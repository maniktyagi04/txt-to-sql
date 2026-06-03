from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.retrieval import SchemaTableMetadata, TableRetrievalResult
from app.services.cache import BaseCache
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")

# ---------------------------------------------------------------------------
# Domain keyword sets used for database-level score boosting.
# When a question clearly references concepts from one BEAVER domain, we apply
# a small additive boost (DOMAIN_BOOST) to tables belonging to that domain so
# they rank higher without ever completely suppressing other candidates.
# ---------------------------------------------------------------------------
_NOVA_KEYWORDS: frozenset[str] = frozenset(
    {
        "instance",
        "instances",
        "vm",
        "vms",
        "hypervisor",
        "hypervisors",
        "compute",
        "computes",
        "flavor",
        "flavors",
        "vcpus",
        "memory_mb",
        "display_name",
        "hostname",
        "hostnames",
        "power_state",
        "shelved",
        "offloaded",
        "cell",
        "cells",
        "aggregate",
        "aggregates",
        "keypair",
        "keypairs",
        "uuid",
        "uuids",
        "root_gb",
        "ephemeral_gb",
        "deleted",
        "nova",
        "openstack",
        "vif",
        "vifs",
        "console",
        "consoles",
        "pci",
    }
)

_NEUTRON_KEYWORDS: frozenset[str] = frozenset(
    {
        "port",
        "ports",
        "subnet",
        "subnets",
        "network",
        "networks",
        "router",
        "routers",
        "dhcp",
        "floatingip",
        "floatingips",
        "vpn",
        "ipsec",
        "gre",
        "vxlan",
        "vlan",
        "agent",
        "agents",
        "rbac",
        "standardattribute",
        "standardattributes",
        "ml2",
        "security_group",
        "security_groups",
        "ip_version",
        "cidr",
        "gateway_ip",
        "neutron",
        "ip_allocation",
        "ipallocations",
    }
)

_DW_KEYWORDS: frozenset[str] = frozenset(
    {
        "department",
        "departments",
        "enrolled",
        "enrollment",
        "enrollments",
        "course",
        "courses",
        "faculty",
        "student",
        "students",
        "history",
        "building",
        "buildings",
        "dlc",
        "iap",
        "term",
        "terms",
        "academic",
        "budget",
        "grade",
        "grades",
        "headcount",
        "salary",
        "salaries",
        "employee",
        "employees",
        "hr",
        "payroll",
        "vendor",
        "vendors",
        "invoice",
        "invoices",
        "payment",
        "payments",
        "warehouse",
        "subject",
        "subjects",
        "catalog",
        "library",
        "tip",
        "sis",
        "responsible_faculty",
        "subject_offered",
        "subject_person",
        "requisition",
        "requisitions",
        "mathematical",
        "chemistry",
        "mathematics",
        "school",
    }
)

# Score added to tables from the detected domain
_DOMAIN_BOOST: float = 0.15


class RetrieverError(RuntimeError):
    """Base exception for retriever failures."""


class SchemaMetadataNotFoundError(RetrieverError):
    """Raised when configured schema metadata cannot be loaded."""


class EmbeddingModelUnavailableError(RetrieverError):
    """Raised when sentence-transformers is not installed or cannot load."""


@dataclass(frozen=True)
class EmbeddedSchemaTable:
    table: SchemaTableMetadata
    embedding: list[float]


class SchemaRetriever:
    """Semantic schema retriever using sentence-transformers embeddings.

    Improvements over the original implementation:
    * Richer schema document representation (all columns + types + all FKs)
    * Upgraded default model: ``BAAI/bge-small-en-v1.5`` (stronger on technical text)
    * Domain-aware score boosting: when a question clearly targets one BEAVER
      database (dw / nova / neutron), tables from that database receive a small
      additive boost before ranking.
    * Calibrated confidence score: normalised to [0, 1] using gap between
      top-1 and top-k median so it reflects true discrimination.
    * Detailed retrieval logging: every retrieved table with its score is logged.
    """

    def __init__(self, settings: Settings, cache: BaseCache | None = None) -> None:
        self.settings = settings
        self.cache = cache
        self._model: Any | None = None
        self._embedded_tables: list[EmbeddedSchemaTable] | None = None

    # ------------------------------------------------------------------
    # Public API (unchanged contract)
    # ------------------------------------------------------------------

    def retrieve(
        self, question: str, top_k: int | None = None
    ) -> list[TableRetrievalResult]:
        selected_top_k = self._normalize_top_k(top_k)

        if self.cache:
            cache_key = BaseCache.generate_key("retrieve", question, selected_top_k)
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.info(
                    "schema_retrieval_cache_hit",
                    extra={"question": question, "top_k": selected_top_k},
                )
                return [
                    TableRetrievalResult.model_validate(item) for item in cached_data
                ]
            logger.info(
                "schema_retrieval_cache_miss",
                extra={"question": question, "top_k": selected_top_k},
            )

        embedded_tables = self._load_or_build_embeddings()

        if not embedded_tables:
            logger.warning("retrieval_empty_schema")
            return []

        question_embedding = self._encode([question])[0]
        predicted_domain = self._detect_domain(question)

        scored_tables = [
            (
                table,
                self._score(question_embedding, table, predicted_domain),
            )
            for table in embedded_tables
        ]
        scored_tables.sort(key=lambda item: item[1], reverse=True)

        top_scores = [s for _, s in scored_tables[:selected_top_k]]
        calibrated_confidence = self._calibrate_confidence(top_scores)

        results = [
            TableRetrievalResult(
                table_name=embedded_table.table.table_name,
                score=round(max(score, 0.0), 4),
                reason=self._build_reason(question, embedded_table.table, score),
                explanation=self._build_reason(question, embedded_table.table, score),
                confidence=round(calibrated_confidence, 4),
            )
            for embedded_table, score in scored_tables[:selected_top_k]
        ]

        # Log retrieved schemas with similarity scores
        logger.info(
            "schema_retrieval_completed",
            extra={
                "question": question[:120],
                "top_k": selected_top_k,
                "result_count": len(results),
                "predicted_domain": predicted_domain,
                "confidence_score": results[0].score if results else 0.0,
                "calibrated_confidence": calibrated_confidence,
                "retrieved_tables": [
                    {"table": r.table_name, "score": r.score} for r in results
                ],
            },
        )

        if self.cache:
            cache_key = BaseCache.generate_key("retrieve", question, selected_top_k)
            self.cache.set(
                cache_key,
                [item.model_dump() for item in results],
                ttl_seconds=self.settings.cache_ttl_seconds,
            )

        return results

    def confidence_score(self, results: list[TableRetrievalResult]) -> float:
        if not results:
            return 0.0
        return results[0].score

    # ------------------------------------------------------------------
    # Private helpers — scoring
    # ------------------------------------------------------------------

    def _normalize_top_k(self, top_k: int | None) -> int:
        configured_top_k = top_k or self.settings.default_retrieval_top_k
        return min(configured_top_k, self.settings.max_retrieval_top_k)

    def _detect_domain(self, question: str) -> str | None:
        """Detect the most likely BEAVER database for a given question."""
        tokens = self._tokens(question)
        nova_hits = len(tokens & _NOVA_KEYWORDS)
        neutron_hits = len(tokens & _NEUTRON_KEYWORDS)
        dw_hits = len(tokens & _DW_KEYWORDS)

        best = max(nova_hits, neutron_hits, dw_hits)
        if best == 0:
            return None
        if nova_hits == best:
            return "nova"
        if neutron_hits == best:
            return "neutron"
        return "dw"

    def _score(
        self,
        question_embedding: list[float],
        embedded_table: EmbeddedSchemaTable,
        predicted_domain: str | None,
    ) -> float:
        """Compute cosine similarity, then apply a domain-level boost."""
        sim = self._cosine_similarity(question_embedding, embedded_table.embedding)
        if predicted_domain:
            table_db = embedded_table.table.table_name.split(".", 1)[0]
            if table_db == predicted_domain:
                sim = min(sim + _DOMAIN_BOOST, 1.0)
        return sim

    def _calibrate_confidence(self, top_scores: list[float]) -> float:
        """Return a calibrated confidence value for the retrieval result set.

        Uses the gap between the top-1 score and the median of remaining
        scores to reflect how discriminative the top result is.
        """
        if not top_scores:
            return 0.0
        if len(top_scores) == 1:
            return round(top_scores[0], 4)
        rest = top_scores[1:]
        median_rest = sorted(rest)[len(rest) // 2]
        gap = top_scores[0] - median_rest
        # Scale gap to [0,1] — a gap of 0.15+ is considered very confident
        calibrated = min(top_scores[0] * 0.6 + gap * 2.5, 1.0)
        return round(max(calibrated, 0.0), 4)

    # ------------------------------------------------------------------
    # Private helpers — embedding store
    # ------------------------------------------------------------------

    def _load_or_build_embeddings(self) -> list[EmbeddedSchemaTable]:
        if self._embedded_tables is not None:
            return self._embedded_tables

        schema_tables = self._load_schema_metadata()
        schema_fingerprint = self._schema_fingerprint(schema_tables)
        embedding_store_path = Path(self.settings.schema_embedding_store_path)
        stored_payload = self._load_embedding_store(embedding_store_path)

        if self._is_embedding_store_current(stored_payload, schema_fingerprint):
            self._embedded_tables = self._deserialize_embedding_store(stored_payload)
            logger.info(
                "schema_embeddings_loaded",
                extra={
                    "path": str(embedding_store_path),
                    "table_count": len(self._embedded_tables),
                    "model_name": self.settings.embedding_model_name,
                },
            )
            return self._embedded_tables

        self._embedded_tables = self._build_embedding_store(
            schema_tables=schema_tables,
            schema_fingerprint=schema_fingerprint,
            embedding_store_path=embedding_store_path,
        )
        return self._embedded_tables

    def _load_schema_metadata(self) -> list[SchemaTableMetadata]:
        schema_path = Path(self.settings.schema_metadata_path)
        if not schema_path.exists():
            raise SchemaMetadataNotFoundError(
                f"Schema metadata file not found: {schema_path}"
            )

        try:
            payload = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaMetadataNotFoundError(
                f"Schema metadata file is not valid JSON: {schema_path}"
            ) from exc

        raw_tables = payload.get("tables", payload)
        if not isinstance(raw_tables, list):
            raise SchemaMetadataNotFoundError(
                "Schema metadata must be a list or an object with a 'tables' list."
            )

        return [SchemaTableMetadata.model_validate(table) for table in raw_tables]

    def _load_embedding_store(
        self, embedding_store_path: Path
    ) -> dict[str, Any] | None:
        if not embedding_store_path.exists():
            return None

        try:
            return json.loads(embedding_store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(
                "schema_embedding_store_invalid",
                extra={"path": str(embedding_store_path)},
            )
            return None

    def _is_embedding_store_current(
        self,
        payload: dict[str, Any] | None,
        schema_fingerprint: str,
    ) -> bool:
        if payload is None:
            return False

        return (
            payload.get("model_name") == self.settings.embedding_model_name
            and payload.get("schema_fingerprint") == schema_fingerprint
            and isinstance(payload.get("tables"), list)
        )

    def _deserialize_embedding_store(
        self,
        payload: dict[str, Any] | None,
    ) -> list[EmbeddedSchemaTable]:
        if payload is None:
            return []

        embedded_tables: list[EmbeddedSchemaTable] = []
        for item in payload.get("tables", []):
            table = SchemaTableMetadata.model_validate(item["metadata"])
            embedding = [float(value) for value in item["embedding"]]
            embedded_tables.append(
                EmbeddedSchemaTable(table=table, embedding=embedding)
            )
        return embedded_tables

    def _build_embedding_store(
        self,
        *,
        schema_tables: list[SchemaTableMetadata],
        schema_fingerprint: str,
        embedding_store_path: Path,
    ) -> list[EmbeddedSchemaTable]:
        documents = [self._schema_document(table) for table in schema_tables]
        embeddings = self._encode(documents)

        embedded_tables = [
            EmbeddedSchemaTable(table=table, embedding=embedding)
            for table, embedding in zip(schema_tables, embeddings, strict=True)
        ]

        embedding_store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_name": self.settings.embedding_model_name,
            "schema_fingerprint": schema_fingerprint,
            "tables": [
                {
                    "metadata": embedded_table.table.model_dump(),
                    "embedding": embedded_table.embedding,
                }
                for embedded_table in embedded_tables
            ],
        }
        embedding_store_path.write_text(json.dumps(payload), encoding="utf-8")

        logger.info(
            "schema_embeddings_generated",
            extra={
                "path": str(embedding_store_path),
                "table_count": len(embedded_tables),
                "model_name": self.settings.embedding_model_name,
            },
        )
        return embedded_tables

    # ------------------------------------------------------------------
    # Private helpers — encoding
    # ------------------------------------------------------------------

    def _encode(self, documents: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(documents, normalize_embeddings=True)
        return [[float(value) for value in embedding] for embedding in embeddings]

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingModelUnavailableError(
                "sentence-transformers is required for schema retrieval."
            ) from exc

        try:
            self._model = SentenceTransformer(self.settings.embedding_model_name)
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                f"Unable to load embedding model: {self.settings.embedding_model_name}"
            ) from exc

        logger.info(
            "embedding_model_loaded",
            extra={"model_name": self.settings.embedding_model_name},
        )
        return self._model

    # ------------------------------------------------------------------
    # Private helpers — schema document builder (richer representation)
    # ------------------------------------------------------------------

    def _schema_document(self, table: SchemaTableMetadata) -> str:
        """Build a rich text document for embedding.

        Includes:
        * Full table name and description
        * All column names with their SQL types (not truncated)
        * All foreign key relationships in natural language form
        * Tags for additional domain signal
        """
        parts = [
            f"table: {table.table_name}",
            f"description: {table.description}",
        ]

        # All columns with types (untruncated)
        if table.column_types:
            col_parts = [f"{col} ({typ})" for col, typ in table.column_types.items()]
            parts.append(f"columns: {', '.join(col_parts)}")
        elif table.columns:
            parts.append(f"columns: {', '.join(table.columns)}")

        # All foreign keys as natural language relationships
        if table.foreign_keys:
            fk_parts = [
                f"{table.table_name}.{fk['from_col']} references "
                f"{fk['to_table']}.{fk['to_col']}"
                for fk in table.foreign_keys
            ]
            parts.append(f"relationships: {'; '.join(fk_parts)}")

        if table.tags:
            parts.append(f"tags: {', '.join(table.tags)}")

        return " ".join(parts).strip()

    # ------------------------------------------------------------------
    # Private helpers — similarity and fingerprinting
    # ------------------------------------------------------------------

    def _schema_fingerprint(self, schema_tables: list[SchemaTableMetadata]) -> str:
        canonical_payload = json.dumps(
            [table.model_dump() for table in schema_tables],
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        numerator = sum(
            left_value * right_value
            for left_value, right_value in zip(left, right, strict=True)
        )
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))

        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0

        similarity = numerator / (left_norm * right_norm)
        return (similarity + 1.0) / 2.0

    # ------------------------------------------------------------------
    # Private helpers — explanation builder
    # ------------------------------------------------------------------

    def _build_reason(
        self,
        question: str,
        table: SchemaTableMetadata,
        score: float,
    ) -> str:
        """Build a detailed human-readable reason for selecting this table."""
        question_terms = self._tokens(question)
        schema_text = self._schema_document(table)
        schema_terms = self._tokens(schema_text)
        matched_terms = sorted(question_terms.intersection(schema_terms))

        parts = table.table_name.split(".", 1)
        schema_prefix = parts[0] if len(parts) == 2 else ""
        bare_table = parts[1] if len(parts) == 2 else parts[0]
        schema_label = f" [{schema_prefix.upper()}]" if schema_prefix else ""

        if matched_terms:
            shown_terms = ", ".join(matched_terms[:6])
            fk_hint = ""
            if table.foreign_keys:
                related = ", ".join(fk["to_table"] for fk in table.foreign_keys[:3])
                fk_hint = f" Related tables: {related}."
            return (
                f"{schema_label} '{bare_table}' matched on terms ({shown_terms}) "
                f"with similarity {score:.3f}.{fk_hint}"
            )

        return (
            f"{schema_label} '{bare_table}' selected by semantic similarity "
            f"(score {score:.3f})."
        )

    def _tokens(self, text: str) -> set[str]:
        return {match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)}

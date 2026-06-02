from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.retrieval import SchemaTableMetadata, TableRetrievalResult
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]+")


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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._embedded_tables: list[EmbeddedSchemaTable] | None = None

    def retrieve(self, question: str, top_k: int | None = None) -> list[TableRetrievalResult]:
        selected_top_k = self._normalize_top_k(top_k)
        embedded_tables = self._load_or_build_embeddings()

        if not embedded_tables:
            logger.warning("retrieval_empty_schema")
            return []

        question_embedding = self._encode([question])[0]
        scored_tables = [
            (
                table,
                self._cosine_similarity(question_embedding, table.embedding),
            )
            for table in embedded_tables
        ]
        scored_tables.sort(key=lambda item: item[1], reverse=True)

        results = [
            TableRetrievalResult(
                table_name=embedded_table.table.table_name,
                score=round(max(score, 0.0), 4),
                reason=self._build_reason(question, embedded_table.table, score),
            )
            for embedded_table, score in scored_tables[:selected_top_k]
        ]

        logger.info(
            "schema_retrieval_completed",
            extra={
                "top_k": selected_top_k,
                "result_count": len(results),
                "confidence_score": results[0].score if results else 0.0,
            },
        )
        return results

    def confidence_score(self, results: list[TableRetrievalResult]) -> float:
        if not results:
            return 0.0
        return results[0].score

    def _normalize_top_k(self, top_k: int | None) -> int:
        configured_top_k = top_k or self.settings.default_retrieval_top_k
        return min(configured_top_k, self.settings.max_retrieval_top_k)

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

    def _load_embedding_store(self, embedding_store_path: Path) -> dict[str, Any] | None:
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
            embedded_tables.append(EmbeddedSchemaTable(table=table, embedding=embedding))
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

    def _encode(self, documents: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(documents, normalize_embeddings=True)
        return [
            [float(value) for value in embedding]
            for embedding in embeddings
        ]

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

    def _schema_document(self, table: SchemaTableMetadata) -> str:
        return " ".join(
            [
                f"table: {table.table_name}",
                f"description: {table.description}",
                f"columns: {', '.join(table.columns)}",
                f"tags: {', '.join(table.tags)}",
            ]
        ).strip()

    def _schema_fingerprint(self, schema_tables: list[SchemaTableMetadata]) -> str:
        canonical_payload = json.dumps(
            [table.model_dump() for table in schema_tables],
            sort_keys=True,
        )
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        numerator = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))

        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0

        similarity = numerator / (left_norm * right_norm)
        return (similarity + 1.0) / 2.0

    def _build_reason(
        self,
        question: str,
        table: SchemaTableMetadata,
        score: float,
    ) -> str:
        question_terms = self._tokens(question)
        schema_text = self._schema_document(table)
        schema_terms = self._tokens(schema_text)
        matched_terms = sorted(question_terms.intersection(schema_terms))

        if matched_terms:
            shown_terms = ", ".join(matched_terms[:5])
            return (
                f"Matched schema metadata terms ({shown_terms}) with semantic "
                f"similarity score {score:.2f}."
            )

        return (
            "Selected by semantic similarity between the question and table "
            f"metadata with score {score:.2f}."
        )

    def _tokens(self, text: str) -> set[str]:
        return {match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)}

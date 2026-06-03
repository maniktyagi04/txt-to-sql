from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.retrieval import TableRetrievalResult, SchemaTableMetadata
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Few-shot examples — curated pairs drawn from the real BEAVER domain
# (dw.* academic warehouse, nova.* compute, neutron.* networking).
# Each example shows the schema context alongside the expected JSON output so
# the model learns output format, alias style, and join patterns at once.
# ---------------------------------------------------------------------------
_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "question": "List all current academic terms with their start and end dates",
        "tables": (
            "Table: dw.ACADEMIC_TERMS\n"
            "  Columns (with types):\n"
            "    TERM_CODE VARCHAR(127), TERM_DESCRIPTION VARCHAR(127),\n"
            "    TERM_START_DATE VARCHAR(255), TERM_END_DATE VARCHAR(255),\n"
            "    IS_CURRENT_TERM VARCHAR(127)\n"
            "  Relationships: none"
        ),
        "sql": (
            "SELECT at.TERM_CODE, at.TERM_DESCRIPTION, "
            "at.TERM_START_DATE, at.TERM_END_DATE "
            "FROM dw.ACADEMIC_TERMS at "
            "WHERE at.IS_CURRENT_TERM = 'Y' "
            "ORDER BY at.TERM_START_DATE DESC "
            "LIMIT 50;"
        ),
        "confidence": "0.97",
        "explanation": (
            "Queries dw.ACADEMIC_TERMS filtered to current terms only, "
            "returning the term code, description, and date range. "
            "IS_CURRENT_TERM is a VARCHAR flag stored as 'Y'/'N'."
        ),
    },
    {
        "question": "Show compute instances and their flavors for active VMs",
        "tables": (
            "Table: nova.instances\n"
            "  Columns (with types):\n"
            "    uuid VARCHAR, display_name VARCHAR, vm_state VARCHAR,\n"
            "    instance_type_id INTEGER, host VARCHAR, deleted INTEGER\n"
            "  Relationships: none\n\n"
            "Table: nova.instance_types\n"
            "  Columns (with types):\n"
            "    id INTEGER, name VARCHAR, vcpus INTEGER,\n"
            "    memory_mb INTEGER, root_gb INTEGER\n"
            "  Relationships: none"
        ),
        "sql": (
            "SELECT i.display_name, i.uuid, i.vm_state, i.host, "
            "it.name AS flavor_name, it.vcpus, it.memory_mb "
            "FROM nova.instances i "
            "JOIN nova.instance_types it ON i.instance_type_id = it.id "
            "WHERE i.deleted = 0 AND i.vm_state = 'active' "
            "ORDER BY i.display_name "
            "LIMIT 100;"
        ),
        "confidence": "0.95",
        "explanation": (
            "Joins nova.instances to nova.instance_types on instance_type_id "
            "to retrieve the flavor details for each active, non-deleted VM."
        ),
    },
    {
        "question": "Show departments with highest enrollment",
        "tables": (
            "Table: beaver.departments\n"
            "  Columns (with types):\n"
            "    department_id INTEGER, department_name VARCHAR, headcount INTEGER\n"
            "  Relationships: none\n\n"
            "Table: beaver.courses\n"
            "  Columns (with types):\n"
            "    course_id INTEGER, course_name VARCHAR, department_id INTEGER,\n"
            "    course_type VARCHAR, credits INTEGER\n"
            "  Relationships: courses.department_id → departments.department_id\n\n"
            "Table: beaver.enrollments\n"
            "  Columns (with types):\n"
            "    enrollment_id INTEGER, student_id INTEGER, course_id INTEGER, grade VARCHAR\n"
            "  Relationships: enrollments.course_id → courses.course_id"
        ),
        "sql": (
            "SELECT d.department_name, COUNT(e.student_id) AS enrollment_count "
            "FROM beaver.departments d "
            "JOIN beaver.courses c ON d.department_id = c.department_id "
            "JOIN beaver.enrollments e ON c.course_id = e.course_id "
            "GROUP BY d.department_name "
            "ORDER BY enrollment_count DESC "
            "LIMIT 25;"
        ),
        "confidence": "0.95",
        "explanation": (
            "Joins departments → courses → enrollments using the foreign key "
            "chain to count total enrolled students per department."
        ),
    },
    {
        "question": "List all network ports with their subnet and network information",
        "tables": (
            "Table: neutron.ports\n"
            "  Columns (with types):\n"
            "    id VARCHAR, network_id VARCHAR, status VARCHAR,\n"
            "    mac_address VARCHAR, device_id VARCHAR, deleted INTEGER\n"
            "  Relationships: ports.network_id → networks.id\n\n"
            "Table: neutron.networks\n"
            "  Columns (with types):\n"
            "    id VARCHAR, name VARCHAR, status VARCHAR, shared INTEGER\n"
            "  Relationships: none"
        ),
        "sql": (
            "SELECT p.id AS port_id, p.mac_address, p.status AS port_status, "
            "n.name AS network_name, n.status AS network_status "
            "FROM neutron.ports p "
            "JOIN neutron.networks n ON p.network_id = n.id "
            "WHERE p.deleted = 0 "
            "ORDER BY n.name, p.id "
            "LIMIT 100;"
        ),
        "confidence": "0.93",
        "explanation": (
            "Joins neutron.ports to neutron.networks on network_id to show "
            "each active port alongside its parent network details."
        ),
    },
]

# ---------------------------------------------------------------------------
# System instruction block — injected at the top of every prompt.
# Rules are explicit and numbered so the model can reference them.
# ---------------------------------------------------------------------------
_SYSTEM_INSTRUCTIONS = """\
You are an expert SQL engineer for an enterprise data platform (BEAVER).
Your task is to write a single, read-only SQL query that correctly answers \
the user's natural language question.

=== STRICT RULES — FOLLOW ALL OF THEM ===
1. ONLY use the tables and columns that appear in the "Retrieved Schema Context" \
section below. Do NOT invent tables, columns, or aliases that are not listed.
2. ONLY generate SELECT statements. Never write INSERT, UPDATE, DELETE, DROP, \
CREATE, ALTER, TRUNCATE, or any mutation.
3. Use schema-qualified table names exactly as given \
(e.g. dw.ACADEMIC_TERMS, nova.instances, neutron.ports).
4. Use the EXACT column names from the schema — column names are case-sensitive \
in PostgreSQL; reproduce them verbatim.
5. When joining tables, ONLY use join conditions that are grounded in the \
"Relationships" entries shown in the schema. Do NOT invent join paths.
6. Always alias every table (e.g. FROM dw.ACADEMIC_TERMS at).
7. For queries that could return many rows (no WHERE equality on a primary key), \
always add LIMIT 100 unless the question explicitly asks for all records.
8. Use standard ANSI SQL that is compatible with PostgreSQL / SQLite.
9. Your entire response MUST be a single valid JSON object — nothing else:
   {"sql": "<your SQL>", "confidence": <float 0.0–1.0>, "explanation": "<clear explanation>"}
10. Set confidence to reflect how completely the provided schema satisfies the \
question (0.0 = cannot answer at all, 1.0 = perfect match with all needed columns).
11. Do NOT wrap the JSON in markdown code fences or any extra text.
12. If the schema context does not contain sufficient information to answer, \
return confidence ≤ 0.3 and set sql to "SELECT 'Insufficient schema context' AS message;".
=== END RULES ===
"""


class SQLPromptBuilder:
    """Builds a structured LLM prompt by resolving full schema metadata for
    the retrieved tables, injecting column types, foreign-key relationships,
    domain-curated few-shot examples, and strong anti-hallucination rules."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._schema_index: dict[str, SchemaTableMetadata] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_prompt(
        self,
        question: str,
        retrieved_tables: list[TableRetrievalResult],
    ) -> str:
        """Return a fully-rendered prompt string ready to be sent to the LLM."""
        schema_index = self._load_schema_index()
        enriched = self._enrich_tables(retrieved_tables, schema_index)
        schema_block = self._format_schema_block(enriched)
        relationships_block = self._format_relationships_block(enriched)
        examples_block = self._format_examples_block(question)
        # Compute a retrieval-based prior confidence to guide the model
        retrieval_confidence = self._compute_retrieval_confidence(retrieved_tables)

        prompt = (
            f"{_SYSTEM_INSTRUCTIONS}\n\n"
            "## Retrieved Schema Context\n\n"
            f"{schema_block}\n\n"
            f"{relationships_block}\n\n"
            "## Few-Shot Examples\n\n"
            f"{examples_block}\n\n"
            "## Question\n\n"
            f"{question}\n\n"
            f"## Retrieval Confidence Prior: {retrieval_confidence:.2f}\n"
            "(Use this as a starting point for your confidence field; "
            "adjust up if you can fully satisfy the question, "
            "adjust down if columns or joins are missing.)\n\n"
            "## Your JSON Response\n"
        )

        logger.debug(
            "prompt_built",
            extra={
                "question_length": len(question),
                "table_count": len(enriched),
                "prompt_length": len(prompt),
                "retrieval_confidence": retrieval_confidence,
            },
        )
        return prompt

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_schema_index(self) -> dict[str, SchemaTableMetadata]:
        """Load and cache schema metadata keyed by table_name."""
        if self._schema_index is not None:
            return self._schema_index

        schema_path = Path(self.settings.schema_metadata_path)
        if not schema_path.exists():
            logger.warning(
                "prompt_builder_schema_not_found",
                extra={"path": str(schema_path)},
            )
            self._schema_index = {}
            return self._schema_index

        raw: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
        tables = raw.get("tables", raw)
        self._schema_index = {
            SchemaTableMetadata.model_validate(
                t
            ).table_name: SchemaTableMetadata.model_validate(t)
            for t in tables
        }
        logger.debug(
            "prompt_builder_schema_loaded",
            extra={"table_count": len(self._schema_index)},
        )
        return self._schema_index

    def _enrich_tables(
        self,
        retrieved: list[TableRetrievalResult],
        index: dict[str, SchemaTableMetadata],
    ) -> list[SchemaTableMetadata]:
        """Return full SchemaTableMetadata for each retrieved table, preserving order."""
        enriched: list[SchemaTableMetadata] = []
        for result in retrieved:
            meta = index.get(result.table_name)
            if meta is None:
                logger.warning(
                    "prompt_builder_table_not_in_metadata",
                    extra={"table_name": result.table_name},
                )
                meta = SchemaTableMetadata(
                    table_name=result.table_name,
                    description="No description available.",
                    columns=[],
                    tags=[],
                )
            enriched.append(meta)
        return enriched

    def _format_schema_block(self, tables: list[SchemaTableMetadata]) -> str:
        """Render tables with column types so the model avoids type mismatches."""
        lines: list[str] = []
        for table in tables:
            col_type_map = table.column_types or {}
            tags_str = ", ".join(table.tags) if table.tags else "none"

            # Build column list: "col_name TYPE" when type is available
            if table.columns:
                col_entries: list[str] = []
                for col in table.columns:
                    col_type = col_type_map.get(col, "")
                    if col_type:
                        col_entries.append(f"{col} {col_type}")
                    else:
                        col_entries.append(col)
                columns_str = ",\n    ".join(col_entries)
            else:
                columns_str = "(no columns listed)"

            lines.append(
                f"Table: {table.table_name}\n"
                f"  Description: {table.description}\n"
                f"  Columns (with types):\n"
                f"    {columns_str}\n"
                f"  Tags: {tags_str}"
            )
        return "\n\n".join(lines)

    def _format_relationships_block(self, tables: list[SchemaTableMetadata]) -> str:
        """Render foreign-key relationships as explicit join hints.

        This directly addresses hallucinated join conditions — the model now
        sees the exact ON clause it should use for every FK relationship.
        """
        rel_lines: list[str] = []
        for table in tables:
            if not table.foreign_keys:
                continue
            for fk in table.foreign_keys:
                from_col = fk.get("from_col", "")
                to_table = fk.get("to_table", "")
                to_col = fk.get("to_col", "")
                if from_col and to_table and to_col:
                    rel_lines.append(
                        f"  {table.table_name}.{from_col} → {to_table}.{to_col}"
                    )

        if not rel_lines:
            return (
                "## Table Relationships\n\n"
                "  (No explicit foreign key relationships found for these tables. "
                "Only join on columns that are logically equivalent based on column names.)"
            )

        body = "\n".join(rel_lines)
        return (
            "## Table Relationships\n\n"
            "Use ONLY these verified join paths:\n"
            f"{body}"
        )

    @staticmethod
    def _format_examples_block(question: str) -> str:
        """Render few-shot examples; select the most domain-relevant ones first."""
        q_lower = question.lower()

        # Score each example by keyword overlap with the question
        def _relevance(ex: dict[str, str]) -> int:
            ex_text = (ex["question"] + " " + ex["tables"]).lower()
            score = 0
            for word in q_lower.split():
                if len(word) > 3 and word in ex_text:
                    score += 1
            return score

        sorted_examples = sorted(_FEW_SHOT_EXAMPLES, key=_relevance, reverse=True)
        # Always show 2 most relevant examples to keep prompt concise
        examples_to_show = sorted_examples[:2]

        lines: list[str] = []
        for i, example in enumerate(examples_to_show, start=1):
            lines.append(
                f"Example {i}:\n"
                f"  Question: {example['question']}\n"
                f"  Available Tables:\n"
                f"    {example['tables']}\n"
                f"  Expected Output:\n"
                f'    {{"sql": "{example["sql"]}", '
                f'"confidence": {example["confidence"]}, '
                f'"explanation": "{example["explanation"]}"}}'
            )
        return "\n\n".join(lines)

    @staticmethod
    def _compute_retrieval_confidence(
        retrieved: list[TableRetrievalResult],
    ) -> float:
        """Compute an aggregate retrieval confidence from per-table scores.

        Strategy:
        - Use the mean of the top-3 table scores as the base confidence.
        - Apply a coverage penalty when fewer than 2 tables are retrieved
          (single-table answers are inherently less reliable).
        """
        if not retrieved:
            return 0.0
        scores = sorted([r.score for r in retrieved], reverse=True)
        top_scores = scores[:3]
        mean_score = sum(top_scores) / len(top_scores)
        # Slight penalty when only 1 table was retrieved
        coverage_factor = 1.0 if len(retrieved) >= 2 else 0.85
        return round(min(1.0, mean_score * coverage_factor), 4)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.retrieval import TableRetrievalResult, SchemaTableMetadata
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Few-shot examples embedded directly — these are domain-curated pairs that
# steer the model toward high-quality, read-only, correctly-joined SQL.
# ---------------------------------------------------------------------------
_FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "question": "What is the total enterprise sales amount by region for the last quarter?",
        "tables": "analytics.sales_orders (order_id, customer_id, product_id, order_date, region, enterprise_sales_amount, discount_amount, order_status)\nanalytics.calendar (date_day, fiscal_year, fiscal_quarter, fiscal_month, week_start_date, is_holiday)",
        "sql": (
            "SELECT so.region, SUM(so.enterprise_sales_amount) AS total_sales "
            "FROM analytics.sales_orders so "
            "JOIN analytics.calendar c ON so.order_date = c.date_day "
            "WHERE c.fiscal_quarter = CONCAT(EXTRACT(YEAR FROM CURRENT_DATE)::text, '-Q', "
            "  EXTRACT(QUARTER FROM CURRENT_DATE - INTERVAL '3 months')::text) "
            "GROUP BY so.region "
            "ORDER BY total_sales DESC;"
        ),
        "confidence": "0.92",
    },
    {
        "question": "Which marketing campaigns had the highest conversion rate last month?",
        "tables": "marketing.campaign_performance (campaign_id, campaign_name, channel, start_date, end_date, impressions, clicks, spend, leads, conversions)",
        "sql": (
            "SELECT campaign_name, channel, "
            "  ROUND(conversions::numeric / NULLIF(clicks, 0) * 100, 2) AS conversion_rate_pct "
            "FROM marketing.campaign_performance "
            "WHERE start_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') "
            "  AND end_date <= DATE_TRUNC('month', CURRENT_DATE) "
            "ORDER BY conversion_rate_pct DESC "
            "LIMIT 10;"
        ),
        "confidence": "0.89",
    },
    {
        "question": "How many high-priority support tickets were unresolved in the past 7 days?",
        "tables": "support.tickets (ticket_id, customer_id, created_at, resolved_at, priority, status, issue_type, first_response_minutes, resolution_minutes, csat_score)",
        "sql": (
            "SELECT COUNT(*) AS unresolved_high_priority_tickets "
            "FROM support.tickets "
            "WHERE priority = 'high' "
            "  AND status != 'resolved' "
            "  AND created_at >= CURRENT_DATE - INTERVAL '7 days';"
        ),
        "confidence": "0.95",
    },
]

_SYSTEM_INSTRUCTIONS = """\
You are an expert SQL engineer for an enterprise data platform.
Your task is to write a single, read-only SQL query that correctly answers the user's natural language question.

Rules:
- Only use the tables and columns explicitly provided in the schema context below.
- Do NOT invent tables, columns, joins, or filters that are not listed.
- Generate only SELECT statements. Never write INSERT, UPDATE, DELETE, DROP, CREATE, or any other mutation.
- Use explicit JOINs with ON conditions when joining tables.
- Always alias tables to avoid ambiguity.
- Use standard ANSI SQL with PostgreSQL-compatible syntax.
- Include a LIMIT clause if the query could return unbounded rows.
- Your entire response MUST be a single valid JSON object and nothing else.
- The JSON must conform to this schema:
  {"sql": "<your SQL here>", "confidence": <float between 0.0 and 1.0>}
- Confidence should reflect how well the schema context satisfies the question (0.0 = cannot answer, 1.0 = perfect match).
- Do NOT wrap the JSON in markdown code fences or any other text.
"""


class SQLPromptBuilder:
    """Builds a structured LLM prompt by resolving full schema metadata for
    the retrieved tables and embedding few-shot examples."""

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
        examples_block = self._format_examples_block()

        prompt = (
            f"{_SYSTEM_INSTRUCTIONS}\n\n"
            "## Retrieved Schema Context\n\n"
            f"{schema_block}\n\n"
            "## Few-Shot Examples\n\n"
            f"{examples_block}\n\n"
            "## Question\n\n"
            f"{question}\n\n"
            "## Your JSON Response\n"
        )

        logger.debug(
            "prompt_built",
            extra={
                "question_length": len(question),
                "table_count": len(enriched),
                "prompt_length": len(prompt),
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
            SchemaTableMetadata.model_validate(t).table_name: SchemaTableMetadata.model_validate(t)
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
                # Fall back to a minimal stub so we never silently drop a table
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
        """Render tables in a structured, model-friendly block."""
        lines: list[str] = []
        for table in tables:
            columns_str = ", ".join(table.columns) if table.columns else "(no columns listed)"
            tags_str = ", ".join(table.tags) if table.tags else "none"
            lines.append(
                f"Table: {table.table_name}\n"
                f"  Description: {table.description}\n"
                f"  Columns: {columns_str}\n"
                f"  Tags: {tags_str}"
            )
        return "\n\n".join(lines)

    def _format_examples_block(self) -> str:
        """Render few-shot examples as numbered blocks."""
        lines: list[str] = []
        for i, example in enumerate(_FEW_SHOT_EXAMPLES, start=1):
            lines.append(
                f"Example {i}:\n"
                f"  Question: {example['question']}\n"
                f"  Available Tables:\n    {example['tables']}\n"
                f"  Expected Output:\n"
                f'    {{"sql": "{example["sql"]}", "confidence": {example["confidence"]}}}'
            )
        return "\n\n".join(lines)

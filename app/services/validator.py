from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, OptimizeError
from sqlglot.optimizer.qualify import qualify

from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SQLValidator:
    """Validates SQL queries against syntax rules and schema metadata using SQLGlot."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._schema_mapping: dict[str, dict[str, str]] | None = None

    def validate(self, sql_query: str) -> dict[str, Any]:
        """Validate a SQL query for syntax, tables, columns, and semantic references.

        Args:
            sql_query: The SQL query string to validate.

        Returns:
            A dict with:
                - "is_valid": bool
                - "errors": list[str]
        """
        errors: list[str] = []

        # 1. Parse the SQL query to verify basic syntax
        try:
            # We parse using the 'postgres' dialect as defined in instructions
            expression = sqlglot.parse_one(sql_query, read="postgres")
        except ParseError as exc:
            err_msg = f"SQL Syntax Error: {exc}"
            logger.warning("sql_validation_syntax_error", extra={"sql": sql_query, "error": err_msg})
            errors.append(err_msg)
            return {"is_valid": False, "errors": errors}
        except Exception as exc:
            err_msg = f"SQL Parsing Failed: {exc}"
            logger.warning("sql_validation_parsing_failed", extra={"sql": sql_query, "error": err_msg})
            errors.append(err_msg)
            return {"is_valid": False, "errors": errors}

        # Load schema index
        schema = self._get_schema_mapping()

        # 2. Table Validation
        # Extract CTEs first so we don't treat them as physical tables
        ctes = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE)}

        tables_in_query: list[tuple[str, str]] = []
        for table_node in expression.find_all(exp.Table):
            db = table_node.db
            name = table_node.name
            
            # If the table is a CTE alias, skip physical schema check
            if name.lower() in ctes:
                continue

            full_name = f"{db}.{name}" if db else name
            tables_in_query.append((full_name, name))

        # Verify that all referenced physical tables exist in the schema
        for full_name, name in tables_in_query:
            if full_name.lower() not in schema and name.lower() not in schema:
                err_msg = f"Table '{full_name}' is not defined in the database schema."
                errors.append(err_msg)

        if errors:
            logger.warning(
                "sql_validation_table_error",
                extra={"sql": sql_query, "errors": errors, "tables_checked": [t[0] for t in tables_in_query]},
            )
            return {"is_valid": False, "errors": errors}

        # 3. Column & Semantic Reference Validation
        # qualify() checks for ambiguous references, column existence, and aliases resolution
        try:
            qualify(expression, schema=schema)
        except OptimizeError as exc:
            err_msg = f"SQL Semantic Error: {exc}"
            errors.append(err_msg)
        except Exception as exc:
            err_msg = f"SQL Semantic Resolution Failed: {exc}"
            errors.append(err_msg)

        if errors:
            logger.warning("sql_validation_semantic_error", extra={"sql": sql_query, "errors": errors})
            return {"is_valid": False, "errors": errors}

        logger.info("sql_validation_succeeded", extra={"sql_length": len(sql_query)})
        return {"is_valid": True, "errors": []}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_schema_mapping(self) -> dict[str, dict[str, str]]:
        """Load and parse the database schema from metadata path into SQLGlot format."""
        if self._schema_mapping is not None:
            return self._schema_mapping

        schema_path = Path(self.settings.schema_metadata_path)
        if not schema_path.exists():
            logger.warning("validator_schema_file_missing", extra={"path": str(schema_path)})
            self._schema_mapping = {}
            return self._schema_mapping

        try:
            raw_data = json.loads(schema_path.read_text(encoding="utf-8"))
            tables = raw_data.get("tables", raw_data)
            
            mapping: dict[str, dict[str, str]] = {}
            for t in tables:
                table_name = t["table_name"]
                columns = t["columns"]
                
                # SQLGlot expects column types (e.g. "VARCHAR") for qualification
                col_map = {col.lower(): "VARCHAR" for col in columns}
                
                # Map fully qualified lowercase table name
                mapping[table_name.lower()] = col_map
                
                # Map base lowercase table name
                base_name = table_name.split(".")[-1]
                mapping[base_name.lower()] = col_map

            self._schema_mapping = mapping
            logger.info("validator_schema_mapping_loaded", extra={"table_count": len(self._schema_mapping)})
            return self._schema_mapping
        except Exception as exc:
            logger.error("validator_schema_loading_failed", extra={"error": str(exc)})
            self._schema_mapping = {}
            return self._schema_mapping

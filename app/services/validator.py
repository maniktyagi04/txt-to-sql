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
    """Validates SQL queries against syntax rules and schema metadata using SQLGlot.

    Checks performed (in order):
    1. SQL syntax — parse with the postgres dialect.
    2. Mutation guard — reject any non-SELECT statements.
    3. Table existence — every referenced table must exist in the schema.
    4. Column existence (via SQLGlot qualify) — checks all column references.
    5. Join sanity — warns when a join ON condition references a column that
       does not exist in the joined tables (best-effort, non-blocking).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._schema_mapping: dict[str, dict[str, str]] | None = None
        # Set of allowed top-level statement types (only SELECT)
        self._allowed_stmt_types: tuple[type, ...] = (exp.Select,)

    def validate(self, sql_query: str) -> dict[str, Any]:
        """Validate a SQL query for syntax, mutation safety, tables, and columns.

        Args:
            sql_query: The SQL query string to validate.

        Returns:
            A dict with:
                - "is_valid": bool
                - "errors": list[str]
                - "warnings": list[str]  (non-fatal issues)
        """
        errors: list[str] = []
        warnings: list[str] = []

        # ------------------------------------------------------------------ #
        # 1. Syntax check
        # ------------------------------------------------------------------ #
        try:
            expression = sqlglot.parse_one(sql_query, read="postgres")
        except ParseError as exc:
            err_msg = f"SQL Syntax Error: {exc}"
            logger.warning(
                "sql_validation_syntax_error",
                extra={"sql": sql_query, "error": err_msg},
            )
            errors.append(err_msg)
            return {"is_valid": False, "errors": errors, "warnings": warnings}
        except Exception as exc:
            err_msg = f"SQL Parsing Failed: {exc}"
            logger.warning(
                "sql_validation_parsing_failed",
                extra={"sql": sql_query, "error": err_msg},
            )
            errors.append(err_msg)
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # ------------------------------------------------------------------ #
        # 2. Mutation guard — only SELECT allowed
        # ------------------------------------------------------------------ #
        if not isinstance(expression, self._allowed_stmt_types):
            stmt_type = type(expression).__name__
            err_msg = (
                f"Only SELECT statements are permitted. "
                f"Detected statement type: {stmt_type}."
            )
            logger.warning(
                "sql_validation_mutation_blocked",
                extra={"sql": sql_query, "stmt_type": stmt_type},
            )
            errors.append(err_msg)
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Load schema mapping
        schema = self._get_schema_mapping()

        # ------------------------------------------------------------------ #
        # 3. Table existence check
        # ------------------------------------------------------------------ #
        # Extract CTEs so we don't treat them as physical tables
        ctes = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE)}

        tables_in_query: list[tuple[str, str]] = []
        for table_node in expression.find_all(exp.Table):
            db = table_node.db
            name = table_node.name

            # Skip CTE references
            if name.lower() in ctes:
                continue

            full_name = f"{db}.{name}" if db else name
            tables_in_query.append((full_name, name))

        unknown_tables: list[str] = []
        for full_name, name in tables_in_query:
            if full_name.lower() not in schema and name.lower() not in schema:
                unknown_tables.append(full_name)

        if unknown_tables:
            for tbl in unknown_tables:
                err_msg = f"Table '{tbl}' is not defined in the database schema."
                errors.append(err_msg)
            logger.warning(
                "sql_validation_table_error",
                extra={
                    "sql": sql_query,
                    "errors": errors,
                    "unknown_tables": unknown_tables,
                },
            )
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # ------------------------------------------------------------------ #
        # 4. Column & semantic reference validation via SQLGlot qualify()
        # ------------------------------------------------------------------ #
        try:
            qualify(expression, schema=schema)  # type: ignore[arg-type]
        except OptimizeError as exc:
            err_msg = f"SQL Semantic Error: {exc}"
            errors.append(err_msg)
            logger.warning(
                "sql_validation_semantic_error",
                extra={"sql": sql_query, "errors": errors},
            )
            return {"is_valid": False, "errors": errors, "warnings": warnings}
        except Exception as exc:
            # qualify() can occasionally raise for complex queries;
            # treat as a non-fatal warning so valid queries aren't blocked.
            warn_msg = f"SQL Semantic Resolution skipped (non-fatal): {exc}"
            warnings.append(warn_msg)
            logger.debug(
                "sql_validation_qualify_skipped",
                extra={"sql": sql_query, "warning": warn_msg},
            )

        # ------------------------------------------------------------------ #
        # 5. Join sanity check (best-effort, non-blocking)
        # ------------------------------------------------------------------ #
        self._check_joins(expression, schema, warnings)  # type: ignore[arg-type]

        logger.info(
            "sql_validation_succeeded",
            extra={"sql_length": len(sql_query), "warnings": warnings},
        )
        return {"is_valid": True, "errors": [], "warnings": warnings}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_joins(
        self,
        expression: exp.Expression,  # type: ignore[override]
        schema: dict[str, dict[str, str]],
        warnings: list[str],
    ) -> None:
        """Best-effort join sanity check.

        Looks at every JOIN...ON EQ condition and verifies that both sides
        reference columns that actually exist in the schema for those tables.
        Appends to *warnings* (not errors) so the query is not hard-rejected.
        """
        try:
            for join in expression.find_all(exp.Join):
                on_clause = join.args.get("on")
                if on_clause is None:
                    continue
                for eq_node in on_clause.find_all(exp.EQ):
                    for col_node in eq_node.find_all(exp.Column):
                        tbl_alias = col_node.table
                        col_name = col_node.name
                        if not tbl_alias or not col_name:
                            continue
                        tbl_cols = schema.get(tbl_alias.lower(), {})
                        if tbl_cols and col_name.lower() not in tbl_cols:
                            warnings.append(
                                f"JOIN sanity: column '{col_name}' not found "
                                f"in table alias '{tbl_alias}' schema entry."
                            )
        except Exception:
            # Join check is best-effort; never crash validation
            pass

    def _get_schema_mapping(self) -> dict[str, dict[str, str]]:
        """Load and parse the database schema from metadata path into SQLGlot format.

        SQLGlot's qualify() expects:
            { "table_name": { "col_name": "TYPE", ... }, ... }

        We map both:
        - Fully-qualified name: "dw.ACADEMIC_TERMS" → {col: type, ...}
        - Base name: "academic_terms" → {col: type, ...}

        Column types are read from the ``column_types`` field when available;
        otherwise we default to VARCHAR so qualify() can at least resolve names.
        """
        if self._schema_mapping is not None:
            return self._schema_mapping

        schema_path = Path(self.settings.schema_metadata_path)
        if not schema_path.exists():
            logger.warning(
                "validator_schema_file_missing", extra={"path": str(schema_path)}
            )
            self._schema_mapping = {}
            return self._schema_mapping

        try:
            raw_data = json.loads(schema_path.read_text(encoding="utf-8"))
            tables = raw_data.get("tables", raw_data)

            mapping: dict[str, dict[str, str]] = {}
            for t in tables:
                table_name: str = t["table_name"]
                columns: list[str] = t.get("columns", [])
                column_types: dict[str, str] = t.get("column_types", {})

                # Build {col_lower: TYPE} — use real type when known
                col_map: dict[str, str] = {}
                for col in columns:
                    raw_type = column_types.get(col, "VARCHAR")
                    # Normalise to a simple base type that SQLGlot understands
                    col_map[col.lower()] = _normalise_type(raw_type)

                # Map fully qualified lowercase name (e.g. "dw.academic_terms")
                mapping[table_name.lower()] = col_map

                # Map bare table name (e.g. "academic_terms")
                base_name = table_name.split(".")[-1].lower()
                if base_name not in mapping:
                    mapping[base_name] = col_map

            self._schema_mapping = mapping
            logger.info(
                "validator_schema_mapping_loaded",
                extra={"table_count": len(self._schema_mapping)},
            )
            return self._schema_mapping
        except Exception as exc:
            logger.error("validator_schema_loading_failed", extra={"error": str(exc)})
            self._schema_mapping = {}
            return self._schema_mapping


# ---------------------------------------------------------------------------
# Helper: normalise raw DB type strings to simple SQLGlot-compatible tokens
# ---------------------------------------------------------------------------

_TYPE_ALIASES: dict[str, str] = {
    "varchar": "TEXT",
    "char": "TEXT",
    "text": "TEXT",
    "nvarchar": "TEXT",
    "clob": "TEXT",
    "integer": "INT",
    "int": "INT",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "number": "DOUBLE",
    "numeric": "DOUBLE",
    "decimal": "DOUBLE",
    "float": "FLOAT",
    "double": "DOUBLE",
    "real": "FLOAT",
    "boolean": "BOOLEAN",
    "bool": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "datetime": "TIMESTAMP",
}


def _normalise_type(raw_type: str) -> str:
    """Convert a raw column type string to a simple SQLGlot-compatible type."""
    base = raw_type.split("(")[0].strip().lower()
    return _TYPE_ALIASES.get(base, "TEXT")

"""SQL Execution Service.

Provides secure, read-only SQLite execution for validated SQL queries,
incorporating strict database timeouts, custom AST compilation authorizers,
telemetry logging, and thread-pool execution for FastAPI.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, TypedDict

from starlette.concurrency import run_in_threadpool

from app.services.validator import SQLValidator
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SQLExecutionError(Exception):
    """Base exception for all SQL execution failures."""

    pass


class SQLValidationError(SQLExecutionError):
    """Raised when the query fails semantic or syntax validation before execution."""

    pass


class SQLTimeoutError(SQLExecutionError):
    """Raised when a query execution exceeds the configured timeout threshold."""

    pass


class SQLSecurityError(SQLExecutionError):
    """Raised when a query attempts to perform unauthorized database operations (DML/DDL)."""

    pass


class ExecutionResult(TypedDict):
    rows: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    execution_time_ms: float


class SQLExecutor:
    """Service layer to safely execute read-only queries against SQLite databases."""

    def __init__(
        self, settings: Settings, validator: SQLValidator | None = None
    ) -> None:
        self.settings = settings
        self.validator = validator or SQLValidator(settings)
        # Database directory sourced from configuration — never hardcoded
        self.db_dir = Path(settings.beaver_db_dir)

    async def execute_query(
        self,
        sql_query: str,
        timeout_seconds: float = 5.0,
        validate: bool = True,
        default_db: str | None = None,
    ) -> ExecutionResult:
        """Asynchronously executes a SQL query in a thread pool to avoid blocking the event loop.

        Args:
            sql_query: The SQL query string to run.
            timeout_seconds: Strict query execution timeout limit.
            validate: Whether to run the SQLValidator pipeline first.
            default_db: Optional default database to open directly (e.g. "dw").

        Returns:
            ExecutionResult containing formatted rows and query metadata.
        """
        # Offload execution to thread pool to preserve event loop reactivity
        return await run_in_threadpool(
            self._execute_query_sync,
            sql_query=sql_query,
            timeout_seconds=timeout_seconds,
            validate=validate,
            default_db=default_db,
        )

    def _execute_query_sync(
        self,
        sql_query: str,
        timeout_seconds: float,
        validate: bool,
        default_db: str | None = None,
    ) -> ExecutionResult:
        """Synchronously connects to SQLite, validates, compiles, and runs the query under safety guardrails."""
        start_time = time.perf_counter()

        logger.info(
            "sql_execution_start",
            extra={
                "sql_length": len(sql_query),
                "timeout_seconds": timeout_seconds,
                "validate": validate,
                "default_db": default_db,
            },
        )

        # 1. Validation Gate
        if validate:
            validation = self.validator.validate(sql_query)
            if not validation["is_valid"]:
                err_msg = f"SQL query failed validation: {validation['errors']}"
                logger.warning(
                    "sql_execution_validation_blocked",
                    extra={"sql": sql_query, "errors": validation["errors"]},
                )
                raise SQLValidationError(err_msg)

        # Ensure database directory and databases are present
        if not self.db_dir.exists():
            raise SQLExecutionError(
                f"Database directory '{self.db_dir}' does not exist. "
                "Run init_databases() or set BEAVER_DB_DIR env var."
            )

        # 2. Establish connection and attach schemas
        # Start with the default/anchor database, then attach each BEAVER schema.
        db_to_open = ":memory:"
        if default_db:
            db_file = self.db_dir / f"{default_db}.db"
            if db_file.exists():
                db_to_open = str(db_file)

        conn = sqlite3.connect(db_to_open)
        cursor = conn.cursor()

        # Determine which schemas to attach from configuration
        schema_names = self.settings.beaver_db_names

        try:
            # Attach each BEAVER database as its schema identifier (dw, nova, neutron)
            attached: list[str] = []
            for schema in schema_names:
                db_file = self.db_dir / f"{schema}.db"
                if not db_file.exists():
                    logger.warning(
                        "beaver_db_file_missing",
                        extra={"schema": schema, "path": str(db_file)},
                    )
                    continue
                conn.execute(f"ATTACH DATABASE '{db_file}' AS {schema};")
                attached.append(schema)

            if not attached:
                raise SQLExecutionError(
                    f"No BEAVER database files found in '{self.db_dir}'. "
                    f"Expected: {[f'{s}.db' for s in schema_names]}. "
                    "Copy the files or set BEAVER_DB_SOURCE_DIR."
                )

            # 3. Security Authorizer Injection
            # Compile-time protection denying DML/DDL operations
            def sqlite_authorizer(
                action_code: int,
                arg1: str | None,
                arg2: str | None,
                db_name: str | None,
                trigger_name: str | None,
            ) -> int:
                # Allowed actions for read-only query compiler
                if action_code in (
                    sqlite3.SQLITE_SELECT,
                    sqlite3.SQLITE_READ,
                    sqlite3.SQLITE_FUNCTION,
                ):
                    return sqlite3.SQLITE_OK

                logger.warning(
                    "sql_execution_authorization_denied",
                    extra={
                        "action_code": action_code,
                        "arg1": arg1,
                        "arg2": arg2,
                        "db_name": db_name,
                        "sql": sql_query,
                    },
                )
                return sqlite3.SQLITE_DENY

            conn.set_authorizer(sqlite_authorizer)

            # 4. Timeout VM Progress Handler Injection
            # Checks time delta inside SQLite virtual machine execution loop
            start_execution_time = time.time()

            def progress_handler() -> int:
                if time.time() - start_execution_time > timeout_seconds:
                    # Return non-zero to abort execution immediately
                    return 1
                return 0

            # Trigger progress_handler every instruction for quick and safe query cancellation
            conn.set_progress_handler(progress_handler, 1)

            # 5. Execute query
            cursor.execute(sql_query)

            # Fetch results
            raw_rows = cursor.fetchall()
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else []
            )

            # Format row output as list of dicts mapping column keys to values
            rows = [dict(zip(columns, row)) for row in raw_rows]
            row_count = len(rows)

            latency_ms = (time.perf_counter() - start_time) * 1000.0

            logger.info(
                "sql_execution_success",
                extra={
                    "row_count": row_count,
                    "latency_ms": latency_ms,
                    "sql": sql_query,
                },
            )

            return {
                "rows": rows,
                "columns": columns,
                "row_count": row_count,
                "execution_time_ms": round(latency_ms, 2),
            }

        except sqlite3.DatabaseError as exc:
            # OperationalError with "interrupted" is raised by progress_handler timeout abort
            exc_str = str(exc)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if "interrupted" in exc_str or "abort" in exc_str:
                logger.error(
                    "sql_execution_timeout",
                    extra={
                        "error": exc_str,
                        "sql": sql_query,
                        "latency_ms": latency_ms,
                    },
                )
                raise SQLTimeoutError(
                    f"Database query execution exceeded timeout limit of {timeout_seconds}s."
                ) from exc

            if "not authorized" in exc_str or "authorizer" in exc_str:
                logger.error(
                    "sql_execution_security_violation",
                    extra={
                        "error": exc_str,
                        "sql": sql_query,
                        "latency_ms": latency_ms,
                    },
                )
                raise SQLSecurityError(
                    "Query execution denied: destructive or unauthorized operation detected."
                ) from exc

            logger.error(
                "sql_execution_database_error",
                extra={"error": exc_str, "sql": sql_query, "latency_ms": latency_ms},
            )
            raise SQLExecutionError(f"Database error occurred: {exc_str}") from exc

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(
                "sql_execution_failed",
                extra={"error": str(exc), "sql": sql_query, "latency_ms": latency_ms},
            )
            raise SQLExecutionError(f"SQL execution failed: {exc}") from exc

        finally:
            conn.close()

"""SQL Execution Router.

Exposes the POST /execute endpoint, providing secure query execution
with error mapping to appropriate HTTP status codes.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.execution import ExecuteSQLRequest, ExecuteSQLResponse
from app.services.executor import (
    SQLExecutor,
    SQLExecutionError,
    SQLValidationError,
    SQLSecurityError,
    SQLTimeoutError,
)
from app.services.validator import SQLValidator
from app.utils.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency factories — cached per process via lru_cache
# ---------------------------------------------------------------------------


@lru_cache
def get_sql_validator() -> SQLValidator:
    return SQLValidator(get_settings())


@lru_cache
def get_sql_executor() -> SQLExecutor:
    # Pass settings and cached validator to SQLExecutor
    return SQLExecutor(get_settings(), get_sql_validator())


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/execute",
    response_model=ExecuteSQLResponse,
    summary="Execute validated read-only SQL queries against SQLite",
    description=(
        "Accepts a SQL query, performs strict schema/semantic validation, "
        "and executes it in a highly-controlled, read-only SQLite transaction with execution timeouts."
    ),
)
async def execute_sql(
    request: ExecuteSQLRequest,
    executor: SQLExecutor = Depends(get_sql_executor),
) -> ExecuteSQLResponse:
    logger.info(
        "api_execute_sql_request",
        extra={
            "sql_length": len(request.sql),
            "timeout_seconds": request.timeout_seconds,
        },
    )

    try:
        # Execute query. Validation runs automatically by default inside execute_query
        result = await executor.execute_query(
            sql_query=request.sql,
            timeout_seconds=request.timeout_seconds,
            validate=True,
        )
        return ExecuteSQLResponse(
            rows=result["rows"],
            columns=result["columns"],
            row_count=result["row_count"],
            execution_time_ms=result["execution_time_ms"],
        )

    except SQLValidationError as exc:
        logger.warning(
            "api_execute_validation_failed",
            extra={"error": str(exc), "sql": request.sql},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"SQL Validation Failed: {exc}",
        ) from exc

    except SQLSecurityError as exc:
        logger.error(
            "api_execute_security_violation",
            extra={"error": str(exc), "sql": request.sql},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"SQL Security Violation: {exc}",
        ) from exc

    except SQLTimeoutError as exc:
        logger.error(
            "api_execute_timeout", extra={"error": str(exc), "sql": request.sql}
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"SQL Execution Timeout: {exc}",
        ) from exc

    except SQLExecutionError as exc:
        logger.error(
            "api_execute_database_error", extra={"error": str(exc), "sql": request.sql}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SQL Execution Database Error: {exc}",
        ) from exc

    except Exception as exc:
        logger.error(
            "api_execute_unhandled_error", extra={"error": str(exc), "sql": request.sql}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal database error occurred during execution.",
        ) from exc

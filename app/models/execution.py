"""Pydantic schemas for the SQL Execution layer."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class ExecuteSQLRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=10,
        examples=["SELECT * FROM analytics.sales_orders LIMIT 10;"],
        description="The validated SQL query to execute against SQLite.",
    )
    timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Strict execution timeout threshold in seconds.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sql": "SELECT * FROM analytics.sales_orders LIMIT 10;",
                "timeout_seconds": 5.0,
            }
        }
    )


class ExecuteSQLResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(
        ...,
        description="Tabular result rows formatted as list of dictionaries mapping columns to values.",
    )
    columns: list[str] = Field(
        ...,
        description="Ordered list of column names in the result set.",
    )
    row_count: int = Field(
        ...,
        ge=0,
        description="Number of rows returned in the result set.",
    )
    execution_time_ms: float = Field(
        ...,
        ge=0.0,
        description="Database query execution latency in milliseconds.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "rows": [
                    {
                        "order_id": 1,
                        "customer_id": "C001",
                        "enterprise_sales_amount": 15000.0,
                    }
                ],
                "columns": ["order_id", "customer_id", "enterprise_sales_amount"],
                "row_count": 1,
                "execution_time_ms": 2.45,
            }
        }
    )

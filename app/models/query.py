"""Pydantic models for the end-to-end query pipeline endpoint (POST /query)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict


class QueryRequest(BaseModel):
    """Single natural-language question that drives the full pipeline."""

    question: str = Field(
        ...,
        min_length=3,
        examples=["What are the top 5 campaigns by conversions?"],
        description="Natural language question to convert into SQL and optionally execute.",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Number of schema tables to retrieve. Defaults to server setting.",
    )
    execute: bool = Field(
        default=True,
        description="Whether to execute the validated SQL and return result rows.",
    )
    timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Execution timeout in seconds (only used when execute=True).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What are the top 5 campaigns by conversions?",
                "top_k": 5,
                "execute": True,
                "timeout_seconds": 5.0,
            }
        }
    )


class RetrievalStage(BaseModel):
    """Retrieval stage output embedded in QueryResponse."""

    tables: list[str] = Field(..., description="Ordered list of retrieved table names.")
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Top retrieval similarity score."
    )


class GenerationStage(BaseModel):
    """SQL generation stage output embedded in QueryResponse."""

    sql: str = Field(..., description="Generated and validated SQL query.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="LLM generation confidence score."
    )


class ExecutionStage(BaseModel):
    """Execution stage output embedded in QueryResponse."""

    rows: list[dict[str, Any]] = Field(
        ..., description="Result rows as list of column→value dicts."
    )
    columns: list[str] = Field(..., description="Ordered column names in result set.")
    row_count: int = Field(..., ge=0, description="Number of rows returned.")
    execution_time_ms: float = Field(
        ..., ge=0.0, description="Database execution latency in milliseconds."
    )


class QueryResponse(BaseModel):
    """Complete end-to-end pipeline response."""

    question: str = Field(..., description="Original natural language question.")
    retrieval: RetrievalStage
    generation: GenerationStage
    execution: ExecutionStage | None = Field(
        default=None,
        description="Execution results, or null when execute=False.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What are the top 5 campaigns by conversions?",
                "retrieval": {
                    "tables": ["marketing.campaign_performance"],
                    "confidence_score": 0.88,
                },
                "generation": {
                    "sql": "SELECT campaign_name, conversions FROM marketing.campaign_performance ORDER BY conversions DESC LIMIT 5;",
                    "confidence": 0.94,
                },
                "execution": {
                    "rows": [
                        {"campaign_name": "Spring Cloud Drive", "conversions": 320}
                    ],
                    "columns": ["campaign_name", "conversions"],
                    "row_count": 1,
                    "execution_time_ms": 3.2,
                },
            }
        }
    )

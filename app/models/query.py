"""Pydantic models for the end-to-end query pipeline endpoint (POST /query)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict
from app.models.retrieval import TableRetrievalResult


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
    retrieved_tables: list[TableRetrievalResult] = Field(
        ..., description="List of retrieved tables with their retrieval scores and explanations."
    )
    generated_sql: str = Field(..., description="The generated SQL query.")
    sql_explanation: str = Field(..., description="Explanation of the generated SQL query.")
    validation_result: dict[str, Any] = Field(
        ..., description="Validation result indicating whether the query is valid and listing any errors."
    )
    execution_result: dict[str, Any] | None = Field(
        default=None,
        description="Execution result rows and column names, or null when execution is skipped/fails.",
    )
    latency_ms: float = Field(..., description="Total pipeline latency in milliseconds.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "Show departments with highest enrollment",
                "retrieved_tables": [
                    {
                        "table_name": "beaver.departments",
                        "score": 0.95,
                        "reason": "Required department metadata for query resolution.",
                        "explanation": "Provides department names and core headcounts.",
                        "confidence": 0.95,
                    }
                ],
                "generated_sql": "SELECT d.department_name, COUNT(e.student_id) AS enrollment_count FROM beaver.departments d JOIN beaver.courses c ON d.department_id = c.department_id JOIN beaver.enrollments e ON c.course_id = e.course_id GROUP BY d.department_name ORDER BY enrollment_count DESC;",
                "sql_explanation": "This query joins departments to courses and then to enrollments to count the total student enrollments per department.",
                "validation_result": {"is_valid": True, "errors": []},
                "execution_result": {
                    "rows": [
                        {"department_name": "Computer Science", "enrollment_count": 5}
                    ],
                    "columns": ["department_name", "enrollment_count"],
                    "row_count": 1,
                    "execution_time_ms": 1.5,
                },
                "latency_ms": 125.4,
            }
        }
    )

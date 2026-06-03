"""Benchmark Endpoint Router.

Provides POST /benchmark to execute evaluations across the Beaver academic dataset.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.routes.query import get_query_pipeline, get_sql_executor
from app.services.benchmark import BenchmarkService
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    dry_run: bool = Field(
        default=False,
        description="Whether to run benchmark against mock pipelines or dry run without LLM calls.",
    )
    limit_per_domain: int = Field(
        default=10,
        description="Number of queries to load and run per parquet file/domain (default: 10).",
    )


class BenchmarkResponse(BaseModel):
    total_queries: int = Field(..., examples=[25])
    metrics: dict[str, Any] = Field(
        ...,
        examples=[
            {
                "retrieval_recall_at_5": 1.0,
                "retrieval_recall_at_10": 1.0,
                "sql_exact_match_accuracy": 0.95,
                "sql_execution_match_accuracy": 0.95,
                "parsing_success_rate": 1.0,
                "average_latency_ms": 42.5,
            }
        ],
    )
    subtask_breakdown: dict[str, Any] = Field(
        ..., description="Subtask performance breakdown."
    )
    error_analysis: dict[str, Any] = Field(
        ..., description="Detailed logs of failed queries."
    )
    overall_duration_ms: float = Field(
        ..., description="Total execution time of the benchmark."
    )
    dataset_statistics: dict[str, Any] = Field(
        default_factory=dict, description="Statistics of the loaded datasets."
    )
    failure_categorization: dict[str, Any] = Field(
        default_factory=dict, description="Categorization of failures."
    )
    benchmark_summary: dict[str, Any] = Field(
        default_factory=dict, description="Summary and recommendations."
    )


# ---------------------------------------------------------------------------
# Dependency Injection
# ---------------------------------------------------------------------------


@lru_cache
def get_benchmark_service(
    pipeline=Depends(get_query_pipeline),
    executor=Depends(get_sql_executor),
) -> BenchmarkService:
    return BenchmarkService(pipeline=pipeline, executor=executor)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/benchmark",
    response_model=BenchmarkResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute Text-to-SQL benchmark suite",
    description="Runs 25 standard evaluation cases against the Beaver academic database and returns metrics.",
)
async def run_benchmark(
    request: BenchmarkRequest,
    service: BenchmarkService = Depends(get_benchmark_service),
) -> BenchmarkResponse:
    logger.info(
        "benchmark_execution_started",
        extra={
            "dry_run": request.dry_run,
            "limit_per_domain": request.limit_per_domain,
        },
    )
    result = await service.run_benchmark(
        dry_run=request.dry_run,
        limit_per_domain=request.limit_per_domain,
    )
    logger.info(
        "benchmark_execution_completed",
        extra={"duration_ms": result["overall_duration_ms"]},
    )
    return BenchmarkResponse(
        total_queries=result["total_queries"],
        metrics=result["metrics"],
        subtask_breakdown=result["subtask_breakdown"],
        error_analysis=result["error_analysis"],
        overall_duration_ms=result["overall_duration_ms"],
        dataset_statistics=result.get("dataset_statistics", {}),
        failure_categorization=result.get("failure_categorization", {}),
        benchmark_summary=result.get("benchmark_summary", {}),
    )

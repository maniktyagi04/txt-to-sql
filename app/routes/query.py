"""End-to-End Query Pipeline Router.

Exposes POST /query — accepts a single natural-language question and
runs the full Retrieve → Generate → Validate → Execute pipeline,
returning structured per-stage results in one response.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.query import (
    QueryRequest,
    QueryResponse,
)
from app.services.pipeline import (
    QueryPipeline,
    PipelineError,
    PipelineRetrievalError,
    PipelineGenerationError,
    PipelineValidationError,
    PipelineExecutionError,
)
from app.services.cache import get_cache
from app.services.retriever import SchemaRetriever
from app.services.prompt_builder import SQLPromptBuilder
from app.services.llm_service import GeminiLLMService
from app.services.validator import SQLValidator
from app.services.executor import SQLExecutor
from app.utils.config import Settings, get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency factories — lru_cache ensures singletons per process
# ---------------------------------------------------------------------------


@lru_cache
def get_retriever() -> SchemaRetriever:
    return SchemaRetriever(get_settings(), get_cache())


@lru_cache
def get_prompt_builder() -> SQLPromptBuilder:
    return SQLPromptBuilder(get_settings())


@lru_cache
def get_llm_service() -> GeminiLLMService:
    return GeminiLLMService(get_settings(), get_cache())


@lru_cache
def get_sql_validator() -> SQLValidator:
    return SQLValidator(get_settings())


@lru_cache
def get_sql_executor() -> SQLExecutor:
    return SQLExecutor(get_settings(), get_sql_validator())


@lru_cache
def get_query_pipeline() -> QueryPipeline:
    settings: Settings = get_settings()
    return QueryPipeline(
        settings=settings,
        retriever=get_retriever(),
        prompt_builder=get_prompt_builder(),
        llm_service=get_llm_service(),
        validator=get_sql_validator(),
        executor=get_sql_executor(),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Run the full Text-to-SQL pipeline from a natural language question",
    description=(
        "Accepts a natural language question and orchestrates the complete pipeline: "
        "schema retrieval → SQL generation → validation → optional execution. "
        "Returns per-stage results including retrieved tables, generated SQL, "
        "confidence scores, and (when execute=True) the query result rows."
    ),
)
async def run_query(
    request: QueryRequest,
    pipeline: QueryPipeline = Depends(get_query_pipeline),
) -> QueryResponse:
    logger.info(
        "api_query_request",
        extra={
            "question_length": len(request.question),
            "execute": request.execute,
            "top_k": request.top_k,
            "timeout_seconds": request.timeout_seconds,
        },
    )

    try:
        result = await pipeline.run(
            question=request.question,
            top_k=request.top_k,
            execute=request.execute,
            timeout_seconds=request.timeout_seconds,
        )
    except PipelineRetrievalError as exc:
        logger.error("api_query_retrieval_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Schema retrieval failed: {exc}",
        ) from exc
    except PipelineGenerationError as exc:
        logger.error("api_query_generation_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"SQL generation failed: {exc}",
        ) from exc
    except PipelineValidationError as exc:
        logger.error("api_query_validation_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Generated SQL failed validation: {exc}",
        ) from exc
    except PipelineExecutionError as exc:
        logger.error("api_query_execution_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SQL execution failed: {exc}",
        ) from exc
    except PipelineError as exc:
        logger.error("api_query_pipeline_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("api_query_unhandled_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred in the query pipeline.",
        ) from exc

    return QueryResponse(
        question=result.question,
        retrieved_tables=result.retrieved_tables,
        generated_sql=result.generated_sql,
        sql_explanation=result.sql_explanation,
        validation_result=result.validation_result,
        validation_warnings=result.validation_warnings,
        execution_result=result.execution_result,
        confidence_score=result.confidence_score,
        latency_ms=result.latency_ms,
    )

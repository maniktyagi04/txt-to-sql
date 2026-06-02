"""End-to-End Query Pipeline Service.

Orchestrates the full Retrieve → Generate → Validate → Execute pipeline
in a single call, providing structured per-stage results with full telemetry.
"""

from __future__ import annotations

from typing import Any

import time

from starlette.concurrency import run_in_threadpool

from app.models.retrieval import TableRetrievalResult

from app.services.retriever import SchemaRetriever
from app.services.prompt_builder import SQLPromptBuilder
from app.services.llm_service import (
    GeminiLLMService,
    LLMServiceError,
    LLMUnavailableError,
    LLMMaxRetriesExceededError,
    LLMResponseParseError,
)
from app.services.validator import SQLValidator
from app.services.executor import (
    SQLExecutor,
    SQLExecutionError,
    SQLValidationError,
    SQLSecurityError,
    SQLTimeoutError,
)
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class PipelineError(Exception):
    """Base class for pipeline orchestration errors."""

    pass


class PipelineRetrievalError(PipelineError):
    """Raised when schema retrieval fails."""

    pass


class PipelineGenerationError(PipelineError):
    """Raised when LLM SQL generation fails."""

    pass


class PipelineValidationError(PipelineError):
    """Raised when SQL validation rejects the generated query."""

    pass


class PipelineExecutionError(PipelineError):
    """Raised when SQL execution fails."""

    pass


class PipelineResult:
    """Holds full per-stage results from the query pipeline."""

    def __init__(
        self,
        question: str,
        retrieved_tables: list[TableRetrievalResult],
        generated_sql: str,
        sql_explanation: str,
        validation_result: dict[str, Any],
        execution_result: dict[str, Any] | None,
        latency_ms: float,
    ) -> None:
        self.question = question
        self.retrieved_tables = retrieved_tables
        self.generated_sql = generated_sql
        self.sql_explanation = sql_explanation
        self.validation_result = validation_result
        self.execution_result = execution_result
        self.latency_ms = latency_ms


class QueryPipeline:
    """Orchestrates the full text-to-SQL query pipeline."""

    def __init__(
        self,
        settings: Settings,
        retriever: SchemaRetriever,
        prompt_builder: SQLPromptBuilder,
        llm_service: GeminiLLMService,
        validator: SQLValidator,
        executor: SQLExecutor,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.prompt_builder = prompt_builder
        self.llm_service = llm_service
        self.validator = validator
        self.executor = executor

    async def run(
        self,
        question: str,
        top_k: int | None = None,
        execute: bool = True,
        timeout_seconds: float = 5.0,
    ) -> PipelineResult:
        """Run the full pipeline from question to optional execution.

        Args:
            question: Natural language question.
            top_k: Number of schema tables to retrieve.
            execute: Whether to run the validated SQL.
            timeout_seconds: Execution timeout in seconds.

        Returns:
            PipelineResult with per-stage telemetry.
        """
        pipeline_start = time.perf_counter()

        logger.info(
            "pipeline_start",
            extra={
                "question_length": len(question),
                "execute": execute,
                "top_k": top_k,
            },
        )

        # ------------------------------------------------------------------ #
        # Stage 1: Schema Retrieval
        # ------------------------------------------------------------------ #
        effective_top_k = top_k or self.settings.default_retrieval_top_k
        effective_top_k = min(effective_top_k, self.settings.max_retrieval_top_k)

        try:
            retrieved_tables: list[TableRetrievalResult] = await run_in_threadpool(
                self.retriever.retrieve,
                question,
                effective_top_k,
            )
        except Exception as exc:
            logger.error("pipeline_retrieval_failed", extra={"error": str(exc)})
            raise PipelineRetrievalError(f"Schema retrieval failed: {exc}") from exc

        logger.info(
            "pipeline_retrieval_done",
            extra={
                "table_count": len(retrieved_tables),
            },
        )

        # ------------------------------------------------------------------ #
        # Stage 2: SQL Generation & Explanation
        # ------------------------------------------------------------------ #
        try:
            prompt = self.prompt_builder.build_prompt(
                question=question,
                retrieved_tables=retrieved_tables,
            )
        except Exception as exc:
            logger.error("pipeline_prompt_build_failed", extra={"error": str(exc)})
            raise PipelineGenerationError(f"Prompt construction failed: {exc}") from exc

        try:
            llm_result = await run_in_threadpool(self.llm_service.generate, prompt)
        except LLMUnavailableError as exc:
            raise PipelineGenerationError(f"LLM unavailable: {exc}") from exc
        except LLMMaxRetriesExceededError as exc:
            raise PipelineGenerationError(f"LLM max retries exceeded: {exc}") from exc
        except LLMResponseParseError as exc:
            raise PipelineGenerationError(f"LLM response parse error: {exc}") from exc
        except LLMServiceError as exc:
            raise PipelineGenerationError(f"LLM service error: {exc}") from exc

        logger.info(
            "pipeline_generation_done",
            extra={
                "sql_length": len(llm_result.sql),
                "confidence": llm_result.confidence,
                "latency_ms": round(llm_result.latency_ms, 2),
            },
        )

        # ------------------------------------------------------------------ #
        # Stage 3: SQL Validation
        # ------------------------------------------------------------------ #
        validation = self.validator.validate(llm_result.sql)
        if not validation["is_valid"]:
            logger.error(
                "pipeline_validation_failed",
                extra={"errors": validation["errors"], "sql": llm_result.sql},
            )
            raise PipelineValidationError(
                f"SQL validation failed: {validation['errors']}"
            )

        logger.info("pipeline_validation_passed")

        # ------------------------------------------------------------------ #
        # Stage 4: SQL Execution (optional)
        # ------------------------------------------------------------------ #
        execution_result: dict[str, Any] | None = None
        if execute:
            try:
                exec_result = await self.executor.execute_query(
                    sql_query=llm_result.sql,
                    timeout_seconds=timeout_seconds,
                    validate=False,  # Already validated in Stage 3
                )
                execution_result = {
                    "rows": exec_result["rows"],
                    "columns": exec_result["columns"],
                    "row_count": exec_result["row_count"],
                    "execution_time_ms": exec_result["execution_time_ms"],
                }
                logger.info(
                    "pipeline_execution_done",
                    extra={
                        "row_count": exec_result["row_count"],
                        "latency_ms": exec_result["execution_time_ms"],
                    },
                )
            except (
                SQLValidationError,
                SQLSecurityError,
                SQLTimeoutError,
                SQLExecutionError,
            ) as exc:
                logger.error("pipeline_execution_failed", extra={"error": str(exc)})
                raise PipelineExecutionError(f"SQL execution failed: {exc}") from exc

        latency_ms = (time.perf_counter() - pipeline_start) * 1000.0
        logger.info(
            "pipeline_complete",
            extra={"total_latency_ms": round(latency_ms, 2), "execute": execute},
        )

        return PipelineResult(
            question=question,
            retrieved_tables=retrieved_tables,
            generated_sql=llm_result.sql,
            sql_explanation=llm_result.explanation,
            validation_result=validation,
            execution_result=execution_result,
            latency_ms=latency_ms,
        )

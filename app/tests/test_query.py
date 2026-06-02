"""Tests for the End-to-End Query Pipeline.

Coverage:
- QueryPipeline service: full success path (mock LLM), generate-only path (execute=False).
- PipelineError propagation: retrieval failure, generation failure, validation failure, execution failure.
- POST /query endpoint: 200 success, 422 validation block, 503 generation unavailable, 400 execution failure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.retrieval import TableRetrievalResult
from app.models.query import GenerationStage, RetrievalStage, ExecutionStage
from app.services.pipeline import (
    QueryPipeline,
    PipelineRetrievalError,
    PipelineGenerationError,
    PipelineValidationError,
    PipelineExecutionError,
)
from app.services.llm_service import (
    GenerationResult,
    LLMUnavailableError,
)
from app.services.executor import SQLTimeoutError
from app.utils.config import get_settings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_SQL = (
    "SELECT campaign_name, conversions "
    "FROM marketing.campaign_performance "
    "ORDER BY conversions DESC LIMIT 5;"
)

MOCK_RETRIEVED_TABLES = [
    TableRetrievalResult(
        table_name="marketing.campaign_performance",
        score=0.88,
        reason="Direct match for campaigns and conversions.",
    )
]

MOCK_LLM_RESULT = GenerationResult(
    sql=VALID_SQL,
    confidence=0.94,
    raw_response='{"sql": "...", "confidence": 0.94}',
    latency_ms=100.0,
    attempt=1,
)

MOCK_EXEC_RESULT = {
    "rows": [{"campaign_name": "Spring Cloud Drive", "conversions": 320}],
    "columns": ["campaign_name", "conversions"],
    "row_count": 1,
    "execution_time_ms": 2.1,
}


def _make_pipeline(
    retriever=None,
    prompt_builder=None,
    llm_service=None,
    validator=None,
    executor=None,
) -> QueryPipeline:
    """Build a QueryPipeline with all dependencies mocked by default."""
    settings = get_settings()

    # Retriever
    if retriever is None:
        retriever = MagicMock()
        retriever.retrieve.return_value = MOCK_RETRIEVED_TABLES
        retriever.confidence_score.return_value = 0.88
        retriever.settings = settings

    # Prompt builder
    if prompt_builder is None:
        prompt_builder = MagicMock()
        prompt_builder.build_prompt.return_value = "built prompt"

    # LLM service
    if llm_service is None:
        llm_service = MagicMock()
        llm_service.generate.return_value = MOCK_LLM_RESULT

    # Validator
    if validator is None:
        validator = MagicMock()
        validator.validate.return_value = {"is_valid": True, "errors": []}

    # Executor
    if executor is None:
        executor = MagicMock()
        executor.execute_query = AsyncMock(return_value=MOCK_EXEC_RESULT)

    return QueryPipeline(
        settings=settings,
        retriever=retriever,
        prompt_builder=prompt_builder,
        llm_service=llm_service,
        validator=validator,
        executor=executor,
    )


# ---------------------------------------------------------------------------
# QueryPipeline Unit Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestQueryPipeline:

    async def test_full_pipeline_success(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(
            question="Which campaigns had the most conversions?",
            execute=True,
        )
        assert result.question == "Which campaigns had the most conversions?"
        assert result.retrieval.tables == ["marketing.campaign_performance"]
        assert result.retrieval.confidence_score == 0.88
        assert result.generation.sql == VALID_SQL
        assert result.generation.confidence == 0.94
        assert result.execution is not None
        assert result.execution.row_count == 1
        assert result.execution.rows[0]["campaign_name"] == "Spring Cloud Drive"
        assert result.total_latency_ms > 0.0

    async def test_pipeline_generate_only_no_execution(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(
            question="Which campaigns had the most conversions?",
            execute=False,
        )
        assert result.generation.sql == VALID_SQL
        assert result.execution is None

    async def test_pipeline_raises_retrieval_error(self):
        retriever = MagicMock()
        retriever.retrieve.side_effect = RuntimeError("Embedding model offline")
        retriever.settings = get_settings()
        pipeline = _make_pipeline(retriever=retriever)

        with pytest.raises(PipelineRetrievalError) as exc_info:
            await pipeline.run(question="Sales by region?")
        assert "retrieval failed" in str(exc_info.value).lower()

    async def test_pipeline_raises_generation_error_on_llm_unavailable(self):
        llm_service = MagicMock()
        llm_service.generate.side_effect = LLMUnavailableError("No API key")
        pipeline = _make_pipeline(llm_service=llm_service)

        with pytest.raises(PipelineGenerationError) as exc_info:
            await pipeline.run(question="Sales by region?")
        assert "unavailable" in str(exc_info.value).lower()

    async def test_pipeline_raises_validation_error(self):
        validator = MagicMock()
        validator.validate.return_value = {
            "is_valid": False,
            "errors": ["Column ghost_col could not be resolved."],
        }
        pipeline = _make_pipeline(validator=validator)

        with pytest.raises(PipelineValidationError) as exc_info:
            await pipeline.run(question="Sales by region?")
        assert "validation failed" in str(exc_info.value).lower()

    async def test_pipeline_raises_execution_error_on_timeout(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(
            side_effect=SQLTimeoutError("Exceeded 5s timeout")
        )
        pipeline = _make_pipeline(executor=executor)

        with pytest.raises(PipelineExecutionError) as exc_info:
            await pipeline.run(question="Sales by region?", execute=True)
        assert "execution failed" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# POST /query API Integration Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestQueryEndpoint:

    def test_query_success(self, client: TestClient):
        """Full pipeline success with mocked LLM and executor."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.question = "Which campaigns had the most conversions?"
        mock_result.retrieval = RetrievalStage(
            tables=["marketing.campaign_performance"],
            confidence_score=0.88,
        )
        mock_result.generation = GenerationStage(sql=VALID_SQL, confidence=0.94)
        mock_result.execution = ExecutionStage(
            rows=[{"campaign_name": "Spring Cloud Drive", "conversions": 320}],
            columns=["campaign_name", "conversions"],
            row_count=1,
            execution_time_ms=2.1,
        )
        mock_pipeline.run = AsyncMock(return_value=mock_result)

        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        payload = {
            "question": "Which campaigns had the most conversions?",
            "execute": True,
            "timeout_seconds": 5.0,
        }
        response = client.post("/query", json=payload)
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "Which campaigns had the most conversions?"
        assert data["retrieval"]["tables"] == ["marketing.campaign_performance"]
        assert data["retrieval"]["confidence_score"] == 0.88
        assert data["generation"]["sql"] == VALID_SQL
        assert data["generation"]["confidence"] == 0.94
        assert data["execution"]["row_count"] == 1
        assert data["execution"]["rows"][0]["campaign_name"] == "Spring Cloud Drive"

    def test_query_generate_only(self, client: TestClient):
        """Pipeline with execute=False should return null execution stage."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.question = "Sales by region?"
        mock_result.retrieval = RetrievalStage(
            tables=["analytics.sales_orders"], confidence_score=0.82
        )
        mock_result.generation = GenerationStage(
            sql="SELECT region, SUM(enterprise_sales_amount) FROM analytics.sales_orders GROUP BY region;",
            confidence=0.91,
        )
        mock_result.execution = None
        mock_pipeline.run = AsyncMock(return_value=mock_result)

        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        payload = {"question": "Sales by region?", "execute": False}
        response = client.post("/query", json=payload)
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["execution"] is None
        assert data["generation"]["sql"] is not None

    def test_query_validation_failure_returns_422(self, client: TestClient):
        """PipelineValidationError maps to HTTP 422."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            side_effect=PipelineValidationError(
                "Column ghost_col could not be resolved."
            )
        )
        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        response = client.post("/query", json={"question": "Show me ghost_col values."})
        app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_query_generation_failure_returns_503(self, client: TestClient):
        """PipelineGenerationError maps to HTTP 503."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            side_effect=PipelineGenerationError("LLM unavailable: No API key.")
        )
        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        response = client.post("/query", json={"question": "Total sales last quarter?"})
        app.dependency_overrides.clear()

        assert response.status_code == 503

    def test_query_execution_failure_returns_400(self, client: TestClient):
        """PipelineExecutionError maps to HTTP 400."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_pipeline.run = AsyncMock(
            side_effect=PipelineExecutionError("Database error occurred.")
        )
        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        response = client.post("/query", json={"question": "Total sales last quarter?"})
        app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_query_short_question_returns_422(self, client: TestClient):
        """Pydantic min_length=3 on question field returns HTTP 422."""
        response = client.post("/query", json={"question": "Hi"})
        assert response.status_code == 422

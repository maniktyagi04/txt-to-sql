"""Tests for the End-to-End Query Pipeline and Route.

Coverage:
- QueryPipeline execution flow orchestration.
- Integration mapping inside POST /query.
- Proper error propagation and code mapping.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.pipeline import (
    QueryPipeline,
    PipelineRetrievalError,
    PipelineGenerationError,
    PipelineValidationError,
    PipelineExecutionError,
)
from app.services.llm_service import GenerationResult, LLMUnavailableError
from app.models.retrieval import TableRetrievalResult
from app.services.executor import SQLTimeoutError
from app.utils.config import get_settings


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_SQL = (
    "SELECT student_name "
    "FROM beaver.students "
    "ORDER BY student_name LIMIT 5;"
)

MOCK_RETRIEVED_TABLES = [
    TableRetrievalResult(
        table_name="beaver.students",
        score=0.88,
        reason="Direct match for students.",
        explanation="Direct match for students.",
        confidence=0.88,
    )
]

MOCK_LLM_RESULT = GenerationResult(
    sql=VALID_SQL,
    confidence=0.94,
    explanation="Mocked SQL explanation.",
    raw_response='{"sql": "...", "confidence": 0.94}',
    latency_ms=100.0,
    attempt=1,
)

MOCK_EXEC_RESULT = {
    "rows": [{"student_name": "Alice Smith"}],
    "columns": ["student_name"],
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
            question="Which students are in department CS?",
            execute=True,
        )
        assert result.question == "Which students are in department CS?"
        assert result.retrieved_tables[0].table_name == "beaver.students"
        assert result.generated_sql == VALID_SQL
        assert result.sql_explanation == "Mocked SQL explanation."
        assert result.execution_result is not None
        assert result.execution_result["row_count"] == 1
        assert result.execution_result["rows"][0]["student_name"] == "Alice Smith"
        assert result.latency_ms > 0.0

    async def test_pipeline_generate_only_no_execution(self):
        pipeline = _make_pipeline()
        result = await pipeline.run(
            question="Which students are in department CS?",
            execute=False,
        )
        assert result.generated_sql == VALID_SQL
        assert result.execution_result is None

    async def test_pipeline_raises_retrieval_error(self):
        retriever = MagicMock()
        retriever.retrieve.side_effect = RuntimeError("Embedding model offline")
        retriever.settings = get_settings()
        pipeline = _make_pipeline(retriever=retriever)

        with pytest.raises(PipelineRetrievalError) as exc_info:
            await pipeline.run(question="Students list?")
        assert "retrieval failed" in str(exc_info.value).lower()

    async def test_pipeline_raises_generation_error_on_llm_unavailable(self):
        llm_service = MagicMock()
        llm_service.generate.side_effect = LLMUnavailableError("No API key")
        pipeline = _make_pipeline(llm_service=llm_service)

        with pytest.raises(PipelineGenerationError) as exc_info:
            await pipeline.run(question="Students list?")
        assert "unavailable" in str(exc_info.value).lower()

    async def test_pipeline_raises_validation_error(self):
        validator = MagicMock()
        validator.validate.return_value = {
            "is_valid": False,
            "errors": ["Column ghost_col could not be resolved."],
        }
        pipeline = _make_pipeline(validator=validator)

        with pytest.raises(PipelineValidationError) as exc_info:
            await pipeline.run(question="Students list?")
        assert "validation failed" in str(exc_info.value).lower()

    async def test_pipeline_raises_execution_error_on_timeout(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(
            side_effect=SQLTimeoutError("Exceeded 5s timeout")
        )
        pipeline = _make_pipeline(executor=executor)

        with pytest.raises(PipelineExecutionError) as exc_info:
            await pipeline.run(question="Students list?", execute=True)
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
        mock_result.question = "Which students are in CS?"
        mock_result.retrieved_tables = MOCK_RETRIEVED_TABLES
        mock_result.generated_sql = VALID_SQL
        mock_result.sql_explanation = "Mocked SQL explanation."
        mock_result.validation_result = {"is_valid": True, "errors": []}
        mock_result.execution_result = {
            "rows": [{"student_name": "Alice Smith"}],
            "columns": ["student_name"],
            "row_count": 1,
            "execution_time_ms": 2.1,
        }
        mock_result.latency_ms = 125.0
        mock_pipeline.run = AsyncMock(return_value=mock_result)

        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        payload = {
            "question": "Which students are in CS?",
            "execute": True,
            "timeout_seconds": 5.0,
        }
        response = client.post("/query", json=payload)
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["question"] == "Which students are in CS?"
        assert data["retrieved_tables"][0]["table_name"] == "beaver.students"
        assert data["generated_sql"] == VALID_SQL
        assert data["sql_explanation"] == "Mocked SQL explanation."
        assert data["validation_result"]["is_valid"] is True
        assert data["execution_result"]["row_count"] == 1
        assert data["execution_result"]["rows"][0]["student_name"] == "Alice Smith"

    def test_query_generate_only(self, client: TestClient):
        """Pipeline with execute=False should return null execution result."""
        from app.routes.query import get_query_pipeline

        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.question = "Students list?"
        mock_result.retrieved_tables = MOCK_RETRIEVED_TABLES
        mock_result.generated_sql = VALID_SQL
        mock_result.sql_explanation = "Mocked SQL explanation."
        mock_result.validation_result = {"is_valid": True, "errors": []}
        mock_result.execution_result = None
        mock_result.latency_ms = 80.0
        mock_pipeline.run = AsyncMock(return_value=mock_result)

        app: Any = client.app
        app.dependency_overrides[get_query_pipeline] = lambda: mock_pipeline

        payload = {"question": "Students list?", "execute": False}
        response = client.post("/query", json=payload)
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["execution_result"] is None
        assert data["generated_sql"] == VALID_SQL

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

        response = client.post("/query", json={"question": "Total students?"})
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

        response = client.post("/query", json={"question": "Total students?"})
        app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_query_short_question_returns_422(self, client: TestClient):
        """Pydantic min_length=3 on question field returns HTTP 422."""
        response = client.post("/query", json={"question": "Hi"})
        assert response.status_code == 422

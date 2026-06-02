"""Tests for the SQL Generation Layer and Route.

Coverage:
- SQLPromptBuilder: few-shot embedding, schema loading/formatting.
- Response parsing: JSON cleaning, markdown fence stripping, confidence clamping.
- GeminiLLMService: generation requests, caching, retry/backoff, mock client hooks.
- Endpoint integration: POST /generate-sql with payload mapping.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.prompt_builder import SQLPromptBuilder
from app.services.llm_service import (
    GeminiLLMService,
    GenerationResult,
    LLMMaxRetriesExceededError,
    LLMResponseParseError,
    LLMUnavailableError,
    _parse_response,
)
from app.models.retrieval import TableRetrievalResult
from app.utils.config import Settings, get_settings


@pytest.fixture
def test_settings() -> Settings:
    base = get_settings()
    return Settings(
        environment="test",
        log_level="DEBUG",
        log_format="plain",
        embedding_model_name=base.embedding_model_name,
        schema_metadata_path=base.schema_metadata_path,
        schema_embedding_store_path=base.schema_embedding_store_path,
        default_retrieval_top_k=5,
        max_retrieval_top_k=25,
        gemini_api_key="test-api-key",
        gemini_model_name="gemini-2.5-flash",
    )


@pytest.fixture
def prompt_builder(test_settings: Settings) -> SQLPromptBuilder:
    return SQLPromptBuilder(test_settings)


@pytest.fixture
def llm_service(test_settings: Settings) -> GeminiLLMService:
    return GeminiLLMService(test_settings)


@pytest.fixture
def sales_tables() -> list[TableRetrievalResult]:
    # We keep the fixture name sales_tables to avoid breaking test signatures,
    # but return Beaver academic tables
    return [
        TableRetrievalResult(
            table_name="beaver.students",
            score=0.91,
            reason="Matched student and department references.",
            explanation="Matched student and department references.",
            confidence=0.91,
        ),
        TableRetrievalResult(
            table_name="beaver.departments",
            score=0.78,
            reason="Matched department details.",
            explanation="Matched department details.",
            confidence=0.78,
        ),
    ]


# ---------------------------------------------------------------------------
# SQLPromptBuilder tests
# ---------------------------------------------------------------------------


class TestSQLPromptBuilder:

    def test_loads_schema_index_from_json(self, prompt_builder: SQLPromptBuilder):
        index = prompt_builder._load_schema_index()
        assert isinstance(index, dict)
        assert len(index) > 0
        assert "beaver.students" in index

        students = index["beaver.students"]
        assert "student_id" in students.columns
        assert "student_name" in students.columns

    def test_enriches_retrieved_tables_with_full_metadata(
        self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]
    ):
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(sales_tables, index)
        assert len(enriched) == 2
        assert enriched[0].table_name == "beaver.students"
        assert enriched[1].table_name == "beaver.departments"

        students = enriched[0]
        assert "student_id" in students.columns
        assert "student_name" in students.columns

    def test_fallback_stub_for_unknown_table(self, prompt_builder: SQLPromptBuilder):
        unknown = [
            TableRetrievalResult(
                table_name="unknown.ghost_table",
                score=0.5,
                reason="N/A",
                explanation="N/A",
                confidence=0.5,
            )
        ]
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(unknown, index)
        assert len(enriched) == 1
        assert enriched[0].table_name == "unknown.ghost_table"
        assert enriched[0].columns == []

    def test_format_schema_block_contains_table_info(
        self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]
    ):
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(sales_tables, index)
        block = prompt_builder._format_schema_block(enriched)
        assert "beaver.students" in block
        assert "student_name" in block
        assert "beaver.departments" in block
        assert "department_name" in block

    def test_format_examples_block_has_three_examples(
        self, prompt_builder: SQLPromptBuilder
    ):
        block = prompt_builder._format_examples_block()
        assert "Example 1:" in block
        assert "Example 2:" in block
        assert "Example 3:" in block
        assert '"confidence"' in block

    def test_build_prompt_contains_question(
        self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]
    ):
        question = "List students in the Computer Science department"
        prompt = prompt_builder.build_prompt(
            question=question, retrieved_tables=sales_tables
        )
        assert question in prompt
        assert "beaver.students" in prompt
        assert "Few-Shot Examples" in prompt
        assert "Retrieved Schema Context" in prompt
        assert '{"sql"' in prompt or '"sql":' in prompt


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------


class TestParseResponse:

    def test_parses_clean_json(self):
        raw = '{"sql": "SELECT 1", "confidence": 0.87, "explanation": "Simple select"}'
        sql, conf, explanation = _parse_response(raw)
        assert sql == "SELECT 1"
        assert conf == pytest.approx(0.87)
        assert explanation == "Simple select"

    def test_strips_markdown_fences(self):
        raw = (
            '```json\n{"sql": "SELECT 2", "confidence": 0.5, "explanation": "M"} \n```'
        )
        sql, conf, explanation = _parse_response(raw)
        assert sql == "SELECT 2"
        assert conf == pytest.approx(0.5)
        assert explanation == "M"

    def test_clamps_confidence_above_one(self):
        raw = '{"sql": "SELECT 3", "confidence": 1.5, "explanation": "M"}'
        _, conf, _ = _parse_response(raw)
        assert conf == pytest.approx(1.0)

    def test_clamps_confidence_below_zero(self):
        raw = '{"sql": "SELECT 4", "confidence": -0.3, "explanation": "M"}'
        _, conf, _ = _parse_response(raw)
        assert conf == pytest.approx(0.0)

    def test_coerces_string_confidence(self):
        raw = '{"sql": "SELECT 5", "confidence": "0.75", "explanation": "M"}'
        _, conf, _ = _parse_response(raw)
        assert conf == pytest.approx(0.75)

    def test_raises_on_invalid_json(self):
        with pytest.raises(LLMResponseParseError, match="not valid JSON"):
            _parse_response("this is not json")

    def test_raises_on_missing_sql_field(self):
        raw = '{"confidence": 0.8, "explanation": "M"}'
        with pytest.raises(LLMResponseParseError, match="'sql' field is missing"):
            _parse_response(raw)

    def test_raises_on_empty_sql(self):
        raw = '{"sql": "   ", "confidence": 0.8, "explanation": "M"}'
        with pytest.raises(LLMResponseParseError, match="'sql' field is missing"):
            _parse_response(raw)

    def test_raises_on_non_numeric_confidence(self):
        raw = '{"sql": "SELECT 6", "confidence": "bad", "explanation": "M"}'
        with pytest.raises(
            LLMResponseParseError, match="'confidence' field is not numeric"
        ):
            _parse_response(raw)


# ---------------------------------------------------------------------------
# GeminiLLMService tests (all Gemini API calls are mocked)
# ---------------------------------------------------------------------------


class TestGeminiLLMService:

    def _make_mock_client(self, text: str) -> MagicMock:
        """Build a minimal mock mimicking the GenerativeModel response structure."""
        part = MagicMock()
        part.text = text
        candidate = MagicMock()
        candidate.content.parts = [part]
        response = MagicMock()
        response.candidates = [candidate]
        client = MagicMock()
        client.generate_content.return_value = response
        return client

    def test_generate_returns_result_on_first_attempt(
        self, llm_service: GeminiLLMService
    ):
        good_json = '{"sql": "SELECT student_name FROM beaver.students", "confidence": 0.91, "explanation": "Exp"}'
        mock_client = self._make_mock_client(good_json)
        llm_service._client = mock_client

        result = llm_service.generate("some prompt")

        assert result.sql == "SELECT student_name FROM beaver.students"
        assert result.confidence == pytest.approx(0.91)
        assert result.explanation == "Exp"
        assert result.attempt == 1
        assert result.latency_ms > 0

    def test_generate_retries_on_parse_error_then_succeeds(
        self, llm_service: GeminiLLMService
    ):
        good_json = '{"sql": "SELECT 1", "confidence": 0.85, "explanation": "Exp"}'
        bad_part = MagicMock()
        bad_part.text = "not json at all"
        good_part = MagicMock()
        good_part.text = good_json

        bad_candidate = MagicMock()
        bad_candidate.content.parts = [bad_part]
        good_candidate = MagicMock()
        good_candidate.content.parts = [good_part]

        bad_response = MagicMock()
        bad_response.candidates = [bad_candidate]
        good_response = MagicMock()
        good_response.candidates = [good_candidate]

        mock_client = MagicMock()
        mock_client.generate_content.side_effect = [bad_response, good_response]

        with patch("time.sleep"):  # suppress backoff delays
            llm_service._client = mock_client
            result = llm_service.generate("some prompt")

        assert result.sql == "SELECT 1"
        assert result.attempt == 2

    def test_generate_raises_max_retries_when_always_failing(
        self, llm_service: GeminiLLMService
    ):
        bad_part = MagicMock()
        bad_part.text = "not json"
        bad_candidate = MagicMock()
        bad_candidate.content.parts = [bad_part]
        bad_response = MagicMock()
        bad_response.candidates = [bad_candidate]

        mock_client = MagicMock()
        mock_client.generate_content.return_value = bad_response
        llm_service._client = mock_client

        with patch("time.sleep"):
            with pytest.raises(LLMMaxRetriesExceededError):
                llm_service.generate("some prompt")

    def test_generate_raises_unavailable_when_no_api_key(self, test_settings: Settings):
        no_key_settings = test_settings.model_copy(update={"gemini_api_key": None})
        service = GeminiLLMService(no_key_settings)

        with patch("builtins.__import__", wraps=__import__):
            with pytest.raises(LLMUnavailableError, match="GEMINI_API_KEY"):
                service._load_client()


# ---------------------------------------------------------------------------
# POST /generate-sql endpoint integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def _make_valid_payload(top_k: int = 2) -> dict:
    return {
        "question": "What is the enrollment year of students in Computer Science?",
        "retrieved_tables": [
            {
                "table_name": "beaver.students",
                "score": 0.91,
                "reason": "Matched students.",
                "explanation": "Matched students.",
                "confidence": 0.91,
            },
            {
                "table_name": "beaver.departments",
                "score": 0.78,
                "reason": "Matched departments.",
                "explanation": "Matched departments.",
                "confidence": 0.78,
            },
        ][:top_k],
    }


class TestGenerateSQLEndpoint:

    def test_success_returns_sql_and_confidence(self, client: TestClient):
        good_json = (
            '{"sql": "SELECT student_name FROM beaver.students", "confidence": 0.89}'
        )
        mock_result = GenerationResult(
            sql="SELECT student_name FROM beaver.students",
            confidence=0.89,
            explanation="Mocked SQL explanation.",
            raw_response=good_json,
            latency_ms=412.5,
            attempt=1,
        )

        from app.routes.generation import get_llm_service, get_prompt_builder

        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = "built prompt"

        app: Any = client.app
        app.dependency_overrides[get_llm_service] = lambda: mock_llm
        app.dependency_overrides[get_prompt_builder] = lambda: mock_builder

        response = client.post("/generate-sql", json=_make_valid_payload())
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "sql" in data
        assert "confidence" in data
        assert data["confidence"] == pytest.approx(0.89)

    def test_validation_error_on_missing_question(self, client: TestClient):
        response = client.post("/generate-sql", json={"retrieved_tables": []})
        assert response.status_code == 422

    def test_validation_error_on_short_question(self, client: TestClient):
        payload = _make_valid_payload()
        payload["question"] = "Hi"
        response = client.post("/generate-sql", json=payload)
        assert response.status_code == 422

    def test_returns_503_when_llm_unavailable(self, client: TestClient):
        from app.routes.generation import get_llm_service

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = LLMUnavailableError("No API key")
        app: Any = client.app
        app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        app.dependency_overrides.clear()

        assert response.status_code == 503

    def test_returns_503_when_max_retries_exceeded(self, client: TestClient):
        from app.routes.generation import get_llm_service

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = LLMMaxRetriesExceededError(
            "All attempts failed"
        )
        app: Any = client.app
        app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        app.dependency_overrides.clear()

        assert response.status_code == 503

    def test_returns_500_when_parse_error(self, client: TestClient):
        from app.routes.generation import get_llm_service

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = LLMResponseParseError("Bad JSON")
        app: Any = client.app
        app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        app.dependency_overrides.clear()

        assert response.status_code == 500

"""Tests for the SQL Generation Layer.

Coverage:
- SQLPromptBuilder: schema loading, enrichment, prompt formatting, fallback stubs.
- _parse_response: valid JSON, markdown fences, missing fields, bad confidence types.
- GeminiLLMService: successful call, parse retry, max-retries exhaustion, no API key.
- POST /generate-sql: success, validation errors, 503 LLM unavailable, 503 max retries,
  500 parse error.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.retrieval import TableRetrievalResult
from app.services.llm_service import (
    GenerationResult,
    GeminiLLMService,
    LLMMaxRetriesExceededError,
    LLMResponseParseError,
    LLMUnavailableError,
    _parse_response,
)
from app.services.prompt_builder import SQLPromptBuilder
from app.utils.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

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
        gemini_api_key="test-api-key-stub",
        gemini_model_name="gemini-2.5-flash",
        gemini_max_retries=2,
        gemini_timeout_seconds=10.0,
    )


@pytest.fixture
def prompt_builder(test_settings: Settings) -> SQLPromptBuilder:
    return SQLPromptBuilder(test_settings)


@pytest.fixture
def llm_service(test_settings: Settings) -> GeminiLLMService:
    return GeminiLLMService(test_settings)


@pytest.fixture
def sales_tables() -> list[TableRetrievalResult]:
    return [
        TableRetrievalResult(
            table_name="analytics.sales_orders",
            score=0.91,
            reason="Matched sales, region, revenue."
        ),
        TableRetrievalResult(
            table_name="analytics.calendar",
            score=0.78,
            reason="Matched quarter, fiscal terms."
        ),
    ]


# ---------------------------------------------------------------------------
# SQLPromptBuilder tests
# ---------------------------------------------------------------------------

class TestSQLPromptBuilder:

    def test_loads_schema_index_from_json(self, prompt_builder: SQLPromptBuilder):
        index = prompt_builder._load_schema_index()
        assert "analytics.sales_orders" in index
        assert "analytics.customers" in index
        assert "support.tickets" in index
        assert "marketing.campaign_performance" in index

    def test_enriches_retrieved_tables_with_full_metadata(
        self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]
    ):
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(sales_tables, index)
        assert len(enriched) == 2
        # sales_orders should have its columns fully populated
        sales = enriched[0]
        assert sales.table_name == "analytics.sales_orders"
        assert "order_id" in sales.columns
        assert "enterprise_sales_amount" in sales.columns

    def test_fallback_stub_for_unknown_table(self, prompt_builder: SQLPromptBuilder):
        unknown = [TableRetrievalResult(table_name="unknown.ghost_table", score=0.5, reason="N/A")]
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(unknown, index)
        assert len(enriched) == 1
        assert enriched[0].table_name == "unknown.ghost_table"
        assert enriched[0].columns == []

    def test_format_schema_block_contains_table_info(self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]):
        index = prompt_builder._load_schema_index()
        enriched = prompt_builder._enrich_tables(sales_tables, index)
        block = prompt_builder._format_schema_block(enriched)
        assert "analytics.sales_orders" in block
        assert "enterprise_sales_amount" in block
        assert "analytics.calendar" in block
        assert "fiscal_quarter" in block

    def test_format_examples_block_has_three_examples(self, prompt_builder: SQLPromptBuilder):
        block = prompt_builder._format_examples_block()
        assert "Example 1:" in block
        assert "Example 2:" in block
        assert "Example 3:" in block
        assert '"confidence"' in block

    def test_build_prompt_contains_question(
        self, prompt_builder: SQLPromptBuilder, sales_tables: list[TableRetrievalResult]
    ):
        question = "What is the total revenue by region last quarter?"
        prompt = prompt_builder.build_prompt(question=question, retrieved_tables=sales_tables)
        assert question in prompt
        assert "analytics.sales_orders" in prompt
        assert "Few-Shot Examples" in prompt
        assert "Retrieved Schema Context" in prompt
        assert '{"sql"' in prompt or '"sql":' in prompt


# ---------------------------------------------------------------------------
# _parse_response tests
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_parses_clean_json(self):
        raw = '{"sql": "SELECT 1", "confidence": 0.87}'
        sql, conf = _parse_response(raw)
        assert sql == "SELECT 1"
        assert conf == pytest.approx(0.87)

    def test_strips_markdown_fences(self):
        raw = '```json\n{"sql": "SELECT 2", "confidence": 0.5}\n```'
        sql, conf = _parse_response(raw)
        assert sql == "SELECT 2"
        assert conf == pytest.approx(0.5)

    def test_clamps_confidence_above_one(self):
        raw = '{"sql": "SELECT 3", "confidence": 1.5}'
        _, conf = _parse_response(raw)
        assert conf == pytest.approx(1.0)

    def test_clamps_confidence_below_zero(self):
        raw = '{"sql": "SELECT 4", "confidence": -0.3}'
        _, conf = _parse_response(raw)
        assert conf == pytest.approx(0.0)

    def test_coerces_string_confidence(self):
        raw = '{"sql": "SELECT 5", "confidence": "0.75"}'
        _, conf = _parse_response(raw)
        assert conf == pytest.approx(0.75)

    def test_raises_on_invalid_json(self):
        with pytest.raises(LLMResponseParseError, match="not valid JSON"):
            _parse_response("this is not json")

    def test_raises_on_missing_sql_field(self):
        raw = '{"confidence": 0.8}'
        with pytest.raises(LLMResponseParseError, match="'sql' field is missing"):
            _parse_response(raw)

    def test_raises_on_empty_sql(self):
        raw = '{"sql": "   ", "confidence": 0.8}'
        with pytest.raises(LLMResponseParseError, match="'sql' field is missing"):
            _parse_response(raw)

    def test_raises_on_non_numeric_confidence(self):
        raw = '{"sql": "SELECT 6", "confidence": "bad"}'
        with pytest.raises(LLMResponseParseError, match="'confidence' field is not numeric"):
            _parse_response(raw)


# ---------------------------------------------------------------------------
# GeminiLLMService tests  (all Gemini API calls are mocked)
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

    def test_generate_returns_result_on_first_attempt(self, llm_service: GeminiLLMService):
        good_json = '{"sql": "SELECT region FROM analytics.sales_orders", "confidence": 0.91}'
        mock_client = self._make_mock_client(good_json)
        llm_service._client = mock_client

        result = llm_service.generate("some prompt")

        assert result.sql == "SELECT region FROM analytics.sales_orders"
        assert result.confidence == pytest.approx(0.91)
        assert result.attempt == 1
        assert result.latency_ms > 0

    def test_generate_retries_on_parse_error_then_succeeds(self, llm_service: GeminiLLMService):
        good_json = '{"sql": "SELECT 1", "confidence": 0.85}'
        bad_part = MagicMock(); bad_part.text = "not json at all"
        good_part = MagicMock(); good_part.text = good_json

        bad_candidate = MagicMock(); bad_candidate.content.parts = [bad_part]
        good_candidate = MagicMock(); good_candidate.content.parts = [good_part]

        bad_response = MagicMock(); bad_response.candidates = [bad_candidate]
        good_response = MagicMock(); good_response.candidates = [good_candidate]

        mock_client = MagicMock()
        mock_client.generate_content.side_effect = [bad_response, good_response]

        with patch("time.sleep"):  # suppress backoff delays
            llm_service._client = mock_client
            result = llm_service.generate("some prompt")

        assert result.sql == "SELECT 1"
        assert result.attempt == 2

    def test_generate_raises_max_retries_when_always_failing(self, llm_service: GeminiLLMService):
        bad_part = MagicMock(); bad_part.text = "not json"
        bad_candidate = MagicMock(); bad_candidate.content.parts = [bad_part]
        bad_response = MagicMock(); bad_response.candidates = [bad_candidate]

        mock_client = MagicMock()
        mock_client.generate_content.return_value = bad_response
        llm_service._client = mock_client

        with patch("time.sleep"):
            with pytest.raises(LLMMaxRetriesExceededError):
                llm_service.generate("some prompt")

    def test_generate_raises_unavailable_when_no_api_key(self, test_settings: Settings):
        no_key_settings = test_settings.model_copy(update={"gemini_api_key": None})
        service = GeminiLLMService(no_key_settings)

        # google.generativeai is imported inside _load_client, so we patch it at the module level
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
        "question": "What is the total sales amount by region this quarter?",
        "retrieved_tables": [
            {"table_name": "analytics.sales_orders", "score": 0.91, "reason": "Matched sales."},
            {"table_name": "analytics.calendar", "score": 0.78, "reason": "Matched quarter."},
        ][:top_k],
    }


class TestGenerateSQLEndpoint:

    def test_success_returns_sql_and_confidence(self, client: TestClient):
        good_json = '{"sql": "SELECT region, SUM(enterprise_sales_amount) FROM analytics.sales_orders GROUP BY region", "confidence": 0.89}'
        mock_result = GenerationResult(
            sql="SELECT region, SUM(enterprise_sales_amount) FROM analytics.sales_orders GROUP BY region",
            confidence=0.89,
            raw_response=good_json,
            latency_ms=412.5,
            attempt=1,
        )

        from app.routes.generation import get_llm_service, get_prompt_builder
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = "built prompt"

        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm
        client.app.dependency_overrides[get_prompt_builder] = lambda: mock_builder

        response = client.post("/generate-sql", json=_make_valid_payload())
        client.app.dependency_overrides.clear()

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
        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        client.app.dependency_overrides.clear()

        assert response.status_code == 503

    def test_returns_503_when_max_retries_exceeded(self, client: TestClient):
        from app.routes.generation import get_llm_service
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = LLMMaxRetriesExceededError("All attempts failed")
        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        client.app.dependency_overrides.clear()

        assert response.status_code == 503

    def test_returns_500_when_parse_error(self, client: TestClient):
        from app.routes.generation import get_llm_service
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = LLMResponseParseError("Bad JSON")
        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm

        response = client.post("/generate-sql", json=_make_valid_payload())
        client.app.dependency_overrides.clear()

        assert response.status_code == 500

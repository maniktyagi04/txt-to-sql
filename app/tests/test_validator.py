"""Tests for the SQL Validation Layer.

Coverage:
- Syntax Validation: valid vs invalid SQL syntax.
- Table Validation: valid vs invalid physical tables, CTE validation.
- Column Validation: valid vs invalid column references on tables.
- Invalid/Ambiguous References: unqualified duplicate columns, incorrect aliases.
- Endpoint Integration: POST /generate-sql returns HTTP 422 if SQL is invalid.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.validator import SQLValidator
from app.utils.config import Settings, get_settings
from app.services.llm_service import GenerationResult


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
def validator(test_settings: Settings) -> SQLValidator:
    return SQLValidator(test_settings)


# ---------------------------------------------------------------------------
# SQLValidator Unit Tests
# ---------------------------------------------------------------------------

class TestSQLValidator:

    def test_valid_syntax_and_references(self, validator: SQLValidator):
        # Correctly qualified columns, joined tables, standard filters
        sql = (
            "SELECT so.order_id, c.account_name "
            "FROM analytics.sales_orders AS so "
            "JOIN analytics.customers AS c ON so.customer_id = c.customer_id "
            "WHERE so.region = 'West';"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is True
        assert len(res["errors"]) == 0

    def test_invalid_syntax(self, validator: SQLValidator):
        # Mismatched parenthesis / select clause
        sql = "SELECT order_id, FROM analytics.sales_orders WHERE (order_id = 1"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any("Syntax" in err or "Parsing" in err for err in res["errors"])

    def test_invalid_table_reference(self, validator: SQLValidator):
        # Table analytics.ghost_table does not exist in schema_metadata.json
        sql = "SELECT order_id FROM analytics.ghost_table;"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any("Table 'analytics.ghost_table' is not defined" in err for err in res["errors"])

    def test_cte_reference_succeeds(self, validator: SQLValidator):
        # CTEs shouldn't trigger "table not defined in schema" errors
        sql = (
            "WITH local_orders AS ("
            "  SELECT order_id, customer_id FROM analytics.sales_orders"
            ")"
            "SELECT o.order_id FROM local_orders o;"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is True
        assert len(res["errors"]) == 0

    def test_invalid_column_reference(self, validator: SQLValidator):
        # 'clicks' column belongs to campaign_performance, not sales_orders
        sql = "SELECT clicks FROM analytics.sales_orders;"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any("Semantic Error" in err or "Resolution" in err for err in res["errors"])

    def test_unqualified_ambiguous_column_fails(self, validator: SQLValidator):
        # customer_id is in both sales_orders and customers, so unqualified customer_id in SELECT is ambiguous
        sql = (
            "SELECT customer_id "
            "FROM analytics.sales_orders "
            "JOIN analytics.customers ON sales_orders.customer_id = customers.customer_id;"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any("ambiguous" in err.lower() or "Semantic Error" in err for err in res["errors"])

    def test_case_insensitivity(self, validator: SQLValidator):
        # Mixed casing in tables/columns should resolve fine
        sql = "SELECT ORDER_ID, customer_id FROM ANALYTICS.sales_orders WHERE REGION = 'West';"
        res = validator.validate(sql)
        assert res["is_valid"] is True
        assert len(res["errors"]) == 0


# ---------------------------------------------------------------------------
# API Route Integration Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


class TestGenerateSQLEndpointWithValidator:

    def test_successful_validation_returns_200(self, client: TestClient):
        # Valid generated SQL
        valid_sql = "SELECT order_id FROM analytics.sales_orders WHERE region = 'West';"
        mock_result = GenerationResult(
            sql=valid_sql,
            confidence=0.91,
            raw_response='{"sql": "...", "confidence": 0.91}',
            latency_ms=100.0,
            attempt=1,
        )

        from app.routes.generation import get_llm_service, get_prompt_builder
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = "built prompt"

        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm
        client.app.dependency_overrides[get_prompt_builder] = lambda: mock_builder

        payload = {
            "question": "Show me orders in the West region.",
            "retrieved_tables": [{"table_name": "analytics.sales_orders", "score": 0.9, "reason": "Match"}],
        }

        response = client.post("/generate-sql", json=payload)
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["sql"] == valid_sql
        assert data["confidence"] == 0.91

    def test_invalid_validation_returns_422(self, client: TestClient):
        # Invalid generated SQL (missing table / wrong column reference)
        invalid_sql = "SELECT invalid_col FROM analytics.sales_orders;"
        mock_result = GenerationResult(
            sql=invalid_sql,
            confidence=0.88,
            raw_response='{"sql": "...", "confidence": 0.88}',
            latency_ms=100.0,
            attempt=1,
        )

        from app.routes.generation import get_llm_service, get_prompt_builder
        mock_llm = MagicMock()
        mock_llm.generate.return_value = mock_result
        mock_builder = MagicMock()
        mock_builder.build_prompt.return_value = "built prompt"

        client.app.dependency_overrides[get_llm_service] = lambda: mock_llm
        client.app.dependency_overrides[get_prompt_builder] = lambda: mock_builder

        payload = {
            "question": "Show me invalid columns.",
            "retrieved_tables": [{"table_name": "analytics.sales_orders", "score": 0.9, "reason": "Match"}],
        }

        response = client.post("/generate-sql", json=payload)
        client.app.dependency_overrides.clear()

        # The endpoint must intercept the invalid SQL and abort with 422 Unprocessable Entity
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        assert any("Failed" in err["message"] or "validation" in err["message"].lower() for err in data["errors"])

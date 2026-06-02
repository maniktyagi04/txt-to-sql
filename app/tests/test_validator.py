"""Tests for the SQL Validation Layer.

Coverage:
- Syntax Validation: valid vs invalid SQL syntax.
- Table Validation: valid vs invalid physical tables, CTE validation.
- Column Validation: valid vs invalid column references on tables.
- Invalid/Ambiguous References: unqualified duplicate columns, incorrect aliases.
- Endpoint Integration: POST /generate-sql returns HTTP 422 if SQL is invalid.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
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
            "SELECT s.student_id, d.department_name "
            "FROM beaver.students AS s "
            "JOIN beaver.departments AS d ON s.department_id = d.department_id "
            "WHERE d.department_name = 'Computer Science';"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is True
        assert len(res["errors"]) == 0

    def test_invalid_syntax(self, validator: SQLValidator):
        # Mismatched parenthesis / select clause
        sql = "SELECT student_id, FROM beaver.students WHERE (student_id = 'S01'"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any("Syntax" in err or "Parsing" in err for err in res["errors"])

    def test_invalid_table_reference(self, validator: SQLValidator):
        # Table beaver.ghost_table does not exist in schema_metadata.json
        sql = "SELECT student_id FROM beaver.ghost_table;"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any(
            "Table 'beaver.ghost_table' is not defined" in err for err in res["errors"]
        )

    def test_cte_reference_succeeds(self, validator: SQLValidator):
        # CTEs shouldn't trigger "table not defined in schema" errors
        sql = (
            "WITH local_students AS ("
            "  SELECT student_id, department_id FROM beaver.students"
            ")"
            "SELECT s.student_id FROM local_students s;"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is True
        assert len(res["errors"]) == 0

    def test_invalid_column_reference(self, validator: SQLValidator):
        # 'grade' column belongs to enrollments, not students
        sql = "SELECT grade FROM beaver.students;"
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any(
            "Semantic Error" in err or "Resolution" in err for err in res["errors"]
        )

    def test_unqualified_ambiguous_column_fails(self, validator: SQLValidator):
        # department_id is in both students and departments, so unqualified department_id is ambiguous
        sql = (
            "SELECT department_id "
            "FROM beaver.students "
            "JOIN beaver.departments ON students.department_id = departments.department_id;"
        )
        res = validator.validate(sql)
        assert res["is_valid"] is False
        assert any(
            "ambiguous" in err.lower() or "Semantic Error" in err
            for err in res["errors"]
        )

    def test_case_insensitivity(self, validator: SQLValidator):
        # Mixed casing in tables/columns should resolve fine
        sql = "SELECT STUDENT_ID, department_id FROM BEAVER.students WHERE ENROLLMENT_YEAR = 2023;"
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
        valid_sql = (
            "SELECT student_id FROM beaver.students WHERE enrollment_year = 2023;"
        )
        mock_result = GenerationResult(
            sql=valid_sql,
            confidence=0.91,
            explanation="Mocked SQL explanation.",
            raw_response='{"sql": "...", "confidence": 0.91}',
            latency_ms=100.0,
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

        payload = {
            "question": "Show me students enrolled in 2023.",
            "retrieved_tables": [
                {
                    "table_name": "beaver.students",
                    "score": 0.9,
                    "reason": "Match",
                    "explanation": "Match",
                    "confidence": 0.9,
                }
            ],
        }

        response = client.post("/generate-sql", json=payload)
        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["sql"] == valid_sql
        assert data["confidence"] == 0.91

    def test_invalid_validation_returns_422(self, client: TestClient):
        # Invalid generated SQL (missing table / wrong column reference)
        invalid_sql = "SELECT invalid_col FROM beaver.students;"
        mock_result = GenerationResult(
            sql=invalid_sql,
            confidence=0.88,
            explanation="Mocked SQL explanation.",
            raw_response='{"sql": "...", "confidence": 0.88}',
            latency_ms=100.0,
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

        payload = {
            "question": "Show me invalid columns.",
            "retrieved_tables": [
                {
                    "table_name": "beaver.students",
                    "score": 0.9,
                    "reason": "Match",
                    "explanation": "Match",
                    "confidence": 0.9,
                }
            ],
        }

        response = client.post("/generate-sql", json=payload)
        app.dependency_overrides.clear()

        # The endpoint must intercept the invalid SQL and abort with 422 Unprocessable Content
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        assert any(
            "failed validation" in err["message"].lower() for err in data["errors"]
        )

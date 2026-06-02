"""Tests for the SQL Execution Layer and Endpoint.

Coverage:
- Successful SELECT executions on various tables (calendar, sales_orders, campaign_performance).
- Result formatting, timing telemetry, and column listings.
- Validation gates intercepting invalid syntax/columns before execution.
- Read-only compilation authorizer blocking DDL (CREATE/DROP) and DML (INSERT/UPDATE/DELETE).
- Progress-handler-based query timeout enforcement.
- REST integration tests for POST /execute endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.executor import (
    SQLExecutor,
    SQLValidationError,
    SQLSecurityError,
    SQLTimeoutError,
)
from app.utils.config import Settings, get_settings


@pytest.fixture
def test_settings() -> Settings:
    base = get_settings()
    return Settings(
        environment="test",
        log_level="DEBUG",
        log_format="plain",
        schema_metadata_path=base.schema_metadata_path,
        schema_embedding_store_path=base.schema_embedding_store_path,
    )


@pytest.fixture
def executor(test_settings: Settings) -> SQLExecutor:
    from app.database.init_db import init_databases

    # Initialize physical databases with mock data for isolated unit testing
    init_databases()
    return SQLExecutor(test_settings)


# ---------------------------------------------------------------------------
# SQLExecutor Unit Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestSQLExecutor:

    async def test_execute_successful_select(self, executor: SQLExecutor):
        # A valid cross-table SELECT query
        sql = (
            "SELECT so.order_id, c.account_name, so.enterprise_sales_amount "
            "FROM analytics.sales_orders AS so "
            "JOIN analytics.customers AS c ON so.customer_id = c.customer_id "
            "WHERE so.region = 'West' "
            "ORDER BY so.order_id LIMIT 2;"
        )
        res = await executor.execute_query(sql)

        assert "rows" in res
        assert "columns" in res
        assert "row_count" in res
        assert "execution_time_ms" in res

        assert res["columns"] == ["order_id", "account_name", "enterprise_sales_amount"]
        assert len(res["rows"]) > 0
        assert res["rows"][0]["order_id"] == 1
        assert res["rows"][0]["account_name"] == "Acme Enterprise"
        assert res["rows"][0]["enterprise_sales_amount"] == 15000.0

    async def test_execute_empty_result(self, executor: SQLExecutor):
        # Valid query returning 0 rows
        sql = "SELECT * FROM analytics.products WHERE is_active = 0 AND category = 'Nonexistent';"
        res = await executor.execute_query(sql)

        assert res["row_count"] == 0
        assert len(res["rows"]) == 0
        assert len(res["columns"]) > 0

    async def test_validation_gate_blocks_invalid_queries(self, executor: SQLExecutor):
        # Invalid column reference
        sql = "SELECT ghost_column FROM analytics.sales_orders;"
        with pytest.raises(SQLValidationError) as exc_info:
            await executor.execute_query(sql, validate=True)
        assert "failed validation" in str(exc_info.value)

    async def test_authorizer_blocks_insert(self, executor: SQLExecutor):
        # Bypass validator and try to run INSERT through executor
        sql = "INSERT INTO analytics.products (product_id, sku) VALUES ('P005', 'SKU-HACK');"
        # We disable pre-validation to test that compile-time authorizer catches it!
        with pytest.raises(SQLSecurityError) as exc_info:
            await executor.execute_query(sql, validate=False)
        assert (
            "denied" in str(exc_info.value).lower()
            or "unauthorized" in str(exc_info.value).lower()
        )

    async def test_authorizer_blocks_drop_table(self, executor: SQLExecutor):
        # Bypass validator and try to run DROP TABLE
        sql = "DROP TABLE analytics.sales_orders;"
        with pytest.raises(SQLSecurityError) as exc_info:
            await executor.execute_query(sql, validate=False)
        assert (
            "denied" in str(exc_info.value).lower()
            or "unauthorized" in str(exc_info.value).lower()
        )

    async def test_execution_timeout(self, executor: SQLExecutor):
        # Force a timeout by setting a negative timeout
        sql = "SELECT * FROM analytics.sales_orders;"
        with pytest.raises(SQLTimeoutError) as exc_info:
            await executor.execute_query(sql, timeout_seconds=-1.0, validate=False)
        assert "timeout" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# API Route Integration Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app()
    # Using 'with TestClient' ensures lifespan startup/shutdown hooks are triggered
    with TestClient(app) as c:
        yield c


class TestExecuteEndpoint:

    def test_api_execute_success(self, client: TestClient):
        payload = {
            "sql": "SELECT order_id, region, enterprise_sales_amount FROM analytics.sales_orders ORDER BY order_id LIMIT 1;",
            "timeout_seconds": 3.0,
        }
        response = client.post("/execute", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "rows" in data
        assert "columns" in data
        assert "row_count" in data
        assert data["row_count"] == 1
        assert data["columns"] == ["order_id", "region", "enterprise_sales_amount"]
        assert data["rows"][0]["order_id"] == 1
        assert data["rows"][0]["region"] == "West"
        assert data["rows"][0]["enterprise_sales_amount"] == 15000.0

    def test_api_execute_validation_failure(self, client: TestClient):
        payload = {
            "sql": "SELECT invalid_col FROM analytics.sales_orders;",
            "timeout_seconds": 3.0,
        }
        response = client.post("/execute", json=payload)
        # Should return HTTP 422 Unprocessable Content due to validator gate failure
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        assert any("Validation Failed" in err["message"] for err in data["errors"])

    def test_api_execute_security_violation(self, client: TestClient):
        # Query that bypasses syntax validator but is blocked at compilation by authorizer
        # SQLValidator parses postgres and doesn't block INSERT if it is syntactically valid in postgres.
        # But compile-time authorizer in executor will block it and return 403 Forbidden!
        payload = {
            "sql": "INSERT INTO analytics.sales_orders (order_id) VALUES (999);",
            "timeout_seconds": 3.0,
        }
        response = client.post("/execute", json=payload)
        assert response.status_code == 403
        data = response.json()
        assert "errors" in data
        assert any("Security Violation" in err["message"] for err in data["errors"])

    def test_api_execute_timeout(self, client: TestClient):
        from unittest.mock import patch

        # Mock executor timeout using a valid timeout payload
        with patch(
            "app.routes.execution.SQLExecutor.execute_query",
            side_effect=SQLTimeoutError(
                "Database query execution exceeded timeout limit."
            ),
        ):
            payload = {
                "sql": "SELECT * FROM analytics.sales_orders;",
                "timeout_seconds": 3.0,
            }
            response = client.post("/execute", json=payload)
            # Should return HTTP 504 Gateway Timeout
            assert response.status_code == 504
            data = response.json()
            assert "errors" in data
            assert any("Timeout" in err["message"] for err in data["errors"])

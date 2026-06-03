"""Tests for the SQL Benchmark Router and Service.

Coverage:
- Endpoint execution: POST /benchmark
- Parameter handling: dry_run and limit_per_domain
- Verification of returned metrics, failure categorization, and summary
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
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
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


class TestBenchmarkEndpoint:

    def test_api_benchmark_dry_run(self, client: TestClient):
        """Test that the /benchmark endpoint returns correctly structured output in dry_run mode."""
        payload = {"dry_run": True, "limit_per_domain": 2}
        response = client.post("/benchmark", json=payload)

        assert response.status_code == 200
        data = response.json()

        # Verify all required top-level fields are present
        assert "total_queries" in data
        assert "metrics" in data
        assert "subtask_breakdown" in data
        assert "error_analysis" in data
        assert "overall_duration_ms" in data
        assert "dataset_statistics" in data
        assert "failure_categorization" in data
        assert "benchmark_summary" in data

        # At least one query must have been evaluated
        assert data["total_queries"] > 0

        # Verify all required metric keys exist
        metrics = data["metrics"]
        assert "retrieval_recall_at_5" in metrics
        assert "retrieval_recall_at_10" in metrics
        assert "sql_exact_match_accuracy" in metrics
        assert "sql_execution_match_accuracy" in metrics
        assert "parsing_success_rate" in metrics
        assert "average_latency_ms" in metrics

        # All metrics must be valid floats in [0, 1] range (except latency)
        for key in (
            "retrieval_recall_at_5",
            "retrieval_recall_at_10",
            "sql_exact_match_accuracy",
            "sql_execution_match_accuracy",
            "parsing_success_rate",
        ):
            assert 0.0 <= metrics[key] <= 1.0, f"{key} out of range: {metrics[key]}"

        assert metrics["average_latency_ms"] >= 0.0

        # Verify subtask breakdown structure
        breakdown = data["subtask_breakdown"]
        assert "retrieval" in breakdown
        assert "generation" in breakdown
        assert "execution" in breakdown

        # Verify error_analysis structure
        assert "failed_queries" in data["error_analysis"]

        # Verify benchmark summary
        summary = data["benchmark_summary"]
        assert summary["status"] == "dry_run"
        assert "accuracy_summary" in summary
        assert isinstance(summary["recommendations"], list)
        assert len(summary["recommendations"]) > 0

        # Verify dataset statistics
        stats = data["dataset_statistics"]
        assert "queries_per_domain" in stats
        assert "total_queries_run" in stats
        assert "is_fallback" in stats
        assert isinstance(stats["is_fallback"], bool)

        # Verify failure categorization
        failure_cat = data["failure_categorization"]
        assert "counts" in failure_cat
        assert "total_failed_queries" in failure_cat
        assert isinstance(failure_cat["total_failed_queries"], int)

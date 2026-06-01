# Enterprise Text-to-SQL API Specification

## Overview

The Enterprise Text-to-SQL API exposes schema retrieval, SQL generation, and benchmark execution endpoints. All endpoints require authentication and tenant-aware authorization.

## Conventions

### Base URL

```text
https://api.example.com/v1
```

### Authentication

Requests must include a bearer token:

```http
Authorization: Bearer <access_token>
```

### Required Headers

| Header | Required | Description |
| --- | --- | --- |
| Authorization | Yes | Bearer token for user or service authentication. |
| Content-Type | Yes | Must be `application/json`. |
| X-Request-ID | No | Caller-provided correlation ID. |
| Idempotency-Key | No | Recommended for retryable generation and benchmark requests. |

### Standard Error Shape

```json
{
  "request_id": "req_01HX...",
  "status": "failed",
  "errors": [
    {
      "code": "VALIDATION_FAILED",
      "message": "Generated SQL references an unauthorized table.",
      "field": "sql",
      "details": {
        "table": "finance.payroll"
      }
    }
  ],
  "warnings": []
}
```

### Common Status Codes

| Status Code | Meaning |
| --- | --- |
| 200 | Request completed successfully. |
| 202 | Request accepted for asynchronous processing. |
| 400 | Invalid request. |
| 401 | Authentication failed. |
| 403 | Authorization denied. |
| 404 | Resource not found. |
| 409 | Conflicting request or idempotency conflict. |
| 422 | Request is well-formed but cannot be processed safely. |
| 429 | Rate limit exceeded. |
| 500 | Internal server error. |
| 503 | Downstream provider unavailable. |

## POST /retrieve

Retrieves authorized schema context relevant to a natural language question.

### Request

```http
POST /v1/retrieve
Content-Type: application/json
Authorization: Bearer <access_token>
```

```json
{
  "tenant_id": "tenant_123",
  "workspace_id": "workspace_456",
  "data_source_id": "ds_789",
  "question": "What were total enterprise sales by region last quarter?",
  "dialect": "postgres",
  "schema_snapshot_id": "schema_snap_001",
  "top_k": 20,
  "filters": {
    "include_schemas": ["analytics", "finance"],
    "exclude_tables": ["finance.payroll"],
    "max_sensitivity": "internal"
  },
  "user_context": {
    "actor_id": "user_123",
    "roles": ["analyst"],
    "groups": ["sales_ops"]
  }
}
```

### Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| tenant_id | string | Yes | Tenant identifier. |
| workspace_id | string | Yes | Workspace identifier. |
| data_source_id | string | Yes | Data source to search. |
| question | string | Yes | Natural language question. |
| dialect | string | No | SQL dialect hint. |
| schema_snapshot_id | string | No | Specific schema snapshot. Uses active snapshot when omitted. |
| top_k | integer | No | Maximum number of schema objects to return. |
| filters | object | No | Retrieval filters. |
| user_context | object | Yes | Actor and authorization attributes. |

### Response 200

```json
{
  "request_id": "req_01HXABC",
  "status": "success",
  "retrieval_id": "ret_01HXABC",
  "schema_snapshot_id": "schema_snap_001",
  "confidence_score": 0.89,
  "selected_objects": [
    {
      "object_id": "obj_sales_orders",
      "object_type": "table",
      "fully_qualified_name": "analytics.sales_orders",
      "description": "Order-level sales facts.",
      "score": 0.94
    },
    {
      "object_id": "obj_region",
      "object_type": "column",
      "fully_qualified_name": "analytics.sales_orders.region",
      "data_type": "text",
      "score": 0.91
    }
  ],
  "join_paths": [
    {
      "tables": ["analytics.sales_orders", "analytics.calendar"],
      "condition": "sales_orders.order_date = calendar.date_day",
      "confidence_score": 0.86
    }
  ],
  "examples": [
    {
      "example_id": "ex_001",
      "question": "Total sales by region this month",
      "sql_hash": "sha256:..."
    }
  ],
  "rationale": "The question asks for sales aggregated by region over a fiscal quarter; sales_orders and calendar provide the required measures and date filtering.",
  "warnings": [],
  "errors": [],
  "metadata": {
    "retrieval_strategy_version": "hybrid-v1",
    "latency_ms": 184
  }
}
```

### Error Codes

| Code | Description |
| --- | --- |
| SCHEMA_NOT_FOUND | Requested schema snapshot does not exist. |
| RETRIEVAL_NO_CONTEXT | No relevant authorized schema context found. |
| AUTHORIZATION_DENIED | Caller cannot access requested data source or schema objects. |
| RETRIEVAL_UNAVAILABLE | Search or vector index is unavailable. |

## POST /generate-sql

Generates SQL for a natural language question using retrieved schema context, then optionally validates and executes it.

### Request

```http
POST /v1/generate-sql
Content-Type: application/json
Authorization: Bearer <access_token>
Idempotency-Key: gen_01HXABC
```

```json
{
  "tenant_id": "tenant_123",
  "workspace_id": "workspace_456",
  "data_source_id": "ds_789",
  "question": "What were total enterprise sales by region last quarter?",
  "dialect": "postgres",
  "retrieval_id": "ret_01HXABC",
  "constraints": {
    "read_only": true,
    "row_limit": 500,
    "require_limit": true,
    "excluded_tables": ["finance.payroll"],
    "execution_timeout_ms": 10000
  },
  "model_config": {
    "provider": "openai",
    "model": "configured-model-name",
    "temperature": 0.1,
    "timeout_ms": 30000
  },
  "validate": true,
  "execute": false,
  "user_context": {
    "actor_id": "user_123",
    "roles": ["analyst"],
    "groups": ["sales_ops"]
  }
}
```

### Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| tenant_id | string | Yes | Tenant identifier. |
| workspace_id | string | Yes | Workspace identifier. |
| data_source_id | string | Yes | Target data source. |
| question | string | Yes | Natural language question. |
| dialect | string | No | SQL dialect. |
| retrieval_id | string | No | Existing retrieval result. Required unless schema_context is supplied. |
| schema_context | object | No | Inline schema context for advanced callers. |
| constraints | object | No | Safety, limit, and generation constraints. |
| model_config | object | No | Model provider override where allowed. |
| validate | boolean | No | Whether validation should run. Defaults to true. |
| execute | boolean | No | Whether execution should run after validation. Defaults to false. |
| user_context | object | Yes | Actor and authorization attributes. |

### Response 200

```json
{
  "request_id": "req_01HXDEF",
  "status": "success",
  "generation_id": "gen_01HXDEF",
  "sql": "SELECT so.region, SUM(so.enterprise_sales_amount) AS total_sales FROM analytics.sales_orders so JOIN analytics.calendar c ON so.order_date = c.date_day WHERE c.fiscal_quarter = '2026-Q1' GROUP BY so.region ORDER BY total_sales DESC LIMIT 500",
  "explanation": "Aggregates enterprise sales by region for the requested fiscal quarter using the sales fact table and calendar dimension.",
  "assumptions": [
    "Last quarter resolves to fiscal quarter 2026-Q1 based on workspace calendar settings.",
    "enterprise_sales_amount is the approved sales measure."
  ],
  "referenced_objects": [
    "analytics.sales_orders",
    "analytics.sales_orders.region",
    "analytics.sales_orders.enterprise_sales_amount",
    "analytics.calendar",
    "analytics.calendar.fiscal_quarter"
  ],
  "validation": {
    "validation_id": "val_01HXDEF",
    "status": "passed",
    "normalized_sql": "SELECT so.region, SUM(so.enterprise_sales_amount) AS total_sales FROM analytics.sales_orders AS so JOIN analytics.calendar AS c ON so.order_date = c.date_day WHERE c.fiscal_quarter = '2026-Q1' GROUP BY so.region ORDER BY total_sales DESC LIMIT 500",
    "execution_eligible": true,
    "risk_score": 0.18,
    "errors": [],
    "warnings": []
  },
  "execution": null,
  "model_metadata": {
    "provider": "openai",
    "model": "configured-model-name",
    "prompt_template_version": "text-to-sql-v1",
    "input_tokens": 3210,
    "output_tokens": 184,
    "latency_ms": 2410
  },
  "warnings": [],
  "errors": [],
  "metadata": {
    "retrieval_id": "ret_01HXABC"
  }
}
```

### Error Codes

| Code | Description |
| --- | --- |
| RETRIEVAL_REQUIRED | Neither retrieval_id nor schema_context was supplied. |
| GENERATION_FAILED | Model provider failed or returned unusable output. |
| PROMPT_CONTEXT_TOO_LARGE | Retrieved context exceeds configured model limits. |
| VALIDATION_FAILED | Generated SQL failed validation. |
| EXECUTION_DENIED | Execution was requested but policy denied it. |
| MODEL_PROVIDER_UNAVAILABLE | Configured model provider is unavailable. |

## POST /benchmark

Starts or runs a benchmark suite for retrieval, SQL generation, validation, and optional execution quality.

### Request

```http
POST /v1/benchmark
Content-Type: application/json
Authorization: Bearer <access_token>
Idempotency-Key: bench_01HXABC
```

```json
{
  "tenant_id": "tenant_123",
  "workspace_id": "workspace_456",
  "benchmark_suite_id": "bench_suite_sales_ops",
  "mode": "async",
  "baseline_run_id": "bench_run_previous",
  "config": {
    "schema_snapshot_id": "schema_snap_001",
    "retrieval_strategy_version": "hybrid-v1",
    "prompt_template_version": "text-to-sql-v1",
    "validation_policy_version": "sql-safety-v1",
    "model_config": {
      "provider": "openai",
      "model": "configured-model-name",
      "temperature": 0.0
    },
    "execution": {
      "enabled": true,
      "timeout_ms": 10000,
      "row_limit": 1000
    },
    "evaluators": {
      "retrieval_recall": true,
      "sql_ast_similarity": true,
      "execution_result_match": true,
      "latency": true,
      "cost": true
    }
  },
  "user_context": {
    "actor_id": "user_123",
    "roles": ["data_engineer"],
    "groups": ["data_platform"]
  }
}
```

### Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| tenant_id | string | Yes | Tenant identifier. |
| workspace_id | string | Yes | Workspace identifier. |
| benchmark_suite_id | string | Yes | Benchmark suite to run. |
| mode | enum | No | sync or async. Defaults to async. |
| baseline_run_id | string | No | Prior benchmark run for comparison. |
| config | object | Yes | Benchmark runtime configuration. |
| user_context | object | Yes | Actor and authorization attributes. |

### Response 202

```json
{
  "request_id": "req_01HXGHI",
  "status": "accepted",
  "benchmark_run_id": "bench_run_01HXGHI",
  "run_status": "queued",
  "metrics": null,
  "report_url": null,
  "comparison": null,
  "warnings": [],
  "errors": [],
  "metadata": {
    "benchmark_suite_id": "bench_suite_sales_ops",
    "dataset_version": "sales-ops-v3",
    "estimated_case_count": 250
  }
}
```

### Response 200

Returned for synchronous runs that complete within the request timeout.

```json
{
  "request_id": "req_01HXGHI",
  "status": "success",
  "benchmark_run_id": "bench_run_01HXGHI",
  "run_status": "succeeded",
  "metrics": {
    "total_cases": 250,
    "retrieval_table_recall": 0.92,
    "retrieval_column_recall": 0.87,
    "sql_parse_success_rate": 0.96,
    "validation_pass_rate": 0.91,
    "execution_success_rate": 0.88,
    "result_accuracy": 0.84,
    "p95_latency_ms": 7120,
    "average_token_cost": 0.014
  },
  "report_url": "s3://enterprise-text-to-sql/benchmarks/bench_run_01HXGHI/report.html",
  "comparison": {
    "baseline_run_id": "bench_run_previous",
    "result_accuracy_delta": 0.03,
    "p95_latency_delta_ms": -420,
    "regressions": [
      {
        "case_id": "case_087",
        "metric": "result_accuracy",
        "previous": 1.0,
        "current": 0.0
      }
    ]
  },
  "warnings": [],
  "errors": [],
  "metadata": {
    "benchmark_suite_id": "bench_suite_sales_ops",
    "dataset_version": "sales-ops-v3"
  }
}
```

### Error Codes

| Code | Description |
| --- | --- |
| BENCHMARK_SUITE_NOT_FOUND | Requested benchmark suite does not exist. |
| BENCHMARK_CONFIG_INVALID | Benchmark configuration is invalid. |
| BENCHMARK_ALREADY_RUNNING | A conflicting benchmark run is already active. |
| BENCHMARK_EXECUTION_FAILED | Benchmark failed during execution. |
| BASELINE_NOT_FOUND | Requested baseline run does not exist. |

## Versioning

Breaking API changes must be introduced under a new major version path. Prompt templates, validation policies, schema snapshots, retrieval strategies, and benchmark datasets must be independently versioned and referenced in responses for reproducibility.

## Rate Limits

Rate limits should be enforced by tenant, user, endpoint, and model provider. Benchmark endpoints should have stricter limits than retrieval endpoints because they may trigger large batch workloads.

## Idempotency

Clients should provide `Idempotency-Key` for generation and benchmark requests. The server should return the original response for retried equivalent requests and reject conflicting payloads with `409 Conflict`.

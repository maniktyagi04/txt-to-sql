# Enterprise Text-to-SQL API Backend Schema

## Folder Structure

The following folder structure is recommended for an enterprise backend. Names are illustrative and should be adapted to the chosen runtime and framework.

```text
enterprise-text-to-sql-api/
  docs/
    PRD.md
    TRD.md
    APP_FLOW.md
    BACKEND_SCHEMA.md
    API_SPECIFICATION.md
  src/
    api/
      routes/
      middleware/
      validators/
      serializers/
    config/
      environment/
      tenants/
      policies/
    services/
      retrieval/
      generation/
      validation/
      execution/
      benchmark/
      schema_ingestion/
      audit/
      authorization/
    models/
      domain/
      persistence/
      api/
    repositories/
      schema_repository/
      benchmark_repository/
      audit_repository/
      configuration_repository/
    providers/
      llm/
      database/
      vector_store/
      identity/
      secrets/
    workers/
      schema_indexing/
      benchmark_runner/
      execution_runner/
    observability/
      logging/
      metrics/
      tracing/
    policies/
      sql_safety/
      data_access/
      retention/
    tests/
      unit/
      integration/
      contract/
      benchmark/
  migrations/
  scripts/
  deploy/
```

## Service Layer Design

### API Layer

- Owns external HTTP contracts.
- Performs request validation, authentication middleware, response serialization, and error mapping.
- Must not contain retrieval, generation, validation, or execution business logic.

### Authorization Service

- Resolves effective permissions for a caller.
- Produces an authorization context used by retrieval, validation, and execution.
- Enforces tenant isolation and object-level access controls.

### Schema Service

- Manages data source registration and schema snapshots.
- Provides schema metadata lookup for retrieval and validation.
- Maintains immutable schema versions to support reproducibility.

### Retrieval Service

- Coordinates lexical search, vector search, graph expansion, and reranking.
- Returns schema context optimized for prompt construction.
- Must only return authorized schema objects.

### Generation Service

- Owns prompt orchestration and LLM provider interaction.
- Produces structured generation results.
- Must treat retrieved context and model output as separate auditable artifacts.

### Validation Service

- Parses and analyzes generated SQL.
- Enforces SQL safety and authorization policies.
- Produces execution eligibility and risk metadata.

### Execution Service

- Runs validated SQL through controlled connectors.
- Enforces execution limits and database-level safety controls.
- Returns result previews and execution diagnostics.

### Benchmark Service

- Schedules and executes benchmark cases.
- Aggregates metrics and compares against baselines.
- Stores reproducible benchmark artifacts and configuration references.

### Audit Service

- Records lifecycle events across all pipeline stages.
- Supports compliance investigation and security review.
- Provides immutable or append-only audit records.

## Data Models

### Tenant

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique tenant identifier. |
| name | string | Tenant display name. |
| status | enum | active, suspended, archived. |
| retention_policy_id | string | Default retention policy. |
| created_at | timestamp | Creation timestamp. |
| updated_at | timestamp | Last update timestamp. |

### Workspace

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique workspace identifier. |
| tenant_id | string | Owning tenant. |
| name | string | Workspace display name. |
| default_dialect | string | Preferred SQL dialect. |
| created_at | timestamp | Creation timestamp. |

### DataSource

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique data source identifier. |
| tenant_id | string | Owning tenant. |
| workspace_id | string | Owning workspace. |
| type | enum | postgres, mysql, snowflake, bigquery, sqlserver, other. |
| name | string | Display name. |
| connection_secret_ref | string | Reference to secret manager entry. |
| status | enum | active, disabled, error. |
| read_only | boolean | Whether execution credentials are read-only. |
| created_at | timestamp | Creation timestamp. |

### SchemaSnapshot

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique snapshot identifier. |
| data_source_id | string | Source database. |
| version | string | Immutable schema version. |
| captured_at | timestamp | Snapshot timestamp. |
| dialect | string | SQL dialect. |
| table_count | integer | Number of tables captured. |
| column_count | integer | Number of columns captured. |
| status | enum | indexing, ready, failed, archived. |

### SchemaObject

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique object identifier. |
| schema_snapshot_id | string | Owning schema snapshot. |
| object_type | enum | database, schema, table, view, column, index, constraint, relationship. |
| fully_qualified_name | string | Dialect-specific qualified name. |
| parent_id | string | Parent schema object when applicable. |
| description | string | Human-readable metadata. |
| data_type | string | Column data type when applicable. |
| sensitivity | enum | public, internal, confidential, restricted. |
| metadata | object | Additional database-specific metadata. |

### RetrievalResult

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique retrieval result identifier. |
| request_id | string | Correlation ID. |
| question | string | User question. |
| schema_snapshot_id | string | Schema snapshot used. |
| strategy_version | string | Retrieval strategy version. |
| selected_objects | array | Tables, columns, joins, examples, and glossary terms. |
| confidence_score | number | Retrieval confidence from 0 to 1. |
| rationale | string | Short explanation of selected context. |
| created_at | timestamp | Creation timestamp. |

### GenerationResult

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique generation result identifier. |
| request_id | string | Correlation ID. |
| retrieval_result_id | string | Source retrieval result. |
| model_provider | string | LLM provider. |
| model_name | string | Model name. |
| prompt_template_version | string | Prompt version. |
| sql | string | Generated SQL, retained according to policy. |
| sql_hash | string | Hash of generated SQL. |
| explanation | string | Human-readable explanation. |
| assumptions | array | Model assumptions. |
| token_usage | object | Input and output token counts. |
| created_at | timestamp | Creation timestamp. |

### ValidationResult

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique validation result identifier. |
| request_id | string | Correlation ID. |
| generation_result_id | string | Source generation result. |
| status | enum | passed, warning, failed. |
| normalized_sql | string | Canonical SQL form. |
| referenced_objects | array | Tables and columns referenced by SQL. |
| errors | array | Blocking validation errors. |
| warnings | array | Non-blocking warnings. |
| risk_score | number | Risk score from 0 to 1. |
| execution_eligible | boolean | Whether SQL may be executed. |
| created_at | timestamp | Creation timestamp. |

### ExecutionResult

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique execution result identifier. |
| request_id | string | Correlation ID. |
| validation_result_id | string | Source validation result. |
| status | enum | succeeded, failed, cancelled, timed_out. |
| columns | array | Result column metadata. |
| rows | array | Result preview rows. |
| row_count | integer | Number of rows returned. |
| execution_time_ms | integer | Database execution duration. |
| diagnostics | object | Database-specific execution metadata. |
| created_at | timestamp | Creation timestamp. |

### BenchmarkSuite

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique benchmark suite identifier. |
| tenant_id | string | Owning tenant. |
| name | string | Suite name. |
| dataset_version | string | Immutable dataset version. |
| schema_snapshot_id | string | Schema snapshot used. |
| evaluator_config | object | Evaluation settings. |
| status | enum | draft, active, archived. |

### BenchmarkRun

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique benchmark run identifier. |
| benchmark_suite_id | string | Source suite. |
| status | enum | queued, running, succeeded, failed, cancelled. |
| config | object | Model, retrieval, prompt, validation, and execution config. |
| metrics | object | Aggregate benchmark metrics. |
| started_at | timestamp | Start timestamp. |
| completed_at | timestamp | Completion timestamp. |

### AuditEvent

| Field | Type | Description |
| --- | --- | --- |
| id | string | Unique audit event identifier. |
| request_id | string | Correlation ID. |
| tenant_id | string | Tenant context. |
| actor_id | string | User or service actor. |
| event_type | string | Event name. |
| resource_type | string | Resource category. |
| resource_id | string | Resource identifier. |
| decision | enum | allowed, denied, not_applicable. |
| metadata | object | Redacted event metadata. |
| created_at | timestamp | Event timestamp. |

## Request/Response Contracts

### Common Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| request_id | string | No | Caller-provided correlation ID. Generated when omitted. |
| tenant_id | string | Yes | Tenant identifier. |
| workspace_id | string | Yes | Workspace identifier. |
| user_context | object | Yes | Actor, roles, groups, and policy attributes. |
| data_source_id | string | Conditional | Required when endpoint needs a target database. |
| dialect | string | No | SQL dialect override. |

### Common Response Fields

| Field | Type | Description |
| --- | --- | --- |
| request_id | string | Correlation ID. |
| status | string | success, accepted, failed, or partial. |
| errors | array | Blocking errors. |
| warnings | array | Non-blocking warnings. |
| metadata | object | Endpoint-specific metadata. |

### Retrieve Request

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| question | string | Yes | Natural language question. |
| schema_snapshot_id | string | No | Specific schema snapshot. Defaults to active snapshot. |
| filters | object | No | Include or exclude schemas, tables, tags, or sensitivity levels. |
| top_k | integer | No | Maximum retrieved schema objects. |

### Retrieve Response

| Field | Type | Description |
| --- | --- | --- |
| retrieval_id | string | Retrieval result identifier. |
| schema_snapshot_id | string | Snapshot used. |
| selected_objects | array | Selected schema objects and examples. |
| join_paths | array | Candidate join paths. |
| confidence_score | number | Retrieval confidence from 0 to 1. |
| rationale | string | Retrieval rationale. |

### Generate SQL Request

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| question | string | Yes | Natural language question. |
| retrieval_id | string | No | Existing retrieval result. |
| schema_context | object | No | Inline retrieval context when retrieval_id is absent. |
| constraints | object | No | Row limit, required filters, excluded tables, execution mode. |
| model_config | object | No | Model provider, model name, temperature, timeout. |
| validate | boolean | No | Whether to run validation after generation. Defaults to true. |
| execute | boolean | No | Whether to execute after validation. Defaults to false. |

### Generate SQL Response

| Field | Type | Description |
| --- | --- | --- |
| generation_id | string | Generation result identifier. |
| sql | string | Generated SQL. |
| explanation | string | Explanation of query logic. |
| assumptions | array | Assumptions made during generation. |
| validation | object | Validation result when requested. |
| execution | object | Execution result when requested and allowed. |
| model_metadata | object | Provider, model, prompt version, token usage. |

### Benchmark Request

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| benchmark_suite_id | string | Yes | Benchmark suite to run. |
| config | object | Yes | Retrieval, model, prompt, validation, and execution settings. |
| mode | enum | No | sync or async. Defaults to async. |
| baseline_run_id | string | No | Baseline run for comparison. |

### Benchmark Response

| Field | Type | Description |
| --- | --- | --- |
| benchmark_run_id | string | Benchmark run identifier. |
| status | string | queued, running, succeeded, failed, or cancelled. |
| metrics | object | Aggregate metrics when available. |
| report_url | string | Report artifact when available. |
| comparison | object | Baseline comparison when requested. |

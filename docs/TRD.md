# Enterprise Text-to-SQL API TRD

> **Implementation Scope:** This document describes the full target technical design.
> The current implementation covers the core pipeline (retrieval, generation, validation,
> execution, benchmarking) without multi-tenancy, authentication layers, async job workers,
> or audit services. See `FINAL_SUBMISSION_REPORT.md` for exact implementation scope.

## Architecture

The Enterprise Text-to-SQL API is organized as a staged pipeline:

1. Client submits a natural language question and execution context.
2. API gateway authenticates the caller and applies tenant policy.
3. Retrieval service selects relevant schema fragments, examples, and business metadata.
4. SQL generation service prompts the configured LLM using retrieved context and policy constraints.
5. Validation service parses, normalizes, authorizes, and risk-scores generated SQL.
6. Execution service optionally runs safe SQL through a controlled database connection.
7. Benchmark service evaluates retrieval and generation quality across curated datasets.
8. Observability, audit, and configuration services support the full lifecycle.

The system should support both synchronous low-latency requests and asynchronous job execution for long-running benchmarks or database operations.

## Components

### API Gateway

- Terminates API requests.
- Validates authentication tokens and request shape.
- Applies rate limits, tenant quotas, and request size limits.
- Propagates correlation IDs.
- Routes requests to retrieval, generation, execution, and benchmark services.

### Identity and Authorization Layer

- Resolves caller identity, tenant, workspace, role, and data access policies.
- Enforces table, column, row, and data source permissions before context retrieval and execution.
- Integrates with enterprise identity providers through OAuth2, OIDC, SAML-backed gateways, or service tokens.

### Schema Ingestion Service

- Connects to supported databases using read-only metadata credentials.
- Extracts schema metadata, constraints, indexes, relationships, comments, and optional statistics.
- Produces immutable schema snapshots.
- Triggers indexing workflows after snapshot creation.

### Schema Index Service

- Builds lexical and vector indexes from schema snapshots.
- Stores table-level, column-level, relationship-level, glossary, and query-example embeddings.
- Supports metadata filters for tenant, database, schema, dialect, sensitivity, and freshness.

### Retrieval Service

- Accepts natural language questions and context constraints.
- Performs hybrid retrieval across schema metadata, glossary entries, examples, and relationship graphs.
- Ranks candidate tables, columns, join paths, and examples.
- Returns retrieval evidence and confidence signals.

### Prompt Orchestration Service

- Builds model prompts from versioned prompt templates, retrieved schema context, request constraints, dialect rules, and security policy.
- Redacts or excludes disallowed metadata.
- Records prompt template versions and model configuration for audit and benchmarking.

### SQL Generation Service

- Calls the configured LLM provider or self-hosted model.
- Supports deterministic and creative generation settings by use case.
- Produces SQL, explanation, assumptions, and model metadata.
- Supports regeneration using validation or execution feedback.

### SQL Validation Service

- Parses SQL using a dialect-aware parser.
- Rejects unsafe statements and unsupported constructs.
- Verifies referenced objects against authorized schema.
- Normalizes generated SQL for explainability and comparison.
- Produces errors, warnings, risk scores, and suggested remediation.

### Execution Service

- Executes validated read-only SQL against approved database connections.
- Applies timeout, row limit, concurrency, and cancellation controls.
- Supports dry-run, explain-plan, and result-preview modes where available.
- Returns tabular result metadata and execution diagnostics.

### Benchmark Service

- Runs configured evaluation datasets.
- Evaluates retrieval relevance, SQL syntax, validation, execution success, result correctness, and latency.
- Compares benchmark runs across model, prompt, retrieval, validation, and schema versions.
- Produces reports for release readiness and regression detection.

### Audit Service

- Stores immutable records for request lifecycle events.
- Captures caller, tenant, policy decision, retrieved schema references, generated SQL hash or full SQL depending on policy, validation outcome, execution metadata, and benchmark metadata.
- Supports compliance exports and incident investigation.

### Configuration Service

- Stores tenant configuration, model routing, dialect preferences, retrieval settings, execution policies, retention policies, and benchmark settings.
- Versions prompts, policies, schema snapshots, and benchmark datasets.

## Technology Decisions

### API Layer

- Recommended style: REST for external API compatibility, with OpenAPI documentation.
- Internal communication: gRPC or typed HTTP clients for service-to-service calls.
- Async jobs: queue-backed workers for benchmarking, schema indexing, and long-running execution.

### Backend Runtime

- Recommended languages: Python for ML and retrieval services; TypeScript, Go, Java, or Python for API and orchestration services depending on platform standards.
- Service design should prioritize typed contracts, explicit error models, and dependency injection for testability.

### Datastores

- Metadata store: PostgreSQL for tenants, users, schema snapshots, policies, benchmark runs, and audit indexes.
- Vector store: pgvector, OpenSearch, Pinecone, Weaviate, Milvus, or equivalent depending on deployment requirements.
- Object store: S3-compatible storage for benchmark artifacts, exported reports, and large schema snapshots.
- Cache: Redis or equivalent for hot schema fragments, request deduplication, and rate-limit counters.

### SQL Parsing and Analysis

- Use a dialect-aware SQL parser instead of string matching.
- Parser must expose AST-level statement type, identifiers, functions, joins, predicates, limits, and subqueries.
- Validation policy should be declarative and testable.

### LLM Provider Strategy

- Support pluggable model providers through a provider interface.
- Store model name, version, temperature, prompt template version, and token usage for each generation.
- Allow tenant-level routing between hosted and self-hosted models.
- Implement provider timeouts, retries, circuit breakers, and fallback rules.

### Retrieval Strategy

- Use hybrid retrieval combining keyword search, embeddings, schema graph traversal, and reranking.
- Retrieval should include positive signals from table descriptions, column comments, prior validated examples, and business glossary terms.
- Retrieval should include negative signals for unauthorized, deprecated, hidden, or low-confidence objects.

### Benchmarking Strategy

- Benchmark datasets should be versioned and immutable after publication.
- Evaluation should support exact SQL match, AST similarity, execution result equivalence, and LLM-assisted judging for explanation quality when appropriate.
- Release promotion should require benchmark thresholds for target domains.

## Security Requirements

### Authentication

- Require authenticated access for every endpoint.
- Support service-to-service tokens and end-user delegated tokens.
- Validate token issuer, audience, expiration, and tenant binding.

### Authorization

- Enforce authorization before exposing schema metadata to retrieval or prompts.
- Enforce database, schema, table, column, and row-level access policies where available.
- Ensure generated SQL cannot reference unauthorized objects even if suggested by the LLM.

### Query Safety

- Default to read-only execution.
- Reject mutation statements, DDL, privilege operations, transaction control, stored procedure calls, external file access, and multi-statement payloads unless explicitly enabled for controlled internal use.
- Enforce row limits, timeouts, concurrency limits, and cancellation.
- Require explicit policy approval for cross-database queries.

### Prompt and Model Safety

- Do not include secrets, credentials, connection strings, or privileged internal policy details in prompts.
- Redact sensitive sample values unless policy permits them.
- Treat model output as untrusted input until validation succeeds.
- Store prompt and completion data according to tenant retention policy.

### Data Protection

- Encrypt data in transit with TLS.
- Encrypt persisted metadata, audit records, benchmark artifacts, and cached values at rest.
- Keep database credentials in a managed secret store.
- Separate tenant data logically and enforce tenant isolation in every query.

### Compliance and Audit

- Record policy decisions and query lifecycle events.
- Support configurable retention and deletion policies.
- Support audit exports for security review.
- Preserve enough metadata to reproduce benchmark and generation outcomes without exposing unnecessary sensitive data.

## Logging Strategy

### Logging Principles

- Logs must be structured, searchable, and correlated by request ID.
- Logs must not contain secrets or raw sensitive data unless explicitly allowed by tenant policy.
- Every pipeline stage must emit start, success, failure, latency, and relevant metadata.
- Audit logs must be immutable or append-only.

### Request Logs

- request_id
- tenant_id
- workspace_id
- actor_id or service_id
- endpoint
- request mode
- dialect
- status code
- latency_ms
- error_code when applicable

### Retrieval Logs

- schema_snapshot_id
- retrieval_strategy_version
- candidate_count
- selected_table_count
- selected_column_count
- retrieval_latency_ms
- confidence_score
- filtered_object_count

### Generation Logs

- model_provider
- model_name
- prompt_template_version
- input_token_count
- output_token_count
- generation_latency_ms
- completion_status
- generated_sql_hash
- regeneration_attempt

### Validation Logs

- parser_name
- parser_version
- validation_policy_version
- statement_type
- referenced_object_count
- validation_status
- warning_codes
- error_codes
- risk_score

### Execution Logs

- connection_id
- database_type
- execution_mode
- query_hash
- timeout_ms
- row_limit
- rows_returned
- execution_latency_ms
- database_error_code when applicable

### Benchmark Logs

- benchmark_run_id
- benchmark_suite_id
- dataset_version
- model_config_version
- retrieval_config_version
- prompt_template_version
- total_cases
- passed_cases
- failed_cases
- aggregate_metrics

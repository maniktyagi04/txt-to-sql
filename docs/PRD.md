# Enterprise Text-to-SQL API PRD

## Problem Statement

Enterprise teams store critical business data across relational databases, warehouses, and domain-specific schemas. Analysts and operators often need answers quickly, but the ability to write correct SQL is unevenly distributed across the organization. This creates dependency on data teams, slows decision-making, and increases the likelihood of inconsistent query logic.

The Enterprise Text-to-SQL API converts natural language questions into executable SQL by retrieving relevant schema context, generating SQL with an LLM, validating the query for safety and correctness, optionally executing it, and benchmarking quality over known datasets. The system must be reliable, auditable, secure, and adaptable to complex enterprise schemas.

## User Personas

### Business Analyst

- Asks operational and reporting questions in natural language.
- Needs fast, trustworthy SQL and result previews.
- May understand business terminology but not physical schema details.
- Values clear explanations, query confidence, and safe failure modes.

### Data Engineer

- Owns database connectivity, schema indexing, lineage, and execution safety.
- Needs observability, governance controls, and reproducible benchmark results.
- Reviews generated SQL for correctness and performance impact.
- Values deterministic interfaces, clear logs, and extensible service boundaries.

### Analytics Engineer

- Curates semantic definitions, joins, metrics, and query examples.
- Needs a way to improve retrieval quality through schema metadata and examples.
- Validates whether generated queries follow domain conventions.
- Values explainable schema selection and benchmarkable quality improvements.

### Application Developer

- Integrates the Text-to-SQL capability into internal tools, copilots, dashboards, or workflow systems.
- Needs stable APIs, clear request/response contracts, error handling, and versioning.
- Values low-latency responses, predictable failure modes, and tenant-safe isolation.

### Security and Compliance Reviewer

- Reviews data access, auditability, PII handling, and query execution controls.
- Needs evidence that generated SQL cannot bypass authorization policies.
- Values immutable audit trails, least-privilege execution, and strict secret management.

## Functional Requirements

### Schema Retrieval

- Ingest database schemas, tables, columns, indexes, constraints, foreign keys, comments, sample values, and optional business glossary metadata.
- Retrieve the most relevant schema fragments for a natural language question.
- Support hybrid retrieval using lexical search, vector embeddings, metadata filters, and relationship traversal.
- Return retrieval evidence, including selected tables, columns, join paths, confidence scores, and rationale.
- Support tenant, workspace, database, and dialect-specific filtering.

### SQL Generation

- Generate SQL from a natural language question and retrieved schema context.
- Support multiple SQL dialects, including PostgreSQL, MySQL, Snowflake, BigQuery, and SQL Server as target extensions.
- Include optional query explanation and assumptions.
- Allow caller-provided constraints such as read-only mode, row limits, required tables, excluded tables, and execution timeout.
- Support regeneration with feedback from validation or execution errors.

### SQL Validation

- Parse generated SQL before execution.
- Reject unsafe statements such as data modification, DDL, privilege changes, multi-statement payloads, and vendor-specific escape hatches unless explicitly allowed by policy.
- Verify referenced tables and columns exist in retrieved or authorized schema.
- Check tenant authorization and database access policy before execution.
- Estimate risk signals such as missing filters, cross joins, unbounded scans, expensive aggregations, and unsupported functions.
- Provide actionable validation errors and warnings.

### SQL Execution

- Execute validated read-only SQL through controlled database connections when execution is enabled.
- Enforce query timeout, row limit, byte scan limit where supported, and cancellation.
- Return results, schema metadata, execution duration, and database execution diagnostics.
- Support dry-run or explain-plan modes for databases that provide them.

### Benchmarking

- Run benchmark suites containing natural language questions, expected SQL, expected result sets, or evaluator rules.
- Measure retrieval accuracy, SQL validity, execution success, result correctness, latency, and token usage.
- Compare runs across model versions, prompts, retrieval strategies, and schema snapshots.
- Store benchmark run metadata, dataset version, configuration, and aggregate metrics.
- Export benchmark reports for engineering review.

### Administration

- Register data sources and schema snapshots.
- Configure allowed databases, tables, roles, dialects, models, and execution policies.
- Manage benchmark datasets and evaluation configurations.
- Provide audit access for generated SQL, validation outcomes, execution metadata, and user activity.

## Non Functional Requirements

### Reliability

- The API must fail safely when retrieval confidence is low, validation fails, execution is denied, or downstream systems are unavailable.
- Core services should be independently deployable and observable.
- Retried requests must be idempotent when an idempotency key is supplied.

### Security

- All requests must be authenticated.
- Authorization must be enforced before schema retrieval, SQL generation, validation, and execution.
- Execution must use least-privilege, read-only database credentials by default.
- Secrets must never be logged, returned, embedded in prompts, or exposed to model providers.

### Privacy

- Prompt context must minimize exposure of sensitive schema metadata and sample values.
- PII handling must be configurable by tenant policy.
- Request, response, and benchmark retention must follow configured data retention policies.

### Performance

- Retrieval should complete within 1 second for typical schema collections.
- SQL generation should support streaming or async operation for high-latency models.
- End-to-end generate-and-validate latency should target under 8 seconds for typical requests.
- Benchmark execution must support batch scheduling and concurrency limits.

### Scalability

- The system must support multiple tenants, databases, schemas, and benchmark suites.
- Schema indexes must scale to thousands of tables and millions of metadata tokens.
- Long-running benchmark and execution jobs must not block synchronous API traffic.

### Observability

- Each request must have a correlation ID propagated across services.
- Logs, metrics, and traces must capture retrieval, generation, validation, execution, and benchmark stages.
- Production telemetry must avoid raw sensitive data unless explicitly permitted by policy.

### Maintainability

- Service boundaries must be clear and testable.
- Prompts, model settings, retrieval configuration, and validation policy should be versioned.
- The system must support model and retrieval strategy experimentation without API-breaking changes.

## Success Metrics

### Product Metrics

- Percentage of accepted generated SQL queries.
- Time saved compared with manual SQL authoring.
- Number of active users and integrated applications.
- User-reported usefulness score for generated query and explanation.

### Quality Metrics

- Retrieval recall at table and column level.
- SQL parse success rate.
- Validation pass rate for safe queries.
- Execution success rate.
- Result-set accuracy against benchmark ground truth.
- Rate of hallucinated tables, columns, joins, or filters.

### Operational Metrics

- P50, P95, and P99 latency by endpoint and pipeline stage.
- Error rate by service, model provider, database connector, and tenant.
- Token usage and model cost per successful query.
- Benchmark run duration and pass/fail trend.

### Security Metrics

- Count of blocked unsafe SQL attempts.
- Count of denied authorization attempts.
- Audit log completeness.
- Percentage of execution requests using read-only credentials.

### Adoption Metrics

- Number of onboarded data sources.
- Number of indexed schemas.
- Benchmark dataset coverage by domain.
- Repeat usage by analysts and integrated applications.

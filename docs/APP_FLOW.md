# Enterprise Text-to-SQL API Application Flow

## Retrieval Flow

### Objective

Identify the minimum authorized schema context required to answer a natural language question accurately.

### Flow

1. Client sends a question, tenant context, target data source, optional dialect, and optional filters.
2. API gateway authenticates the caller and assigns a request ID.
3. Authorization layer resolves allowed databases, schemas, tables, columns, and policies.
4. Retrieval service normalizes the question and extracts entities, metrics, time references, dimensions, and possible filters.
5. Retrieval service performs lexical search against table names, column names, comments, glossary entries, and examples.
6. Retrieval service performs vector search against embedded schema documentation and query examples.
7. Schema graph traversal expands candidate tables through known relationships and foreign keys.
8. Reranker scores candidates using semantic relevance, authorization, schema quality, relationship confidence, and prior validated examples.
9. Retrieval service returns selected tables, columns, join paths, examples, glossary terms, confidence score, and rationale.
10. Low-confidence retrieval returns warnings and may request clarification instead of continuing to generation.

### Inputs

- Natural language question.
- Tenant and workspace context.
- Data source or schema scope.
- SQL dialect.
- Optional required or excluded objects.
- Optional user role and policy context.

### Outputs

- Retrieved schema fragments.
- Relevant examples.
- Join path candidates.
- Business glossary terms.
- Retrieval confidence score.
- Retrieval rationale.
- Clarification prompt when context is insufficient.

### Failure Modes

- No authorized schema available.
- No relevant schema found.
- Conflicting schema candidates.
- Schema index unavailable.
- Retrieval confidence below policy threshold.

## SQL Generation Flow

### Objective

Generate executable, dialect-correct, policy-compliant SQL using retrieved schema context and user constraints.

### Flow

1. SQL generation request is created from the original question and retrieval result.
2. Prompt orchestration service loads the configured prompt template, dialect instructions, and tenant policy.
3. Prompt context is minimized to authorized tables, columns, joins, examples, and constraints.
4. Prompt orchestration service adds output formatting requirements, safety constraints, and known assumptions.
5. SQL generation service calls the configured LLM provider.
6. Model response is parsed into SQL, explanation, assumptions, and confidence indicators.
7. Generated SQL is normalized for validation.
8. SQL generation service records model metadata, token usage, prompt template version, and generated SQL hash.
9. Validation flow starts automatically unless the caller requested generation-only mode.
10. If validation fails and retry policy allows regeneration, validation errors are fed back into a regeneration attempt.

### Inputs

- Natural language question.
- Retrieved schema context.
- SQL dialect.
- Execution mode.
- Query constraints.
- Prompt template version.
- Model configuration.

### Outputs

- Generated SQL.
- Explanation.
- Assumptions.
- Referenced schema objects.
- Model metadata.
- Generation confidence.

### Failure Modes

- Model provider timeout.
- Prompt exceeds context limit.
- Model output is malformed.
- Generated SQL omits required constraints.
- Generated SQL references missing or unauthorized schema objects.

## Validation Flow

### Objective

Ensure generated SQL is syntactically valid, authorized, safe, and operationally acceptable before execution.

### Flow

1. Validation service receives generated SQL, dialect, retrieved schema context, and authorization context.
2. SQL parser creates a dialect-aware AST.
3. Validator confirms the SQL contains exactly one allowed statement.
4. Validator rejects mutation, DDL, privilege, transaction, procedure, external access, and multi-statement operations by default.
5. Validator extracts referenced tables, columns, functions, joins, filters, subqueries, limits, and aggregations.
6. Validator verifies every referenced object exists in the authorized schema scope.
7. Validator checks policy constraints such as required filters, row limits, sensitive columns, and cross-schema access.
8. Validator applies risk analysis for unbounded scans, broad joins, missing predicates, unsupported functions, and expensive patterns.
9. Validator optionally invokes dry-run or explain-plan against the database.
10. Validator returns status, normalized SQL, errors, warnings, risk score, and execution eligibility.

### Inputs

- Generated SQL.
- SQL dialect.
- Authorization context.
- Retrieved schema references.
- Validation policy version.
- Optional execution limits.

### Outputs

- Validation status.
- Normalized SQL.
- Referenced objects.
- Errors and warnings.
- Risk score.
- Execution eligibility.
- Optional dry-run or explain-plan metadata.

### Failure Modes

- SQL parse failure.
- Unsafe statement type.
- Unauthorized object reference.
- Missing required policy predicate.
- Query exceeds estimated risk threshold.
- Database dry-run unavailable or failed.

## Benchmark Flow

### Objective

Measure and compare Text-to-SQL quality, safety, latency, and cost across datasets, schemas, prompts, models, and retrieval strategies.

### Flow

1. Client starts a benchmark run for a specific benchmark suite and configuration.
2. Benchmark service resolves dataset version, schema snapshot, retrieval config, prompt template, model config, and validation policy.
3. Benchmark service creates a benchmark run record and schedules cases.
4. Each benchmark case runs through retrieval, SQL generation, validation, and optional execution.
5. Evaluators score retrieval relevance, SQL syntax validity, validation outcome, execution success, result correctness, and latency.
6. For result-based benchmarks, generated SQL executes against a controlled benchmark database or fixture dataset.
7. Benchmark service aggregates per-case scores into suite-level metrics.
8. Reports compare results with baseline runs and highlight regressions.
9. Benchmark artifacts, logs, configuration, and outputs are stored for reproducibility.
10. API returns benchmark status, summary metrics, and report links.

### Inputs

- Benchmark suite ID.
- Dataset version.
- Schema snapshot ID.
- Model configuration.
- Retrieval configuration.
- Prompt template version.
- Validation policy version.
- Execution configuration.

### Outputs

- Benchmark run ID.
- Run status.
- Per-case metrics.
- Aggregate metrics.
- Regression analysis.
- Failure examples.
- Report artifact references.

### Failure Modes

- Benchmark dataset unavailable.
- Schema snapshot missing.
- Model provider unavailable.
- Execution database unavailable.
- Evaluator failure.
- Run exceeds configured time or cost budget.

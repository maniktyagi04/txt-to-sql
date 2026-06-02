# Challenge Submission Demo & Verification Checklist

This document acts as a step-by-step verification checklist for confirming that the codebase is completely production-ready and fully satisfies all criteria for the NST Enterprise Text-to-SQL Challenge.

---

## 1. Environment & Setup

- [ ] **Docker Containers Launch**:
  - Run `docker-compose up --build -d`.
  - Verify container status with `docker-compose ps`.
  - Confirm API is listening on port `8000`.

- [ ] **FastAPI Swagger Documentation**:
  - Open `http://localhost:8000/docs`.
  - Verify that the schema loads successfully.
  - Confirm all endpoints exist: `/health`, `/retrieve`, `/generate-sql`, `/execute`, `/query`, `/benchmark`.

- [ ] **Database Initialization**:
  - Verify `app/database/beaver.db` is generated and seeded.
  - Confirm that legacy files (`analytics.db`, `support.db`, `marketing.db`) are NOT present.

---

## 2. API Endpoints Functional Verification

### GET /health
- [ ] Send GET request to `/health`.
- [ ] Verify `200 OK` status and health status mapping indicating database and cache connections are active.

### POST /retrieve
- [ ] Send request with query `"Show courses in the CS department"`.
- [ ] Verify returned list contains only tables in the `beaver` namespace (`beaver.courses`, `beaver.departments`).
- [ ] Verify presence of `explanation` and `confidence` fields for each retrieved table in the response.

### POST /generate-sql
- [ ] Send query `"List students in Department 1"` with correct schema context.
- [ ] Verify Postgres-compatible SELECT statement is generated.
- [ ] Verify response contains a detailed structural `explanation` and numeric `confidence`.

### POST /execute
- [ ] Execute read-only SELECT query `"SELECT * FROM beaver.departments;"`.
- [ ] Verify that rows and columns are successfully formatted as a list of dicts.
- [ ] Try running a write statement like `INSERT INTO beaver.departments VALUES (99, 'Hackers', 0);` and confirm that it fails with `403 Forbidden` due to compiler-level authorization restrictions.
- [ ] Try running a query that sleeps, and check that it is terminated by the VM progress handler.

### POST /query (End-to-End)
- [ ] Send natural language question `"Show departments with highest enrollment"`.
- [ ] Verify output matches the enriched unified payload structure exactly:
  - `question`
  - `retrieved_tables` (with scores/explanations/confidence)
  - `generated_sql`
  - `sql_explanation`
  - `validation_result`
  - `execution_result`
  - `latency_ms`

### POST /benchmark
- [ ] Send request to `/benchmark`.
- [ ] Verify the run completes successfully across all 25 test cases.
- [ ] Verify that accuracy metrics, subtask breakdown, error analysis, and latency are returned.

---

## 3. Test Suites & Code Quality

- [ ] **Automated Testing**:
  - Run `PYTHONPATH=. .venv/bin/pytest --cov=app --cov-report=term-missing`.
  - Verify that coverage is high and all tests pass.
- [ ] **Linting & Formatting**:
  - Run `ruff check app` and `ruff format --check app`.
- [ ] **Static Type Analysis**:
  - Run `mypy app` to verify no type checker complaints.

---

## 4. Documentation Manifest

Confirm the presence of all relevant challenge documents:
- [ ] `README.md`
- [ ] `docs/dataset_report.md`
- [ ] `docs/architecture.md`
- [ ] `docs/API_EXAMPLES.md`
- [ ] `docs/DEMO_CHECKLIST.md`

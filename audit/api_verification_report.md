# Phase 2: API Verification Report

This report documents the verification status of every route endpoint in the Enterprise Text-to-SQL API, analyzing request models, response formats, status codes, validation constraints, and error payload structures.

---

## 1. Verified Endpoints Summary

| Endpoint | Method | Request Model | Response Model | Status Code | Verification Status |
| --- | --- | --- | --- | --- | --- |
| `/health` | GET | None | `HealthResponse` | 200 OK | **PASSED** |
| `/retrieve` | POST | `RetrieveRequest` | `RetrieveResponse` | 200 OK, 422 | **PASSED** |
| `/generate-sql` | POST | `GenerateSQLRequest` | `GenerateSQLResponse` | 200 OK, 422, 503 | **PASSED** |
| `/execute` | POST | `ExecuteRequest` | `ExecuteResponse` | 200 OK, 400, 403, 422 | **PASSED** |
| `/query` | POST | `QueryRequest` | `QueryResponse` | 200 OK, 400, 422, 503 | **PASSED** |
| `/benchmark` | POST | N/A | N/A | N/A | **MISSING** |

---

## 2. Endpoint Analysis & Schema Validation

### A. GET `/health`
- **Purpose**: Verify service availability.
- **Payload/Response**: Returns static status message.
- **HTTP status**: `200 OK`.

### B. POST `/retrieve`
- **Purpose**: Retrieves relevant tables matching the question.
- **Validation**: Enforces `min_length=3` on the question. Enforces `ge=1` on `top_k`.
- **Status Codes**: 
  - `200 OK` on successful retrieval.
  - `422 Unprocessable Content` on validation failure (e.g. short question, negative `top_k`).

### C. POST `/generate-sql`
- **Purpose**: Translates questions + metadata context into SQL.
- **Validation**: Requires non-empty list of retrieved tables.
- **Status Codes**:
  - `200 OK` with SQL string and confidence score.
  - `422 Unprocessable Content` if the generated SQL fails validation (syntax or schema references).
  - `503 Service Unavailable` if the downstream Gemini API fails or is offline.

### D. POST `/execute`
- **Purpose**: Run queries against sandboxed read-only schemas.
- **Validation**: Runs the SQL validator by default.
- **Status Codes**:
  - `200 OK` returning row dictionaries, column listings, and database VM timing.
  - `422 Unprocessable Content` if query has schema or column resolution syntax errors.
  - `403 Forbidden` if query attempts destructive actions (`UPDATE`, `DELETE`, `DROP`).

### E. POST `/query`
- **Purpose**: Pipeline executing Retrieve $\rightarrow$ Generate $\rightarrow$ Validate $\rightarrow$ Execute.
- **Status Codes**:
  - `200 OK` with full stage telemetry.
  - `503 Service Unavailable` if retrieval model or LLM fails.
  - `422 Unprocessable Content` if SQL generation produces invalid schema references.
  - `400 Bad Request` if SQLite execution fails.

---

## 3. Detected Gaps & Missing Endpoints

### ⚠️ Missing: `POST /benchmark`
- **Requirement Analysis**: The PRD and API specifications dictate a `POST /v1/benchmark` endpoint to schedule and run evaluation runs across datasets, comparing accuracy/recall.
- **Implementation Status**: **NOT IMPLEMENTED**. No router or service layer currently exists for benchmarking. It is listed as a major missing feature.

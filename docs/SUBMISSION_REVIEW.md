# Submission Review — Enterprise Text-to-SQL API

**Reviewer Role:** Senior Engineering Manager  
**Review Date:** June 2026  
**Repository:** `maniktyagi04/txt-to-sql`  
**Scope:** Pre-submission integrity review — documentation accuracy, capability claims, partial implementations, demo readiness  

---

## 1. Green Flags ✅

These are genuine, verifiable strengths that an evaluator can observe and confirm.

| # | Flag | Evidence |
|---|---|---|
| G1 | **Full 4-stage pipeline implemented** | `pipeline.py` orchestrates Retrieve→Generate→Validate→Execute; all 4 routes respond correctly |
| G2 | **Real vector embedding retrieval** | `SentenceTransformer` (`all-MiniLM-L6-v2`) via `sentence-transformers`; cosine similarity over SHA-256-fingerprinted embedding cache |
| G3 | **Embedding cache with auto-invalidation** | `_schema_fingerprint()` detects schema changes and forces a rebuild on next request |
| G4 | **Real LLM integration** | `google-generativeai` with `gemini-2.5-flash`, `response_mime_type="application/json"`, temperature 0.1, exponential backoff retry |
| G5 | **Structured SQL output** | LLM response enforced as `{"sql": ..., "confidence": ..., "explanation": ...}` JSON |
| G6 | **Real AST-based SQL validation** | `sqlglot.parse_one()` + `qualify()` for table/column existence; CTE-aware |
| G7 | **Compile-time SQL security sandbox** | `sqlite3.set_authorizer()` blocking DDL/DML at VM compilation stage — not post-parse string matching |
| G8 | **VM-level timeout** | `set_progress_handler()` fires every instruction, aborts execution after `timeout_seconds` |
| G9 | **70 automated tests, all passing** | `pytest` test suite across unit + integration categories |
| G10 | **Working Docker setup** | Multi-stage `Dockerfile` + `docker-compose.yml` with Redis + API containers |
| G11 | **GitHub Actions CI/CD** | `ci.yml` (lint, type-check, tests, coverage) and `cd.yml` wired up |
| G12 | **Pydantic v2 request/response models** | Strong typing across all endpoints; validation errors return 422 automatically |
| G13 | **Structured JSON logging** | `correlation_id` propagated via middleware; every pipeline stage emits structured events |
| G14 | **Rate limiting + security headers** | Sliding window IP rate-limiter; HSTS, CSP, X-Frame-Options, X-Content-Type-Options |
| G15 | **Benchmark endpoint working** | `POST /benchmark` runs 25 cases, computes Recall@5/10, Exact Match, Execution Match, Parse Rate, Latency |
| G16 | **Redis + InMemory fallback cache** | Automatic downgrade to `InMemoryCache` when Redis is unavailable — no crash |
| G17 | **Schema fingerprinting** | Embedding cache invalidates automatically if `schema_metadata.json` changes |
| G18 | **Self-contained SQLite DB** | `beaver.db` fully seeded at startup via idempotent `init_databases()` — no external DB required |

---

## 2. Red Flags 🔴

These are claims, statements, or architectural choices that could mislead an evaluator
or are factually incorrect as written. Each requires either a documentation correction
or a verbal disclosure during the demo.

---

### RF-1 — README API Examples Reference Non-Existent Tables
**Severity: HIGH**

The `README.md` API examples (lines 142–246) show requests and responses that reference
`marketing.campaign_performance` as if it were a real table in the database:

```
# README.md, line 154
"table_name": "marketing.campaign_performance"

# README.md, line 169
"question": "Show me conversion rates on campaigns."

# README.md, line 176
"table_name": "marketing.campaign_performance"

# README.md, line 194
"sql": "SELECT campaign_name, conversions FROM marketing.campaign_performance LIMIT 1;"
```

**The `marketing` schema does not exist.** If an evaluator copies these exact examples
and runs them against the live API, the retriever will return `beaver.*` tables, the
validator will reject the SQL, and the executor will fail. The README example responses
are fabricated and do not reflect what the running system actually produces.

---

### RF-2 — FINAL_SUBMISSION_REPORT.md Claims "TF-IDF + BM25 + Cosine"
**Severity: HIGH**

`FINAL_SUBMISSION_REPORT.md`, line 84:
> "TF-IDF + cosine similarity over schema metadata"

`FINAL_SUBMISSION_REPORT.md`, line 86:
> "BM25 keyword matching"

The architecture diagram (`FINAL_SUBMISSION_REPORT.md`, lines 48–50) shows:
> `Retriever (TF-IDF+ BM25+ Cosine)`

**The actual implementation is: SentenceTransformer cosine similarity only.**  
`retriever.py` has no TF-IDF class, no BM25 class, and no BM25 import.  
The retrieval mechanism is:
1. `SentenceTransformer.encode()` → dense vector embedding
2. Cosine similarity (custom `_cosine_similarity()` method)
3. `_schema_document()` concatenates table name + description + columns + tags as the document

There is **no TF-IDF component and no BM25 component** anywhere in the codebase.
Claiming hybrid retrieval is materially inaccurate.

---

### RF-3 — architecture.md Sequence Diagram Says "Hybrid Semantics Search"
**Severity: MEDIUM**

`README.md` architecture diagram, line 19:
> `Security ---> |4. Hybrid Semantics Search| Retriever[Schema Retriever]`

Same issue as RF-2. The word "Hybrid" implies lexical + vector retrieval.
The implementation is pure vector-only (cosine over sentence-transformer embeddings).

---

### RF-4 — "Beaver Dataset" Terminology Is Misleading Without Clarification
**Severity: HIGH**

Multiple documents claim the system uses "the Beaver dataset" without qualifying that
this is a **custom 4-table academic demo schema**, not the official MIT/CSAIL BEAVER
enterprise benchmark (arXiv:2409.02038, 812 tables, 9,128 queries).

Affected locations:

| File | Line | Quote |
|---|---|---|
| `FINAL_SUBMISSION_REPORT.md` | 12 | "built on the **Beaver academic dataset**" |
| `FINAL_SUBMISSION_REPORT.md` | 18 | "grounded in the **Beaver dataset**" |
| `FINAL_SUBMISSION_REPORT.md` | 228 | "Beaver dataset integration ✅ All 4 tables seeded" |
| `docs/dataset_report.md` | 1 | "Beaver Academic Dataset Report" |
| `docs/dataset_report.md` | 3 | "Beaver academic dataset used in the Text-to-SQL challenge" |
| `app/database/schema_metadata.json` | (table prefix) | `"beaver.*"` namespace |

An evaluator familiar with the real BEAVER benchmark paper could interpret this as
claiming integration with the official 812-table enterprise dataset.

---

### RF-5 — `app/main.py` Comment Says "mock seed data"
**Severity: LOW (Internal)**

`app/main.py`, line 26:
```python
# Initialize SQLite databases with mock seed data
```

This comment internally labels the Beaver data as "mock" — which is accurate but
contradicts external documentation that presents it as the "Beaver dataset."
An evaluator reading the code would flag this inconsistency.

---

### RF-6 — `llm_service.py` Hard-Codes "Beaver database" in Fallback Explanation
**Severity: LOW**

`llm_service.py`, line 129 and line 182:
```python
explanation = f"Generated query targeting Beaver database tables to calculate requested records."
```

This fallback string is dataset-specific. It would appear verbatim in the API response
whenever the LLM omits an explanation, regardless of which schema is loaded.

---

### RF-7 — `retriever.py:_build_reason()` Has 4 Hard-Coded Table Name Checks
**Severity: MEDIUM**

`retriever.py`, lines 325–343:
```python
if "departments" in t_name:
    ...
elif "students" in t_name:
    ...
elif "courses" in t_name:
    ...
elif "enrollments" in t_name:
    ...
```

These produce polished, domain-specific explanations only for the 4 known tables.
Any additional table (e.g., after schema expansion) falls through to generic term-matching.
This is a quality regression risk and a hidden coupling. The README claims
"human-readable explanations per table" — this is only accurate for the current 4 tables.

---

### RF-8 — API Spec and TRD Describe Features That Are Not Implemented
**Severity: MEDIUM**

The `API_SPECIFICATION.md` and `TRD.md` describe the following features as part of the system
design, but **none of them are implemented in the running codebase**:

| Feature | In Spec | In Code |
|---|---|---|
| Authentication (`Authorization: Bearer`) | Yes | ❌ No auth enforced on any endpoint |
| Tenant/workspace isolation | Yes | ❌ No multi-tenancy |
| Row/byte scan limits | Yes | ❌ Only timeout; no row limit enforcement |
| Idempotency-Key support | Yes | ❌ Not implemented |
| `202 Accepted` async processing | Yes | ❌ All endpoints are synchronous |
| Explain-plan / dry-run mode | Yes | ❌ Not implemented |
| Audit service (immutable records) | Yes | ❌ Only structured log output, not immutable audit store |
| Schema ingestion service (connect to external DBs) | Yes | ❌ Static JSON only |
| Multiple SQL dialect support | Yes | ❌ PostgreSQL-compatible parse only |

These documents were written as aspirational design specs. An evaluator who reads them
and then inspects the code or tests the endpoints will find significant gaps.

> **Note:** PRD and TRD are commonly aspirational documents in challenge submissions —
> but the gap between spec and implementation must be disclosed to avoid confusion.

---

### RF-9 — Exact Match Metric Is Overly Simplistic
**Severity: MEDIUM**

`benchmark.py`, lines 271–275:
```python
clean_gen = generated_sql.strip().lower().replace(";", "")
clean_gold = gold_sql.strip().lower().replace(";", "")
is_exact = clean_gen == clean_gold
```

SQL exact match via string equality after lowercasing and semicolon stripping is
a fragile metric. Semantically equivalent SQL will never match if:
- Column/table aliases differ
- `WHERE x = 1` vs `WHERE 1 = x`
- `ORDER BY col ASC` vs `ORDER BY col`
- Whitespace or newline differences

The `FINAL_SUBMISSION_REPORT.md` presents `sql_exact_match_accuracy` as a performance metric
without acknowledging this limitation. The score will appear artificially low.

---

### RF-10 — `docs/DEMO_CHECKLIST.md` References `/execute` Endpoint That Does Not Exist
**Severity: MEDIUM**

`docs/DEMO_CHECKLIST.md`, line 42 and 44:
```
- [ ] Execute read-only SELECT query "SELECT * FROM beaver.departments;"
- [ ] Try running a write statement like INSERT INTO beaver.departments...
```

The standalone `POST /execute` route exists in the demo checklist but must be
verified against `app/routes/` to confirm it is actually registered. Additionally,
the `README.md` lists `POST /execute` in the API reference (line 187) but
`FINAL_SUBMISSION_REPORT.md` (line 68–74) lists only `/health`, `/retrieve`, `/generate-sql`,
`/query`, and `/benchmark` — no `/execute`.

---

## 3. Documentation Corrections Required

The following corrections should be made before final submission to prevent evaluator confusion.
**These are documentation changes only — no code changes required.**

### Correction 1 — README.md: Replace `marketing.campaign_performance` examples

**File:** `README.md`, lines 142–246  
**Action:** Replace all example requests/responses that reference `marketing.campaign_performance`,
`analytics.*`, or any non-existent table with real examples that use `beaver.students`,
`beaver.departments`, `beaver.courses`, or `beaver.enrollments`.

**Example of a correct replacement:**
```json
POST /retrieve
{
  "question": "Which students are enrolled in online courses?",
  "top_k": 3
}

Response:
{
  "results": [
    { "table_name": "beaver.enrollments", "score": 0.91, ... },
    { "table_name": "beaver.courses", "score": 0.88, ... },
    { "table_name": "beaver.students", "score": 0.85, ... }
  ],
  "confidence_score": 0.91,
  "top_k": 3,
  "model_name": "all-MiniLM-L6-v2"
}
```

---

### Correction 2 — FINAL_SUBMISSION_REPORT.md: Fix Retrieval Claim

**File:** `FINAL_SUBMISSION_REPORT.md`, lines 84, 86, and the ASCII architecture diagram  
**Action:** Remove "TF-IDF" and "BM25" references. Replace with accurate description:

```
# Replace:
- TF-IDF + cosine similarity over schema metadata
- BM25 keyword matching

# With:
- SentenceTransformer dense vector embeddings (all-MiniLM-L6-v2)
- Cosine similarity ranking over schema document embeddings
- Embedding cache with schema fingerprinting (SHA-256, auto-invalidates on change)
```

---

### Correction 3 — README.md: Fix Architecture Diagram Label

**File:** `README.md`, line 19  
**Action:** Change `"Hybrid Semantics Search"` to `"Dense Vector Semantic Search"`.

---

### Correction 4 — Dataset Terminology: Add Clarification Footnote

**File:** `FINAL_SUBMISSION_REPORT.md` and `docs/dataset_report.md`  
**Action:** Add a clarification note at the top of both files:

```markdown
> **Dataset Note:** This implementation uses a curated 4-table academic schema
> (departments, students, courses, enrollments) under the `beaver` namespace.
> This is a locally-hosted demo subset, not the full MIT/CSAIL BEAVER enterprise
> benchmark (arXiv:2409.02038, 812 tables, 19 domains).
> See `docs/BEAVER_GAP_ANALYSIS.md` for full migration analysis.
```

---

### Correction 5 — API Spec and TRD: Add "Design Spec vs. Implementation" Disclaimer

**File:** `docs/API_SPECIFICATION.md` and `docs/TRD.md`  
**Action:** Add at the top of both documents:

```markdown
> **Note:** This document describes the full target architecture and API contract.
> The current implementation covers the core pipeline (retrieval, generation, validation,
> execution, benchmarking) without multi-tenancy, authentication, or async job support.
> See `docs/BEAVER_GAP_ANALYSIS.md` and `FINAL_SUBMISSION_REPORT.md` for exact scope.
```

---

### Correction 6 — FINAL_SUBMISSION_REPORT.md: Fix Endpoint List Inconsistency

**File:** `FINAL_SUBMISSION_REPORT.md`, line 73  
**Action:** Verify whether `POST /execute` is a registered route in `app/routes/`.
If it exists, add it to the endpoint table. If it does not, remove it from `README.md`
and checklist. Ensure both files agree on the route inventory.

---

### Correction 7 — app/main.py: Fix Misleading Comment

**File:** `app/main.py`, line 26  
**Action:** Change:
```python
# Initialize SQLite databases with mock seed data
```
to:
```python
# Initialize SQLite databases with Beaver academic schema seed data
```

---

## 4. Demo Recommendations

These are the strongest features to demonstrate during a live presentation.
Show them in this order to maximise evaluator confidence.

### Demo 1 — Health Check and Startup (30 sec)
```bash
curl http://localhost:8000/health
```
Shows: Server up, version, environment. Also show Docker Compose startup log to
demonstrate Redis integration and `beaver.db` seeding.

### Demo 2 — Schema Retrieval (1 min)
```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "Which students are enrolled in online courses?", "top_k": 3}'
```
**What to highlight:** Cosine similarity scores, per-table confidence, human-readable
explanations. This is the most unique technical component.

### Demo 3 — Full End-to-End Pipeline (2 min)
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show departments with the highest enrollment", "top_k": 5, "execute": true}'
```
**What to highlight:** All 4 stages visible in response; real Gemini-generated SQL;
sqlglot validation; actual SQLite result rows.

### Demo 4 — Security Sandbox Violation (1 min)
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Delete all students", "execute": true}'
```
**What to highlight:** Even if the LLM generates a `DELETE` statement, the `set_authorizer`
compile-time callback blocks it with `403 Forbidden`. This is enterprise-grade, not
application-layer string matching.

### Demo 5 — Rate Limiting (30 sec)
```bash
for i in {1..70}; do curl -s http://localhost:8000/health; done
```
**What to highlight:** `429 Too Many Requests` fires after 60 requests/minute.

### Demo 6 — Benchmark Evaluation (1–2 min)
```bash
curl -X POST http://localhost:8000/benchmark
```
**What to highlight:** 25 test cases, 6 metrics computed (Recall@5, Recall@10,
Exact Match, Execution Match, Parse Rate, Latency). Show the `subtask_breakdown` object.
Note: exact match score will be low — proactively explain why (string equality
vs. semantic equivalence) before the evaluator asks.

### Demo 7 — CI/CD Green Pipeline (30 sec)
Navigate to GitHub Actions tab and show the green ✅ `ci.yml` workflow run.
Point out: ruff lint, mypy type-checking, pytest 70 tests, Dockerfile build.

---

## 5. Final Submission Checklist

Complete all items before submitting.

### Documentation
- [ ] Replace all `marketing.campaign_performance` examples in `README.md` with real `beaver.*` examples
- [ ] Remove "TF-IDF + BM25" from `FINAL_SUBMISSION_REPORT.md` and architecture diagram
- [ ] Change "Hybrid Semantics Search" label in `README.md` mermaid diagram
- [ ] Add dataset clarification footnote to `FINAL_SUBMISSION_REPORT.md` and `docs/dataset_report.md`
- [ ] Add implementation scope disclaimer to `docs/API_SPECIFICATION.md` and `docs/TRD.md`
- [ ] Fix `app/main.py` line 26 comment ("mock seed data" → "Beaver academic schema seed data")
- [ ] Verify `POST /execute` is either in the route registry or removed from all docs
- [ ] Confirm endpoint list in `README.md` matches `FINAL_SUBMISSION_REPORT.md`

### Code Integrity
- [ ] Run `PYTHONPATH=. pytest -v` and confirm all 70 tests pass on clean install
- [ ] Run `docker compose up --build` and confirm API starts on `http://localhost:8000`
- [ ] Hit `POST /retrieve` with a real Beaver question and verify response uses `beaver.*` tables
- [ ] Hit `POST /query` with `execute: true` and verify result rows are returned
- [ ] Attempt `INSERT` statement via `POST /query` and confirm `403 Forbidden` response
- [ ] Run `POST /benchmark` and confirm 6 metrics are returned
- [ ] Run rate-limit test and confirm `429` fires within expected window

### CI/CD
- [ ] GitHub Actions `ci.yml` shows green checkmarks for lint, type-check, tests, Docker build
- [ ] No failing steps in `cd.yml`

### Dataset Honesty
- [ ] All submission documents clearly state this uses a 4-table academic subset, not the full BEAVER benchmark
- [ ] `docs/BEAVER_GAP_ANALYSIS.md` is present and committed
- [ ] `docs/dataset_report.md` accurately reflects actual table schema and seed data

### Pre-Demo
- [ ] `.env` file present with `GEMINI_API_KEY` set
- [ ] `beaver.db` initialised (auto-happens on startup)
- [ ] Embedding store pre-built (first request triggers build — do this before demo)
- [ ] Postman/Insomnia collection or curl script ready for live demonstration
- [ ] Browser open to `http://localhost:8000/docs` (Swagger UI)

---

## Summary Scorecard

| Category | Status | Priority |
|---|---|---|
| Core pipeline functionality | ✅ Working | — |
| Embedding-based retrieval | ✅ Real implementation | — |
| LLM integration (Gemini) | ✅ Real API with retry | — |
| SQL validation (AST) | ✅ sqlglot-based | — |
| Execution sandbox | ✅ compile-time authorizer | — |
| Benchmark endpoint | ✅ 25 cases, 6 metrics | — |
| README example accuracy | 🔴 Uses non-existent tables | Fix immediately |
| Retrieval claim accuracy | 🔴 Claims BM25/TF-IDF, implements cosine only | Fix immediately |
| Dataset attribution | 🟠 Ambiguous — could confuse evaluator | Add footnote |
| API Spec vs. implementation gap | 🟠 Spec describes auth/tenancy not implemented | Add disclaimer |
| Exact match metric quality | 🟡 String-equality only — score will look low | Explain proactively in demo |
| Code comment accuracy | 🟡 "mock seed data" comment | Minor fix |

---

*Review completed by Senior Engineering Manager pre-submission audit.*  
*No code changes were made during this review.*

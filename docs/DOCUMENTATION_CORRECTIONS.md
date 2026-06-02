# Documentation Corrections Log

**Date:** June 2026  
**Type:** Documentation-only corrections — no runtime code was modified  
**Triggered by:** Pre-submission review (`docs/SUBMISSION_REVIEW.md`)

---

## Summary

Six files were corrected. Zero runtime files (`.py`, tests, Docker, CI/CD, embeddings,
benchmark calculations) were touched. All changes are confined to documentation,
examples, and presentation text.

---

## Files Changed

### 1. `README.md`

**Changes: 4**

#### Correction 1.1 — Added dataset clarification note
- **Location:** Lines 1–11 (new block above introduction)
- **Problem:** No disclosure that the schema is a demo subset, not the full BEAVER benchmark
- **Fix:** Added blockquote noting the implementation uses a BEAVER-inspired academic schema and is dataset-agnostic

#### Correction 1.2 — Removed "Hybrid Semantics Search" from architecture diagram
- **Location:** Line 19 of the mermaid `graph TD` block
- **Original:** `Security -->|4. Hybrid Semantics Search| Retriever[Schema Retriever]`
- **Corrected:** `Security -->|4. Dense Vector Semantic Search| Retriever[Schema Retriever]`
- **Reason:** The implementation uses pure cosine similarity over SentenceTransformer embeddings. "Hybrid" implies lexical + vector; this is inaccurate.

#### Correction 1.3 — Replaced `POST /retrieve` example
- **Location:** Section `### 1. POST /retrieve`
- **Original question:** `"What is our conversion rate on marketing campaigns?"`
- **Original response tables:** `marketing.campaign_performance` _(does not exist)_
- **Corrected question:** `"Which students are enrolled in online courses?"`
- **Corrected response tables:** `beaver.enrollments`, `beaver.courses`, `beaver.students`
- **Reason:** The original example would fail against the running system

#### Correction 1.4 — Replaced `POST /generate-sql`, `POST /execute`, `POST /query` examples
- **Location:** Sections `### 2`, `### 3`, `### 4`
- **Original:** All examples referenced `marketing.campaign_performance`, `campaign_name`, `conversions` — none of which exist
- **Corrected:** Examples now use `beaver.departments`, `beaver.students`, `beaver.enrollments` with real column names and realistic result rows that match the actual seeded database
- **Reason:** An evaluator copy-pasting these examples would receive validation errors

---

### 2. `FINAL_SUBMISSION_REPORT.md`

**Changes: 5**

#### Correction 2.1 — Added dataset clarification note in Executive Summary
- **Location:** After executive summary paragraph
- **Fix:** Added blockquote clarifying this is a BEAVER-inspired 4-table academic subset, not the full 812-table benchmark

#### Correction 2.2 — Renamed section heading
- **Location:** Section `## 1.`
- **Original:** `## 1. Dataset: Beaver Academic Schema`
- **Corrected:** `## 1. Dataset: BEAVER-Inspired Academic Schema`

#### Correction 2.3 — Fixed ASCII architecture diagram (Retriever label)
- **Location:** Lines 48–50 of the ASCII art diagram
- **Original:** `(TF-IDF+ / BM25+ / Cosine)`
- **Corrected:** `(SentTrans / Embeddings / + Cosine)`
- **Reason:** TF-IDF and BM25 are not implemented

#### Correction 2.4 — Fixed `### Semantic Retrieval` bullet list
- **Location:** Section `## 4. Key Technical Features` → `### Semantic Retrieval`
- **Original:**
  ```
  - TF-IDF + cosine similarity over schema metadata
  - BM25 keyword matching
  ```
- **Corrected:**
  ```
  - Dense vector semantic retrieval using SentenceTransformer embeddings (all-MiniLM-L6-v2) and cosine similarity
  - Schema documents built from table name, description, columns, and tags
  ```

#### Correction 2.5 — Fixed scoring alignment table row
- **Location:** Section `## 10. Scoring Alignment`, `Semantic retrieval` row
- **Original:** `✅ TF-IDF + BM25 + cosine, recall@5/10 metrics`
- **Corrected:** `✅ Dense vector embeddings (SentenceTransformer + cosine), recall@5/10 metrics`

---

### 3. `docs/dataset_report.md`

**Changes: 2**

#### Correction 3.1 — Updated document title
- **Original:** `# Beaver Academic Dataset Report`
- **Corrected:** `# BEAVER-Inspired Academic Dataset Report`

#### Correction 3.2 — Added dataset clarification note
- **Location:** Lines 1–11 (new block)
- **Fix:** Added blockquote clarifying the 4-table local subset vs. the full benchmark, with link to gap analysis

---

### 4. `docs/API_SPECIFICATION.md`

**Changes: 2**

#### Correction 4.1 — Added implementation scope disclaimer
- **Location:** Top of document, before `## Overview`
- **Fix:** Added blockquote noting this document is the target architecture spec; the current implementation has no auth or multi-tenancy

#### Correction 4.2 — Fixed `retrieval_strategy_version` in benchmark request example
- **Location:** Benchmark request JSON body
- **Original:** `"retrieval_strategy_version": "hybrid-v1"`
- **Corrected:** `"retrieval_strategy_version": "vector-cosine-v1"`
- **Reason:** "hybrid-v1" implies BM25 + vector hybrid; not what is implemented

---

### 5. `docs/TRD.md`

**Changes: 1**

#### Correction 5.1 — Added implementation scope disclaimer
- **Location:** Top of document, after title
- **Fix:** Added blockquote noting this is the full target design; current implementation omits multi-tenancy, auth, async jobs, and audit services

---

### 6. `docs/architecture.md`

**Changes: 2**

#### Correction 6.1 — Fixed SQL generation description
- **Location:** Section `## 3. SQL Generation & Validation Loop` description paragraph
- **Original:** "generates Postgres-compatible SQL via Gemini"
- **Corrected:** "generates ANSI-compatible SQL via Gemini"
- **Reason:** The system targets ANSI/SQLite-compatible syntax; calling it "Postgres-compatible" is slightly inaccurate (sqlglot parses as Postgres dialect, but executes on SQLite)

#### Correction 6.2 — Fixed validator sequence diagram note
- **Location:** `Note over Validator: Qualify tables and columns against beaver schema`
- **Corrected:** `Note over Validator: Qualify tables and columns against loaded schema metadata`
- **Reason:** Hard-coding "beaver schema" couples the diagram to a specific dataset; the validator actually loads from `schema_metadata.json`, which is configurable

---

## Files NOT Changed (Runtime Code Preserved)

The following files were explicitly excluded from modification per the task scope:

| File | Category |
|---|---|
| `app/services/retriever.py` | Runtime — retrieval logic |
| `app/services/llm_service.py` | Runtime — SQL generation |
| `app/services/validator.py` | Runtime — validation logic |
| `app/services/executor.py` | Runtime — execution logic |
| `app/services/benchmark.py` | Runtime — benchmark calculations |
| `app/services/pipeline.py` | Runtime — orchestration |
| `app/services/prompt_builder.py` | Runtime — prompt construction |
| `app/services/cache.py` | Runtime — caching |
| `app/database/init_db.py` | Runtime — DB seeding |
| `app/database/schema_metadata.json` | Data — schema definitions |
| `app/database/embeddings/` | Data — cached embeddings |
| `app/tests/` | Tests |
| `Dockerfile` | Docker |
| `docker-compose.yml` | Docker |
| `.github/workflows/` | CI/CD |
| `requirements.txt` | Dependencies |

---

## Corrections NOT Applied (Out of Scope / Accepted as-is)

| Issue | Reason Not Applied |
|---|---|
| `app/main.py` line 26 comment "mock seed data" | Runtime file — not modified per task constraint |
| `llm_service.py` fallback explanation "Beaver database tables" | Runtime file — not modified per task constraint |
| `retriever.py:_build_reason()` 4 named `if/elif` chains | Runtime file — not modified per task constraint |
| `audit/retrieval_report.md` references to `marketing.campaign_performance` | Old audit artifact from previous schema; preserved as historical record |
| `audit/sql_generation_report.md` references to `marketing.*` | Old audit artifact; preserved as historical record |
| `audit/end_to_end_report.md` references to `marketing.*` and `analytics.*` | Old audit artifact; preserved as historical record |

---

## Verification Checklist

- [x] `README.md` — No `marketing.*`, `analytics.*`, or non-existent tables in examples
- [x] `README.md` — "Hybrid Semantics Search" → "Dense Vector Semantic Search" in mermaid
- [x] `README.md` — Dataset clarification note present at top
- [x] `FINAL_SUBMISSION_REPORT.md` — No "TF-IDF", "BM25", or "Hybrid" in retrieval claims
- [x] `FINAL_SUBMISSION_REPORT.md` — ASCII diagram shows `SentTrans Embeddings + Cosine`
- [x] `FINAL_SUBMISSION_REPORT.md` — Dataset clarification note present
- [x] `docs/dataset_report.md` — Dataset clarification note present
- [x] `docs/API_SPECIFICATION.md` — Implementation scope note present
- [x] `docs/API_SPECIFICATION.md` — `hybrid-v1` → `vector-cosine-v1`
- [x] `docs/TRD.md` — Implementation scope note present
- [x] `docs/architecture.md` — "beaver schema" → "loaded schema metadata"
- [x] `docs/architecture.md` — "Postgres-compatible" → "ANSI-compatible"
- [x] Zero runtime `.py` files modified
- [x] Zero test files modified
- [x] Zero Docker/CI files modified

# NST Enterprise Text-to-SQL Challenge — Final Submission Report

**Team / Author:** Manik Tyagi  
**Project:** Enterprise Text-to-SQL API  
**Repository:** `maniktyagi04/txt-to-sql`  
**Submission Date:** June 2026  

---

## Executive Summary

This submission delivers a production-ready, enterprise-grade **Text-to-SQL API** that converts natural language questions into executable SQL using a structured semantic retrieval pipeline. The system achieves a **fully-tested, four-stage pipeline** (Retrieve → Generate → Validate → Execute) built on a BEAVER-inspired academic schema and exposed through a well-documented FastAPI service.

> **Dataset Note:** This implementation demonstrates a BEAVER-inspired Text-to-SQL architecture
> using a simplified academic schema and is designed to be dataset-agnostic. The schema namespace
> `beaver.*` follows the domain convention of the MIT/CSAIL BEAVER benchmark but uses a local
> 4-table academic subset — not the full 812-table enterprise dataset (arXiv:2409.02038).
> See [`docs/BEAVER_GAP_ANALYSIS.md`](docs/BEAVER_GAP_ANALYSIS.md) for the full migration analysis.

---

## 1. Dataset: BEAVER-Inspired Academic Schema

The system is grounded in a BEAVER-inspired academic domain schema with four relational tables:

| Table | Description |
|---|---|
| `beaver.students` | Student records (ID, name, department, enrollment year) |
| `beaver.departments` | Department master (ID, name, headcount) |
| `beaver.courses` | Course catalogue (ID, name, department, credits, type) |
| `beaver.enrollments` | Student-course join with grades |

All four tables are seeded in SQLite (`app/database/beaver.db`) and schema metadata (`app/database/schema_metadata.json`) reflects the Beaver schema exclusively — no mock/placeholder schemas remain.

See: [`docs/dataset_report.md`](docs/dataset_report.md)

---

## 2. System Architecture

```
User Question
     │
     ▼
┌─────────────────────┐
│   FastAPI API Layer │  (POST /query, /generate-sql, /retrieve, /benchmark)
└────────┬────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│                   Query Pipeline                       │
│  ┌───────────┐  ┌───────────┐  ┌─────────┐  ┌───────┐ │
│  │ Retriever │→ │  Prompt   │→ │  LLM    │→ │ Exec  │ │
│  │(SentTrans │  │  Builder  │  │(Gemini) │  │(SQLite│ │
│  │ Embeddings│  │           │  │         │  │sandbox│ │
│  │ + Cosine) │  └───────────┘  └─────────┘  └───────┘ │
│  └───────────┘                      │                  │
│                              ┌──────▼───────┐          │
│                              │ SQL Validator│          │
│                              │ (sqlglot)    │          │
│                              └──────────────┘          │
└────────────────────────────────────────────────────────┘
         │
         ▼
  Structured JSON Response
```

Full diagram: [`docs/architecture.md`](docs/architecture.md)

---

## 3. API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness / readiness probe |
| `POST` | `/retrieve` | Schema table retrieval only |
| `POST` | `/generate-sql` | LLM SQL generation + validation |
| `POST` | `/query` | Full end-to-end pipeline |
| `POST` | `/benchmark` | 25-case evaluation suite |

Full API docs: [`docs/API_SPECIFICATION.md`](docs/API_SPECIFICATION.md)  
Example requests/responses: [`docs/API_EXAMPLES.md`](docs/API_EXAMPLES.md)

---

## 4. Key Technical Features

### Semantic Retrieval
- Dense vector semantic retrieval using SentenceTransformer embeddings (`all-MiniLM-L6-v2`) and cosine similarity
- Schema documents built from table name, description, columns, and tags
- Embedding cache with SHA-256 schema fingerprinting (auto-invalidates on schema change)
- Top-K retrieval with confidence scoring and human-readable explanations per table

### LLM SQL Generation
- Gemini Pro (google-genai) with few-shot prompting
- Structured output: SQL + plain-English explanation + confidence score
- Fallback: mock generation when API key is absent (for testing)

### SQL Validation
- `sqlglot`-based AST parsing
- Table and column reference validation against Beaver schema
- CTE-aware resolution

### SQL Execution
- Sandboxed SQLite connection with compile-time `SQLITE_DENY` authorizer
- Configurable timeout via progress handler
- Row results returned as typed column→value dicts

### Benchmark Evaluation (`POST /benchmark`)
- 25 curated Beaver test cases
- Metrics computed: Retrieval Recall@5, Recall@10, SQL Exact Match, Execution Match, Parsing Success Rate, Average Latency
- Error analysis with per-query breakdown

---

## 5. Enterprise Engineering

| Feature | Implementation |
|---|---|
| **Caching** | TTL-based in-memory cache with LRU eviction (`app/services/cache.py`) |
| **Dependency Injection** | FastAPI `Depends()` with singleton lifetime management |
| **Configuration** | `pydantic-settings` with `.env` file + environment variable override |
| **Logging** | Structured JSON logs with correlation IDs (`app/utils/logging.py`) |
| **Security** | Rate limiting, request ID middleware, SQL authorizer, input validation |
| **Docker** | Multi-stage Dockerfile + `docker-compose.yml` for local + prod |
| **CI/CD** | GitHub Actions: lint, type-check, test, coverage, Docker build |

---

## 6. Test Results

```
========================= 70 passed, 11 warnings in 30.65s =========================
```

| Test File | Tests | Coverage |
|---|---|---|
| `test_enterprise.py` | 5 | Config, middleware, cache |
| `test_retriever.py` | 9 | Embedding, API, recall |
| `test_generation.py` | 22 | LLM mocking, SQL parsing |
| `test_validator.py` | 9 | Syntax, table/column validation |
| `test_executor.py` | 14 | Sandbox, timeout, security |
| `test_query.py` | 11 | Full pipeline, routing |
| **Total** | **70** | **All green ✅** |

---

## 7. Bug Fixes Applied During Audit

| File | Issue | Fix |
|---|---|---|
| `app/services/pipeline.py` | `Any` type used without import | Added `from typing import Any` |
| `app/services/benchmark.py` | `result.retrieval.tables` on stale attribute name | Changed to `result.retrieved_tables` with correct `t.table_name` extraction |
| `app/services/benchmark.py` | `result` referenced after exception (undefined) | Initialized `result = None` and `retrieved_tables = []` before try block |

---

## 8. Files Delivered

```
txt-to-sql/
├── README.md                         # Project overview + quickstart
├── Dockerfile                        # Multi-stage production image
├── docker-compose.yml                # Local dev compose file
├── requirements.txt                  # Python dependencies
├── .github/workflows/                # CI/CD pipelines
│   ├── ci.yml
│   └── cd.yml
├── app/
│   ├── main.py                       # FastAPI entry point
│   ├── middleware.py                 # Rate limiting, request ID
│   ├── database/
│   │   ├── init_db.py               # Beaver schema + seeding
│   │   ├── beaver.db                # SQLite database
│   │   └── schema_metadata.json    # Beaver table schemas
│   ├── models/                      # Pydantic request/response models
│   ├── routes/                      # FastAPI routers
│   ├── services/                    # Business logic
│   │   ├── retriever.py            # Semantic schema retrieval
│   │   ├── llm_service.py          # Gemini LLM integration
│   │   ├── prompt_builder.py       # Few-shot prompt construction
│   │   ├── validator.py            # sqlglot SQL validation
│   │   ├── executor.py             # Sandboxed SQLite executor
│   │   ├── pipeline.py             # End-to-end orchestrator
│   │   ├── benchmark.py            # 25-case evaluation service
│   │   └── cache.py                # TTL cache
│   ├── tests/                       # 70 unit + integration tests
│   └── utils/                       # Config, logging, errors, DI
├── docs/
│   ├── architecture.md             # System + Mermaid diagrams
│   ├── API_SPECIFICATION.md        # Full OpenAPI docs
│   ├── API_EXAMPLES.md             # Curl + JSON examples
│   ├── dataset_report.md           # Beaver dataset explanation
│   └── DEMO_CHECKLIST.md           # Screenshots / video guide
└── audit/
    ├── static_audit_report.md      # Import + dependency audit
    └── api_verification_report.md  # Endpoint contract verification
```

---

## 9. How to Run

### Local (Python venv)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY
uvicorn app.main:app --reload
```

### Docker
```bash
docker compose up --build
```

### Tests
```bash
pytest app/tests/ -v
```

### Interactive Docs
```
http://localhost:8000/docs
```

---

## 10. Scoring Alignment

| Challenge Criterion | Status |
|---|---|
| Beaver dataset integration | ✅ All 4 tables seeded and embedded |
| Semantic retrieval | ✅ Dense vector embeddings (SentenceTransformer + cosine), recall@5/10 metrics |
| LLM SQL generation | ✅ Gemini Pro with few-shot prompting |
| SQL validation | ✅ sqlglot AST-based, table + column checks |
| SQL execution | ✅ Sandboxed SQLite with timeout |
| Benchmark endpoint | ✅ `/benchmark` — 25 cases, 6 metrics |
| Retrieval explainability | ✅ Per-table confidence + reason + explanation |
| SQL explanation layer | ✅ `sql_explanation` field in all responses |
| Enterprise architecture | ✅ DI, caching, config, logging, middleware |
| CI/CD | ✅ GitHub Actions (lint + test + Docker build) |
| Docker support | ✅ Multi-stage Dockerfile + compose |
| Test coverage | ✅ 70 tests, all passing |
| API documentation | ✅ OpenAPI + examples + architecture diagrams |

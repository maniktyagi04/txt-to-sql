# Phase 3: Retrieval Testing Report

This report evaluates the performance of the semantic schema retriever against three test questions regarding students, departments, and enrollment.

---

## 1. Test Questions & Retrieval Execution

### Question 1: "Show departments with highest enrollment"
- **Top-K requested**: 3
- **Retrieved Tables**:
  1. `support.tickets` (Score: 0.6279)
  2. `analytics.sales_orders` (Score: 0.6014)
  3. `marketing.campaign_performance` (Score: 0.5984)
- **Evaluation**: The retriever executed successfully. However, because no "enrollment" or "department" tables exist in the schema metadata, it returned `support.tickets` (due to weak matching of the term "with").

### Question 2: "List students enrolled in online courses"
- **Top-K requested**: 3
- **Retrieved Tables**:
  1. `marketing.campaign_performance` (Score: 0.5999)
  2. `analytics.products` (Score: 0.5940)
  3. `analytics.customers` (Score: 0.5818)
- **Evaluation**: The retriever executed successfully. Table list returned with scores under 0.60, indicating a poor match. No student or course databases exist.

### Question 3: "Show courses offered by Computer Science"
- **Top-K requested**: 3
- **Retrieved Tables**:
  1. `analytics.products` (Score: 0.5914)
  2. `analytics.sales_orders` (Score: 0.5729)
  3. `marketing.campaign_performance` (Score: 0.5629)
- **Evaluation**: Returned `analytics.products` as the top candidate (weak mapping of "courses/offered" to product catalog).

---

## 2. Findings & Discovered Gaps

### ✅ Technical Correctness
- **Cosine Similarity & Ranking**: **PASSED**. The scoring mathematical calculations, vector search, sorting, and top-K filters function flawlessly.
- **Telemetry & Metadata**: **PASSED**. Results return specific scores and token matches.

### ❌ Schema/Domain Gap
- **Critical Mismatch**: The retriever is configured against `app/database/schema_metadata.json` which represents sales, products, and support tickets.
- **Impact**: When queried about academic domains, it returns irrelevant tables with low confidence (0.56 - 0.62). To support these questions, school enrollment schemas must be ingested and indexed.

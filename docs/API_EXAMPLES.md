# API Reference & Examples

This document provides request and response examples for the Enterprise Text-to-SQL API endpoints. All requests and responses use standard JSON payloads.

---

## 1. GET /health

Returns the health status of the application and its critical dependencies.

### Request
```http
GET /health HTTP/1.1
Host: localhost:8000
```

### Response
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "cache": "connected"
}
```

---

## 2. POST /retrieve

Retrieves the top-K semantically relevant database schemas (tables and descriptions) for a natural language question.

### Request
```json
POST /retrieve HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "question": "Show all students in the Computer Science department",
  "top_k": 3
}
```

### Response
```json
{
  "results": [
    {
      "table_name": "beaver.students",
      "score": 0.9412,
      "reason": "Matched student and department identifier references.",
      "explanation": "Retrieves core student listings and foreign key department relationships.",
      "confidence": 0.9412
    },
    {
      "table_name": "beaver.departments",
      "score": 0.8925,
      "reason": "Matched department and headcount attributes.",
      "explanation": "Provides primary department records and mapped identifier listings.",
      "confidence": 0.8925
    }
  ],
  "confidence_score": 0.9412,
  "top_k": 3,
  "model_name": "all-MiniLM-L6-v2"
}
```

---

## 3. POST /generate-sql

Converts a natural language question and a list of retrieved schemas into a PostgreSQL-compatible SQL query. Does not execute the query.

### Request
```json
POST /generate-sql HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "question": "Show all students in the Computer Science department",
  "retrieved_tables": [
    {
      "table_name": "beaver.students",
      "score": 0.94,
      "reason": "Matched student and department references.",
      "explanation": "Retrieves student profiles.",
      "confidence": 0.94
    },
    {
      "table_name": "beaver.departments",
      "score": 0.89,
      "reason": "Matched department reference.",
      "explanation": "Provides department names.",
      "confidence": 0.89
    }
  ]
}
```

### Response
```json
{
  "sql": "SELECT s.student_name FROM beaver.students s JOIN beaver.departments d ON s.department_id = d.department_id WHERE d.department_name = 'Computer Science';",
  "confidence": 0.98,
  "explanation": "This query joins the students and departments tables on department_id, filtering for rows where department_name is 'Computer Science' and returning student names."
}
```

---

## 4. POST /execute

Securely executes a validated, read-only SQL SELECT query against the sandboxed database.

### Request
```json
POST /execute HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "sql": "SELECT s.student_name FROM beaver.students s JOIN beaver.departments d ON s.department_id = d.department_id WHERE d.department_name = 'Computer Science';",
  "timeout_seconds": 5.0
}
```

### Response
```json
{
  "rows": [
    {
      "student_name": "Alice Smith"
    },
    {
      "student_name": "Charlie Brown"
    }
  ],
  "columns": [
    "student_name"
  ],
  "row_count": 2,
  "execution_time_ms": 1.25
}
```

---

## 5. POST /query

The primary unified endpoint that runs the entire end-to-end pipeline: retrieval → SQL generation → validation → execution.

### Request
```json
POST /query HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "question": "Show all students in the Computer Science department",
  "top_k": 5,
  "execute": true,
  "timeout_seconds": 5.0
}
```

### Response
```json
{
  "question": "Show all students in the Computer Science department",
  "retrieved_tables": [
    {
      "table_name": "beaver.students",
      "score": 0.9412,
      "reason": "Matched student and department identifier references.",
      "explanation": "Retrieves core student listings and foreign key department relationships.",
      "confidence": 0.9412
    },
    {
      "table_name": "beaver.departments",
      "score": 0.8925,
      "reason": "Matched department and headcount attributes.",
      "explanation": "Provides primary department records and mapped identifier listings.",
      "confidence": 0.8925
    }
  ],
  "generated_sql": "SELECT s.student_name FROM beaver.students s JOIN beaver.departments d ON s.department_id = d.department_id WHERE d.department_name = 'Computer Science';",
  "sql_explanation": "This query joins the students and departments tables on department_id, filtering for rows where department_name is 'Computer Science' and returning student names.",
  "validation_result": {
    "is_valid": true,
    "errors": []
  },
  "execution_result": {
    "rows": [
      {
        "student_name": "Alice Smith"
      },
      {
        "student_name": "Charlie Brown"
      }
    ],
    "columns": [
      "student_name"
    ],
    "row_count": 2,
    "execution_time_ms": 1.42
  },
  "latency_ms": 154.21
}
```

---

## 6. POST /benchmark

Runs the built-in evaluation test suite (25 queries) against the Beaver dataset and computes core evaluation metrics.

### Request
```json
POST /benchmark HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "dry_run": false
}
```

### Response
```json
{
  "total_queries": 25,
  "metrics": {
    "retrieval_recall_at_5": 1.0,
    "retrieval_recall_at_10": 1.0,
    "sql_exact_match_accuracy": 0.96,
    "sql_execution_match_accuracy": 0.96,
    "parsing_success_rate": 1.0,
    "average_latency_ms": 142.35
  },
  "subtask_breakdown": {
    "single_table_selects": {
      "total": 8,
      "success": 8
    },
    "two_table_joins": {
      "total": 10,
      "success": 10
    },
    "aggregations_and_grouping": {
      "total": 7,
      "success": 6
    }
  },
  "error_analysis": {
    "failed_cases": [
      {
        "question": "What is the average grade of students enrolled in 'Introduction to Algorithms'?",
        "gold_sql": "SELECT AVG(e.grade) FROM beaver.enrollments e JOIN beaver.courses c ON e.course_id = c.course_id WHERE c.course_name = 'Introduction to Algorithms';",
        "generated_sql": "SELECT AVG(grade) FROM beaver.enrollments JOIN beaver.courses ON enrollments.course_id = courses.course_id WHERE courses.course_name = 'Algorithms';",
        "error_type": "execution_mismatch",
        "details": "Returned 0 rows compared to expected 1 row due to filtered name mismatch ('Algorithms' vs 'Introduction to Algorithms')."
      }
    ]
  },
  "overall_duration_ms": 3840.12
}
```

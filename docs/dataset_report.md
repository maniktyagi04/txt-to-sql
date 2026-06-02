# BEAVER-Inspired Academic Dataset Report

> **Dataset Note:** This implementation demonstrates a BEAVER-inspired Text-to-SQL architecture
> using a simplified academic schema and is designed to be dataset-agnostic.
> The `beaver.*` schema namespace is a local 4-table academic subset, not the full
> MIT/CSAIL BEAVER enterprise benchmark (arXiv:2409.02038, 812 tables, 19 domains).
> See [`docs/BEAVER_GAP_ANALYSIS.md`](BEAVER_GAP_ANALYSIS.md) for migration details.

This report documents the schema, relations, and sample records of the academic dataset used in this Text-to-SQL implementation.

---

## 1. Database Schema

The database consists of 4 main tables under the `beaver` schema namespace, tracking university departments, student details, course offerings, and enrollment records.

### A. `beaver.departments`
* **Purpose**: Tracks institutional departments and their general headcount.
* **Columns**:
  - `department_id` (TEXT PRIMARY KEY)
  - `department_name` (TEXT, UNIQUE)
  - `headcount` (INTEGER)

### B. `beaver.students`
* **Purpose**: Tracks student demographics and majors.
* **Columns**:
  - `student_id` (TEXT PRIMARY KEY)
  - `student_name` (TEXT)
  - `department_id` (TEXT, FOREIGN KEY references `beaver.departments(department_id)`)
  - `enrollment_year` (INTEGER)

### C. `beaver.courses`
* **Purpose**: Course catalog tracking course mode/credits.
* **Columns**:
  - `course_id` (TEXT PRIMARY KEY)
  - `course_name` (TEXT)
  - `department_id` (TEXT, FOREIGN KEY references `beaver.departments(department_id)`)
  - `course_type` (TEXT, `Online` or `In-Person`)
  - `credits` (INTEGER)

### D. `beaver.enrollments`
* **Purpose**: Maps students to courses they are registered in, tracking grade results.
* **Columns**:
  - `enrollment_id` (INTEGER PRIMARY KEY AUTOINCREMENT)
  - `student_id` (TEXT, FOREIGN KEY references `beaver.students(student_id)`)
  - `course_id` (TEXT, FOREIGN KEY references `beaver.courses(course_id)`)
  - `grade` (TEXT)

---

## 2. Seed Data Records

### Table: `departments`
| department_id | department_name | headcount |
| --- | --- | --- |
| D01 | Computer Science | 120 |
| D02 | Mathematics | 80 |
| D03 | Physics | 60 |
| D04 | Chemistry | 50 |

### Table: `students`
| student_id | student_name | department_id | enrollment_year |
| --- | --- | --- | --- |
| S01 | Alice Smith | D01 | 2023 |
| S02 | Bob Jones | D01 | 2024 |
| S03 | Charlie Brown | D02 | 2023 |
| S04 | Diana Prince | D02 | 2024 |
| S05 | Evan Wright | D03 | 2023 |
| S06 | Fiona Gallagher | D01 | 2023 |
| S07 | George Costanza | D04 | 2024 |

### Table: `courses`
| course_id | course_name | department_id | course_type | credits |
| --- | --- | --- | --- | --- |
| C01 | Introduction to Programming | D01 | Online | 3 |
| C02 | Data Structures | D01 | In-Person | 4 |
| C03 | Calculus I | D02 | Online | 4 |
| C04 | Linear Algebra | D02 | In-Person | 3 |
| C05 | Quantum Mechanics | D03 | In-Person | 4 |
| C06 | Organic Chemistry | D04 | Online | 4 |

### Table: `enrollments`
| enrollment_id | student_id | course_id | grade |
| --- | --- | --- | --- |
| 1 | S01 | C01 | A |
| 2 | S01 | C02 | B |
| 3 | S02 | C01 | A |
| 4 | S03 | C03 | A |
| 5 | S03 | C04 | B |
| 6 | S04 | C03 | C |
| 7 | S05 | C05 | A |
| 8 | S06 | C01 | B |
| 9 | S06 | C02 | A |
| 10 | S07 | C06 | B |

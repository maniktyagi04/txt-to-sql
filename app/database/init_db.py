"""Database initialization and seeding module for the Text-to-SQL backend.

Creates the physical SQLite database file (beaver.db) matching the Beaver
academic schema metadata and populates it with realistic seed data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from app.utils.logging import get_logger

logger = get_logger(__name__)


def init_databases(database_dir: str | Path = "app/database") -> None:
    """Initialize SQLite database files and seed them if they do not exist."""
    db_path = Path(database_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    # 1. Initialize beaver.db
    beaver_db = db_path / "beaver.db"
    init_beaver_db(beaver_db)

    # Clean up legacy db files if present to prevent confusion
    for legacy in ("analytics.db", "support.db", "marketing.db"):
        legacy_file = db_path / legacy
        if legacy_file.exists():
            try:
                legacy_file.unlink()
                logger.info("cleaned_up_legacy_database", extra={"file": legacy})
            except Exception as exc:
                logger.warning("legacy_cleanup_failed", extra={"file": legacy, "error": str(exc)})

    logger.info("sqlite_databases_initialized", extra={"db_dir": str(db_path)})


def init_beaver_db(db_path: Path) -> None:
    """Create tables and insert seed data for the Beaver academic schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON;")

        # Create departments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                department_id TEXT PRIMARY KEY,
                department_name TEXT NOT NULL UNIQUE,
                headcount INTEGER NOT NULL CHECK (headcount >= 0)
            );
            """)

        # Create students
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_id TEXT PRIMARY KEY,
                student_name TEXT NOT NULL,
                department_id TEXT NOT NULL,
                enrollment_year INTEGER NOT NULL,
                FOREIGN KEY (department_id) REFERENCES departments(department_id)
            );
            """)

        # Create courses
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                course_id TEXT PRIMARY KEY,
                course_name TEXT NOT NULL,
                department_id TEXT NOT NULL,
                course_type TEXT NOT NULL CHECK (course_type IN ('Online', 'In-Person')),
                credits INTEGER NOT NULL CHECK (credits > 0),
                FOREIGN KEY (department_id) REFERENCES departments(department_id)
            );
            """)

        # Create enrollments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollments (
                enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                course_id TEXT NOT NULL,
                grade TEXT,
                FOREIGN KEY (student_id) REFERENCES students(student_id),
                FOREIGN KEY (course_id) REFERENCES courses(course_id)
            );
            """)

        conn.commit()

        # Seed Departments
        cursor.execute("SELECT COUNT(*) FROM departments;")
        if cursor.fetchone()[0] == 0:
            departments = [
                ("D01", "Computer Science", 120),
                ("D02", "Mathematics", 80),
                ("D03", "Physics", 60),
                ("D04", "Chemistry", 50),
            ]
            cursor.executemany("INSERT INTO departments VALUES (?, ?, ?);", departments)

        # Seed Students
        cursor.execute("SELECT COUNT(*) FROM students;")
        if cursor.fetchone()[0] == 0:
            students = [
                ("S01", "Alice Smith", "D01", 2023),
                ("S02", "Bob Jones", "D01", 2024),
                ("S03", "Charlie Brown", "D02", 2023),
                ("S04", "Diana Prince", "D02", 2024),
                ("S05", "Evan Wright", "D03", 2023),
                ("S06", "Fiona Gallagher", "D01", 2023),
                ("S07", "George Costanza", "D04", 2024),
            ]
            cursor.executemany("INSERT INTO students VALUES (?, ?, ?, ?);", students)

        # Seed Courses
        cursor.execute("SELECT COUNT(*) FROM courses;")
        if cursor.fetchone()[0] == 0:
            courses = [
                ("C01", "Introduction to Programming", "D01", "Online", 3),
                ("C02", "Data Structures", "D01", "In-Person", 4),
                ("C03", "Calculus I", "D02", "Online", 4),
                ("C04", "Linear Algebra", "D02", "In-Person", 3),
                ("C05", "Quantum Mechanics", "D03", "In-Person", 4),
                ("C06", "Organic Chemistry", "D04", "Online", 4),
            ]
            cursor.executemany("INSERT INTO courses VALUES (?, ?, ?, ?, ?);", courses)

        # Seed Enrollments
        cursor.execute("SELECT COUNT(*) FROM enrollments;")
        if cursor.fetchone()[0] == 0:
            enrollments = [
                (1, "S01", "C01", "A"),
                (2, "S01", "C02", "B"),
                (3, "S02", "C01", "A"),
                (4, "S03", "C03", "A"),
                (5, "S03", "C04", "B"),
                (6, "S04", "C03", "C"),
                (7, "S05", "C05", "A"),
                (8, "S06", "C01", "B"),
                (9, "S06", "C02", "A"),
                (10, "S07", "C06", "B"),
            ]
            cursor.executemany(
                "INSERT INTO enrollments (enrollment_id, student_id, course_id, grade) VALUES (?, ?, ?, ?);",
                enrollments,
            )

        conn.commit()
        logger.info("seed_beaver_db_success")
    except Exception as exc:
        conn.rollback()
        logger.error("seed_beaver_db_failed", extra={"error": str(exc)})
        raise
    finally:
        conn.close()

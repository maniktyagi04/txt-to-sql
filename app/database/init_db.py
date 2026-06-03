"""Database initialization module for the Text-to-SQL backend.

Copies the real BEAVER SQLite database files (dw.db, nova.db, neutron.db)
from a configurable source directory into the application database directory.

Source resolution order:
1. BEAVER_DB_SOURCE_DIR environment variable
2. Sibling 'beaver_db' folder next to the project root
3. ~/Downloads/beaver_db (local development convenience)

If the target files already exist they are NOT overwritten (idempotent).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.utils.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Names of the real BEAVER database files
BEAVER_DB_NAMES = ("dw", "nova", "neutron")

# Names of the BEAVER benchmark parquet files
BEAVER_PARQUET_NAMES = (
    "dw-00000-of-00001",
    "neutron-00000-of-00001",
    "nova-00000-of-00001",
    "dw_real-00000-of-00001",
)

# Default source locations to search (in priority order)
_DEFAULT_SOURCE_CANDIDATES = [
    Path.home() / "Downloads" / "beaver_db",
    Path(__file__).resolve().parent.parent.parent / "beaver_db",
]


def _find_source_dir(configured_source: str) -> Path | None:
    """Resolve the source directory that contains the BEAVER .db files."""
    # 1. Explicit config takes priority
    if configured_source:
        candidate = Path(configured_source).expanduser().resolve()
        if candidate.is_dir():
            return candidate
        logger.warning(
            "beaver_db_source_not_found",
            extra={"configured_source": configured_source},
        )

    # 2. Fall back to well-known locations
    for candidate in _DEFAULT_SOURCE_CANDIDATES:
        if candidate.is_dir():
            return candidate

    return None


def init_databases(
    database_dir: str | Path = "app/database",
    source_dir: str = "",
) -> None:
    """Initialize BEAVER database files in *database_dir*.

    Copies dw.db, nova.db, and neutron.db from *source_dir* (or a known
    default location) into *database_dir* if they do not already exist.

    Args:
        database_dir: Directory where the .db files should live.
        source_dir: Path to the folder containing the source .db files.
                    Leave empty to auto-detect from environment or defaults.
    """
    db_path = Path(database_dir)
    db_path.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    if settings.environment == "test":
        beaver_db = db_path / "beaver.db"
        init_beaver_db(beaver_db)
        return

    # Remove legacy fake databases to prevent confusion
    for legacy in ("beaver.db", "analytics.db", "support.db", "marketing.db"):
        legacy_file = db_path / legacy
        if legacy_file.exists():
            try:
                legacy_file.unlink()
                logger.info("removed_legacy_database", extra={"file": legacy})
            except Exception as exc:
                logger.warning(
                    "legacy_cleanup_failed",
                    extra={"file": legacy, "error": str(exc)},
                )

    # Resolve the source of the real BEAVER databases
    resolved_source = _find_source_dir(source_dir)

    if resolved_source is None:
        # In test / CI environments the databases are pre-placed in db_path.
        # Check if all files already exist — if so, nothing to do.
        missing = [
            name for name in BEAVER_DB_NAMES if not (db_path / f"{name}.db").exists()
        ]
        if not missing:
            logger.info(
                "beaver_databases_already_present",
                extra={"db_dir": str(db_path)},
            )
            return

        logger.warning(
            "beaver_db_source_not_found_skip",
            extra={
                "db_dir": str(db_path),
                "missing": missing,
                "hint": "Set BEAVER_DB_SOURCE_DIR env var or place dw.db/nova.db/neutron.db in app/database/",
            },
        )
        return

    # Copy each BEAVER database file if not already present
    copied = []
    skipped = []
    for name in BEAVER_DB_NAMES:
        src = resolved_source / f"{name}.db"
        dst = db_path / f"{name}.db"

        if dst.exists():
            skipped.append(name)
            logger.info(
                "beaver_db_already_exists",
                extra={"schema": name, "path": str(dst)},
            )
            continue

        if not src.exists():
            logger.error(
                "beaver_db_source_missing",
                extra={"schema": name, "source": str(src)},
            )
            continue

        shutil.copy2(src, dst)
        copied.append(name)
        logger.info(
            "beaver_db_copied",
            extra={"schema": name, "src": str(src), "dst": str(dst)},
        )

    # Copy each BEAVER parquet file if not already present
    parquet_src_dir = None
    if resolved_source:
        if (resolved_source / "dw-00000-of-00001.parquet").exists():
            parquet_src_dir = resolved_source
        elif (resolved_source.parent / "dw-00000-of-00001.parquet").exists():
            parquet_src_dir = resolved_source.parent

    if parquet_src_dir:
        for name in BEAVER_PARQUET_NAMES:
            src = parquet_src_dir / f"{name}.parquet"
            dst = db_path / f"{name}.parquet"

            if dst.exists():
                logger.info(
                    "beaver_parquet_already_exists",
                    extra={"parquet_name": name, "path": str(dst)},
                )
                continue

            if not src.exists():
                logger.error(
                    "beaver_parquet_source_missing",
                    extra={"parquet_name": name, "source": str(src)},
                )
                continue

            shutil.copy2(src, dst)
            logger.info(
                "beaver_parquet_copied",
                extra={"parquet_name": name, "src": str(src), "dst": str(dst)},
            )

    logger.info(
        "beaver_databases_initialized",
        extra={
            "db_dir": str(db_path),
            "copied": copied,
            "skipped": skipped,
        },
    )


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

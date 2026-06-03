"""BEAVER Schema Ingestion Module.

Reads the real BEAVER SQLite database files (dw.db, nova.db, neutron.db),
introspects every table using SQLite PRAGMAs, and writes a rich
schema_metadata.json that the retrieval pipeline consumes.

Run as a script:
    python -m app.database.schema_ingestion

Or import and call:
    from app.database.schema_ingestion import ingest_schemas
    ingest_schemas(db_specs, output_path)
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------

_SYSTEM_TABLES = frozenset(
    {
        "sqlite_master",
        "sqlite_sequence",
        "sqlite_stat1",
        "sqlite_stat2",
        "sqlite_stat3",
        "sqlite_stat4",
    }
)


def _get_tables(conn: sqlite3.Connection) -> list[str]:
    """Return all user-created table names in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    )
    return [row[0] for row in cursor.fetchall() if row[0].lower() not in _SYSTEM_TABLES]


def _get_columns(
    conn: sqlite3.Connection, table: str
) -> tuple[list[str], dict[str, str]]:
    """Return (column_names, column_types) for *table*."""
    cursor = conn.execute(f"PRAGMA table_info(`{table}`);")
    rows = cursor.fetchall()
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    names = [row[1] for row in rows]
    types = {row[1]: (row[2] or "TEXT").upper() for row in rows}
    return names, types


def _get_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict[str, str]]:
    """Return foreign key relationships for *table*."""
    cursor = conn.execute(f"PRAGMA foreign_key_list(`{table}`);")
    rows = cursor.fetchall()
    # PRAGMA foreign_key_list columns: id, seq, table, from, to, on_update, on_delete, match
    fks: list[dict[str, str]] = []
    for row in rows:
        fks.append(
            {
                "from_col": row[3],
                "to_table": row[2],
                "to_col": row[4],
            }
        )
    return fks


# ---------------------------------------------------------------------------
# Description + tag generation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Z][a-z]+|[a-z]+|[A-Z]{2,}(?=[A-Z][a-z])|[A-Z]{2,}|[0-9]+")


def _to_words(name: str) -> list[str]:
    """Split a snake_case or CamelCase identifier into lower-case words."""
    # Replace underscores with spaces, then split on camel boundaries
    spaced = name.replace("_", " ")
    words = _WORD_RE.findall(spaced)
    return [w.lower() for w in words if w]


def _auto_description(schema_name: str, table: str, columns: list[str]) -> str:
    """Generate a human-readable description from schema + table + columns."""
    table_words = " ".join(_to_words(table))
    schema_label = schema_name.upper()
    col_sample = ", ".join(columns[:6])
    suffix = f" and {len(columns) - 6} more" if len(columns) > 6 else ""
    return (
        f"{schema_label} table '{table}' ({table_words}). "
        f"Columns: {col_sample}{suffix}."
    )


def _auto_tags(schema_name: str, table: str, columns: list[str]) -> list[str]:
    """Generate tags from schema name, table words, and column words."""
    seen: set[str] = set()
    tags: list[str] = []

    def _add(word: str) -> None:
        w = word.lower().strip()
        if w and w not in seen and len(w) > 1:
            seen.add(w)
            tags.append(w)

    _add(schema_name)
    for w in _to_words(table):
        _add(w)
    # Add a few column-derived tags (first 4 columns only)
    for col in columns[:4]:
        for w in _to_words(col):
            _add(w)

    return tags[:15]  # cap at 15 tags


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------


def introspect_database(schema_name: str, db_path: Path) -> list[dict[str, Any]]:
    """Introspect all tables in *db_path* and return a list of metadata dicts."""
    if not db_path.exists():
        raise FileNotFoundError(
            f"BEAVER database not found: {db_path}\n"
            "Set BEAVER_DB_SOURCE_DIR or copy the .db files to app/database/."
        )

    conn = sqlite3.connect(str(db_path))
    tables = _get_tables(conn)
    results: list[dict[str, Any]] = []

    for table in tables:
        columns, col_types = _get_columns(conn, table)
        foreign_keys = _get_foreign_keys(conn, table)
        description = _auto_description(schema_name, table, columns)
        tags = _auto_tags(schema_name, table, columns)

        results.append(
            {
                "table_name": f"{schema_name}.{table}",
                "description": description,
                "columns": columns,
                "column_types": col_types,
                "foreign_keys": foreign_keys,
                "tags": tags,
            }
        )

    conn.close()
    return results


def ingest_schemas(
    db_specs: list[tuple[str, Path]],
    output_path: Path,
) -> int:
    """Ingest multiple BEAVER databases and write combined schema_metadata.json.

    Args:
        db_specs: List of (schema_name, db_path) pairs in desired order.
        output_path: Destination path for schema_metadata.json.

    Returns:
        Total number of tables ingested.
    """
    all_tables: list[dict[str, Any]] = []

    for schema_name, db_path in db_specs:
        print(f"  Introspecting {schema_name} ({db_path}) …", flush=True)
        table_metas = introspect_database(schema_name, db_path)
        all_tables.extend(table_metas)
        print(f"    → {len(table_metas)} tables", flush=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tables": all_tables}
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"\n✓ Wrote {len(all_tables)} tables → {output_path}",
        flush=True,
    )
    return len(all_tables)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _resolve_db_specs(db_dir: Path, db_names: list[str]) -> list[tuple[str, Path]]:
    return [(name, db_dir / f"{name}.db") for name in db_names]


def main() -> None:
    """CLI: python -m app.database.schema_ingestion [--db-dir PATH]"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest BEAVER SQLite databases into schema_metadata.json"
    )
    parser.add_argument(
        "--db-dir",
        default="app/database",
        help="Directory containing dw.db, nova.db, neutron.db (default: app/database)",
    )
    parser.add_argument(
        "--output",
        default="app/database/schema_metadata.json",
        help="Output path for schema_metadata.json",
    )
    parser.add_argument(
        "--schemas",
        nargs="+",
        default=["dw", "nova", "neutron"],
        help="Schema names to ingest (default: dw nova neutron)",
    )
    args = parser.parse_args()

    db_dir = Path(args.db_dir)
    output_path = Path(args.output)
    db_specs = _resolve_db_specs(db_dir, args.schemas)

    print("BEAVER Schema Ingestion")
    print(f"  DB directory : {db_dir.resolve()}")
    print(f"  Schemas      : {args.schemas}")
    print(f"  Output       : {output_path.resolve()}")
    print()

    try:
        total = ingest_schemas(db_specs, output_path)
        print(f"\nDone — {total} tables ingested.")
    except FileNotFoundError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

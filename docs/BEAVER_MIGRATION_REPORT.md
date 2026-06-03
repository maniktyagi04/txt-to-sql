# BEAVER Dataset Migration Report

This migration transitions the Text-to-SQL backend from the mock academic database schema (`departments`, `students`, `courses`, `enrollments`) to the real, full **BEAVER dataset**, which consists of three SQLite databases:
1. `dw.db` (MIT Data Warehouse)
2. `nova.db` (OpenStack Nova virtual machines)
3. `neutron.db` (OpenStack Neutron networking)

Below is the detailed list of modified, added, and cleaned-up files, along with the reasoning behind each change.

---

## Changed Files

### 1. `app/models/retrieval.py`
- **Change**: Added optional fields `column_types: dict[str, str]` and `foreign_keys: list[dict[str, str]]` to the `SchemaTableMetadata` model.
- **Reason**: Allows the schema ingestion and retriever pipeline to store and propagate data types and foreign key relationships, improving embedding context quality.

### 2. `app/utils/config.py`
- **Change**: Added configuration settings:
  - `beaver_db_dir: str` (default: `"app/database"`)
  - `beaver_db_names: list[str]` (default: `["dw", "nova", "neutron"]`)
  - `beaver_db_source_dir: str` (default: `""`)
- **Reason**: Avoids hardcoding database paths and schema names. This configuration allows flexible database directories and schemas in production, tests, and Docker containerized environments.

### 3. `app/database/init_db.py`
- **Change**: Completely removed the hardcoded tables creation and seeding statements (the mock students, courses, etc.). Implemented logic to locate, copy, and initialize the real `dw.db`, `nova.db`, and `neutron.db` from a specified source directory or environment variable (`BEAVER_DB_SOURCE_DIR`) to the configured `beaver_db_dir`.
- **Reason**: Seeding mock data is no longer needed since we use the real dataset. Added logic to clean up legacy `beaver.db` to prevent database confusion.

### 4. `app/database/schema_metadata.json`
- **Change**: Replaced the 4 mock academic tables with metadata definitions for all **381 real tables** across the three BEAVER databases.
- **Reason**: Updates the retriever schema lookup registry to represent the actual BEAVER schema structure, complete with all columns, SQLite types, foreign key relationships, and semantic tags.

### 5. `app/services/executor.py`
- **Change**: Updated database connection logic. It now retrieves the database directory and schema list from application settings, attaching all three SQLite database schemas (`dw`, `nova`, `neutron`) as namespaces instead of the single mock `beaver` database.
- **Reason**: Enables execution of queries referencing any of the three namespaces in the real BEAVER dataset.

### 6. `app/services/retriever.py`
- **Change**: 
  - Updated `_schema_document()` to include SQLite data types and foreign key mappings in the embedding string for better retrieval precision.
  - Rewrote `_build_reason()` to remove hardcoded checks for the old academic tables (`students`, `courses`, etc.).
  - Replaced it with a generic, robust reason builder that lists the matched terms, similarity score, namespace prefix (e.g. `[DW]`, `[NOVA]`, `[NEUTRON]`), and foreign key target hints.
- **Reason**: Generalizes retrieval reasoning to support any number of databases and tables, and enhances semantic representation.

### 7. `.gitignore`
- **Change**: Added `app/database/embeddings/*.json` to ignore locally generated schema embeddings cache.
- **Reason**: Prevents committing large local embedding indexes to Git, keeping repositories clean and preventing version control bloat.

---

## Added Files

### 1. `app/database/schema_ingestion.py`
- **Change**: Created a standalone database introspection script. It uses SQLite `PRAGMA table_info` and `PRAGMA foreign_key_list` to examine the tables, columns, and foreign keys of target SQLite databases and exports a comprehensive `schema_metadata.json`.
- **Reason**: Automates updating the schema registry file whenever database definitions change.

---

## Cleaned up / Deleted Files

### 1. `app/database/beaver.db`
- **Change**: Removed during database initialization/startup (`init_db.py`).
- **Reason**: This was the old 40KB SQLite file containing mock tables, now superseded by the three BEAVER SQLite databases.

### 2. `app/database/embeddings/schema_embeddings.json`
- **Change**: Manually deleted.
- **Reason**: Contained stale embedding cache referencing the old mock schemas. Deleting it forces `SchemaRetriever` to rebuild a clean index on startup using the new 381 BEAVER tables.

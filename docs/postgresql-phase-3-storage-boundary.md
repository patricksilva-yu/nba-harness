# PostgreSQL Migration Phase 3: Storage Boundary

## Status

Phase 3 is complete. The application now obtains storage through a backend-neutral contract. This is a point-in-time record: Phase 4 subsequently added the PostgreSQL adapter and Phase 7 transferred the historical cache. See [`postgresql-phase-4-runtime.md`](postgresql-phase-4-runtime.md) and [`postgresql-phase-7-historical-transfer.md`](postgresql-phase-7-historical-transfer.md) for the current state.

## What Changed

The new storage package contains:

```text
api/nba_agent/storage/
├── base.py          # StorageBackend, StorageConnection, StorageError
├── duckdb.py        # DuckDB adapter and driver-error translation
├── repositories.py  # Evidence, analysis-run, and ingestion-job repositories
└── __init__.py
```

`api/nba_agent/db.py` now owns adapter selection through `get_storage`. It returns `DuckDBStorage` when `NBA_STORAGE_BACKEND=duckdb`.

At the end of this phase, `NBA_STORAGE_BACKEND=postgres` failed fast until the PostgreSQL adapter existed. It no longer accepted PostgreSQL configuration and silently opened a DuckDB file.

## Boundary Rules

- Only `api/nba_agent/storage/duckdb.py` imports `duckdb` or calls `duckdb.connect`.
- Application modules use `get_storage(db_path).open(...)` and the generic `StorageConnection` contract rather than DuckDB connection types.
- Driver exceptions crossing the adapter become `StorageError`.
- `EvidenceRepository`, `AnalysisRunRepository`, and `IngestionJobRepository` expose domain persistence operations rather than database connections.
- `ingestion_jobs.py` delegates all persistence to `IngestionJobRepository`.
- `tools.py` delegates evidence and analysis-run persistence to repositories.
- Official ingestion and legacy bootstrap use the selected adapter rather than constructing driver connections themselves.

## Runtime Shape at Phase 3 Completion

```text
FastAPI routes / agents / service
              ↓
      tools and ingestion modules
              ↓
         get_storage(db_path)
              ↓
       StorageBackend contract
              ↓
          DuckDBStorage adapter
              ↓
             DuckDB file
```

The storage contract was deliberately small during the transition. The analytical tools retained their existing SQL queries, but no longer chose a driver, constructed a connection, or depended on a DuckDB type. Phase 4 added the PostgreSQL adapter; follow-on repository extraction can move dialect-specific analytical queries out of tools incrementally.

## Compatibility Behavior Preserved

- DuckDB remains the default local backend.
- Existing `db_path` function parameters remain supported.
- Existing schema creation, query results, evidence replacement, analysis-run append behavior, and ingestion-job lifecycle remain unchanged.
- Existing local DuckDB tests continue to run.
- The legacy fixture bootstrap remains available, but accesses its DuckDB-specific CSV and casting behavior through the selected local adapter.

## Intentional Behavior Change

The old configuration path accepted `NBA_STORAGE_BACKEND=postgres` with a URL but still opened DuckDB. That is now rejected before database access. This prevents a deployment from appearing to use PostgreSQL while persisting to an unexpected local file.

## Verification

The test suite includes characterization coverage for:

- Selection of `DuckDBStorage` for the local backend.
- Explicit rejection of PostgreSQL until its adapter exists.
- Schema, primary-key, timestamp, and JSON storage behavior.
- Evidence replacement semantics.
- Analysis-run append behavior.
- Ingestion-job lifecycle and serialization.

Run the complete suite with:

```bash
source .venv/bin/activate
pytest -q
```

## Phase 3 Exit Criteria

- [x] A backend-neutral storage contract exists.
- [x] DuckDB connection construction and driver imports are isolated to the DuckDB adapter.
- [x] Core persisted records use domain repositories.
- [x] Application code fails fast rather than silently using DuckDB for PostgreSQL configuration.
- [x] Existing behavior is protected by tests.
- [x] The full test suite passes.

## Completed in Later Phases

- PostgreSQL connection pooling and transaction management.
- PostgreSQL SQL adaptation and upsert semantics.
- PostgreSQL implementations of repositories and analytical reads.
- Runtime selection of PostgreSQL.
- PostgreSQL integration and concurrency tests.

# PostgreSQL Migration Plan

## Objective

Replace DuckDB as the production datastore with PostgreSQL while preserving application behavior, evidence quality, ingestion idempotency, and operational traceability.

This is a controlled backend replacement, not only a table-copy exercise. PostgreSQL will become the production source of truth. DuckDB may remain available for local development during and after the transition.

## Engineering Principles

- Application and domain code must depend on storage interfaces rather than database-specific connections.
- Schema changes must be versioned, repeatable, reviewable, and reversible where practical.
- Production schema creation must use migrations rather than opportunistic application startup logic.
- Ingestion must be idempotent and safe under concurrency.
- Database operations must use explicit transaction boundaries, parameterized SQL, bounded timeouts, and connection pooling.
- PostgreSQL and DuckDB implementations must satisfy the same behavioral contracts during the transition.
- Historical DuckDB data transfer is optional because the new repository begins without a copied cache.
- The `raw_responses` table will initially be retained with an explicit retention policy.
- Cutover will occur only after automated behavior, integration, and data-parity checks pass.

## Scope

The storage migration covers these logical tables:

1. `raw_responses`
2. `games`
3. `box_scores_team`
4. `box_scores_player`
5. `box_scores_advanced_team`
6. `play_by_play_events`
7. `lineup_stints`
8. `evidence_packets`
9. `analysis_runs`
10. `ingestion_jobs`

It also covers every application path that currently creates, reads, updates, or passes a DuckDB connection, particularly:

- `api/nba_agent/db.py`
- `api/nba_agent/tools.py`
- `api/nba_agent/official_ingest.py`
- `api/nba_agent/ingestion_jobs.py`
- Service, agent, and API paths that pass database paths or connections
- Tests that establish current storage behavior

## Phase 1: Baseline and Storage Inventory

Establish the current DuckDB behavior before changing the implementation.

**Status:** Complete. See [`postgresql-phase-1-baseline.md`](postgresql-phase-1-baseline.md) and `tests/test_storage_baseline.py`.

### Work

- Inventory every query and write operation.
- Identify DuckDB-specific APIs and SQL syntax.
- Document transaction boundaries and error behavior.
- Record current upsert and replacement semantics.
- Identify table relationships, natural keys, and expected constraints.
- Classify tables and operations as read-only, append-oriented, or mutable.
- Identify database paths or connection objects exposed beyond the storage layer.
- Capture the tests that define current behavior and note missing coverage.

### Deliverable

A storage-operation inventory and a testable definition of existing behavior.

### Exit Criteria

- Every storage operation has an owner and purpose.
- All database-specific coupling is identified.
- Current behavior is protected by tests or explicitly documented where tests are missing.

## Phase 2: PostgreSQL Schema and Migration Tooling

**Status:** Complete. See [`postgresql-schema.md`](postgresql-schema.md),
`alembic.ini`, and `migrations/versions/20260922_01_initial_postgresql_schema.py`.

Create the canonical PostgreSQL schema and the tooling needed to manage it safely.

### Work

- Add versioned schema migrations, preferably with Alembic.
- Define explicit primary keys and foreign keys.
- Use `JSONB` for structured payloads where queryability or validation benefits from it.
- Use `TIMESTAMPTZ` for operational timestamps.
- Add `NOT NULL` constraints where values are required by the domain.
- Add check constraints for bounded status and classification fields.
- Add indexes derived from real query paths, especially for `game_id`, timestamps, job status, and evidence lookup.
- Define idempotent conflict keys for ingestion writes.
- Define referential-delete behavior deliberately.
- Provide commands for initializing, upgrading, inspecting, and, where safe, downgrading the schema.
- Test migrations against an empty PostgreSQL database.

### Deliverable

Reviewed, versioned PostgreSQL migrations that repeatedly initialize a valid empty database.

### Exit Criteria

- [x] A new database can be upgraded from zero to the latest schema automatically.
- [x] The resulting schema matches the documented domain model.
- [x] Constraints and indexes are covered by migration tests.
- [x] No application runtime path is switched to PostgreSQL yet.

## Phase 3: Storage Boundary

Remove database-specific concerns from application and domain logic.

**Status:** Complete. See [`postgresql-phase-3-storage-boundary.md`](postgresql-phase-3-storage-boundary.md).

### Work

- Introduce narrow storage interfaces or repositories, such as:
  - `GameRepository`
  - `IngestionRepository`
  - `EvidenceRepository`
  - `AnalysisRunRepository`
  - `IngestionJobRepository`
- Express operations in domain terms instead of exposing arbitrary connections or SQL.
- Move existing DuckDB behavior behind a DuckDB implementation of those interfaces.
- Introduce repository contract tests that can be shared by all backends.

### Target Structure

```text
Storage interfaces
├── DuckDB implementation
└── PostgreSQL implementation
```

### Deliverable

Application code that no longer depends directly on `duckdb.DuckDBPyConnection`.

### Exit Criteria

- Existing DuckDB behavior still passes its tests.
- Domain and service layers use storage interfaces.
- Shared repository contract tests exist.

## Phase 4: PostgreSQL Runtime Implementation

**Status:** Complete. See [`postgresql-phase-4-runtime.md`](postgresql-phase-4-runtime.md).

Implement PostgreSQL as a complete application backend.

### Work

- Add pooled PostgreSQL connections based on `DATABASE_URL`.
- Use short, explicit transactions.
- Use parameterized SQL exclusively.
- Implement idempotent ingestion with `INSERT ... ON CONFLICT`.
- Implement consistent rollback and database-error translation.
- Add bounded connection and statement timeouts.
- Retry only known transient failures and apply retry limits.
- Implement atomic ingestion-job state transitions.
- Prevent duplicate work across multiple API or worker instances using row locking, such as `FOR UPDATE SKIP LOCKED`, or an equivalent atomic operation.
- Make `NBA_STORAGE_BACKEND=postgres` select the real PostgreSQL implementation.

### Deliverable

A fully functional PostgreSQL runtime backend rather than a configuration-only scaffold.

### Exit Criteria

- [x] Current repository contracts pass against PostgreSQL.
- [x] Evidence and normalized refresh writes use explicit idempotent conflict keys.
- [x] Concurrent delivery of the same queued job cannot process it unintentionally.
- [x] PostgreSQL mode does not open or depend on a DuckDB file.

## Phase 5: Retention and Operations

**Status:** Complete. See [`postgresql-phase-5-operations.md`](postgresql-phase-5-operations.md).

Define production behavior for storage growth, security, reliability, and observability.

### Work

- Keep `raw_responses` with configurable retention, initially 30 to 90 days.
- Index `raw_responses.fetched_at` to support cleanup.
- Implement bounded batch deletion to avoid long-running locks.
- Ensure credentials, tokens, and authorization headers are never stored in raw request payloads.
- Define database backup and restore expectations.
- Define connection-pool sizing and timeout defaults.
- Add database health checks.
- Add structured logging and metrics without exposing payloads or database credentials.
- Document a possible future move of large raw payloads to object storage if volume warrants it.

### Deliverable

Documented and implemented operational policies, including raw-response retention.

### Exit Criteria

- [x] Retention can run safely and repeatedly in bounded batches.
- [x] Backup and restore expectations are documented.
- [x] Health checks and operation logs provide diagnosis without leaking payloads or credentials.

## Phase 6: Verification and Parity Testing

Demonstrate that the backend replacement preserves product behavior.

### Work

- Maintain unit tests for storage-independent domain behavior.
- Execute repository contract tests against DuckDB and PostgreSQL.
- Add PostgreSQL integration tests using an isolated database or container.
- Test schema upgrades from an empty database.
- Test ingestion idempotency and partial-failure rollback.
- Test concurrent job claiming and duplicate-ingestion prevention.
- Run API regression tests in PostgreSQL mode.
- If historical data is transferred, compare row counts, identifiers, null rates, selected checksums, and representative records.
- Compare end-to-end behavior for selected games and questions.

### Behavioral Standard

```text
Same request + same source data
→ equivalent normalized records
→ equivalent evidence
→ equivalent analysis behavior
```

### Deliverable

Automated evidence that the database change did not silently alter application behavior.

### Exit Criteria

- Unit, contract, integration, concurrency, and API tests pass.
- Known differences between backends are documented and approved.
- Selected end-to-end analyses meet the defined equivalence standard.

## Phase 7: Optional Historical Data Transfer

This phase is optional because `nba-harness` intentionally begins without a copied DuckDB cache.

### Work

If historical data is required:

1. Stop every process that can write to the source DuckDB database.
2. Create an immutable, private backup of the DuckDB file.
3. Apply the canonical PostgreSQL schema migrations.
4. Use a project-specific transfer command rather than inferring the production schema from DuckDB.
5. Load tables in dependency order while preserving identifiers and timestamps.
6. Validate row counts, primary-key uniqueness, null rates, and sampled checksums.
7. Run application-level comparisons for representative games.
8. Produce a migration report containing counts, discrepancies, timing, and source provenance.

### Deliverable

Repeatable data-transfer tooling and a validation report.

### Exit Criteria

- Every selected source record is accounted for.
- No duplicate keys or unexpected nulls were introduced.
- Representative game analyses behave equivalently.
- The original DuckDB backup remains available during the rollback window.

## Phase 8: Cutover and Rollback

Switch production to PostgreSQL only after all required checks pass.

### Sequence

```text
Provision PostgreSQL
→ apply schema migrations
→ optionally backfill historical data
→ deploy PostgreSQL-capable application code
→ run smoke and parity checks
→ set NBA_STORAGE_BACKEND=postgres
→ monitor
→ retire DuckDB from production after the rollback window
```

### Work

- Record the exact application version and schema version used for cutover.
- Run database, API, ingestion, and analysis smoke tests.
- Monitor errors, latency, connection-pool saturation, lock contention, and job throughput.
- Keep DuckDB unchanged during the rollback window.
- Roll back through configuration and application deployment rather than reverse-copying partially written PostgreSQL data into DuckDB.
- Remove production DuckDB dependencies only after PostgreSQL is stable and the rollback window closes.

### Deliverable

A controlled production cutover with explicit success criteria and rollback instructions.

### Exit Criteria

- Production traffic uses PostgreSQL successfully.
- Operational metrics remain within accepted thresholds.
- The rollback window closes without unresolved data-integrity issues.
- DuckDB is removed from the production runtime path.

## Planned Implementation Increments

The work should be delivered in independently reviewable increments:

1. PostgreSQL schema and migration tooling.
2. Storage interfaces and repository contracts.
3. DuckDB adapter moved behind the storage interfaces.
4. PostgreSQL repository implementation.
5. Ingestion and job-concurrency conversion.
6. Tools, evidence, and analysis-run conversion.
7. Integration, concurrency, and parity tests.
8. Optional historical backfill utility.
9. Operations documentation, retention job, deployment configuration, and cutover checklist.

## Initial Data Decision

The default plan is to initialize PostgreSQL without historical data and allow ask-driven ingestion to populate it. Historical transfer from `/Users/patrick/Developer/nba/data/nba_agent.duckdb` will occur only if preserving the old local cache is explicitly requested.

## Definition of Done

The migration is complete when:

- PostgreSQL is the actual production datastore, not only a configured backend name.
- All application storage operations use the defined storage boundary.
- Schema migrations are reproducible and tested.
- Ingestion and job handling are safe under concurrency.
- PostgreSQL integration and parity tests pass.
- Retention, backups, monitoring, cutover, and rollback are documented.
- Historical data, if selected for transfer, is validated and accounted for.
- DuckDB is no longer required in the production runtime path.

# PostgreSQL Migration Phase 1: Storage Baseline

## Status

Phase 1 is complete. This document records the storage behavior that had to be preserved or deliberately changed during the PostgreSQL migration. It is a point-in-time description of the DuckDB implementation, not the target PostgreSQL design. It is superseded as a current-state reference by [`postgresql-phase-4-runtime.md`](postgresql-phase-4-runtime.md) through [`postgresql-phase-7-historical-transfer.md`](postgresql-phase-7-historical-transfer.md).

The baseline was produced from the migrated working tree on 2026-09-21 at commit `90b5648`, plus the uncommitted migration-planning documents.

## Executive Summary

DuckDB is not isolated behind a storage boundary. Database paths, DuckDB connection types, direct SQL, and DuckDB-specific syntax appear in schema setup, official ingestion, analysis tools, persisted job handling, service constructors, command-line utilities, and legacy fixture import code.

The most important behavioral findings are:

- `NBA_STORAGE_BACKEND=postgres` validates configuration but does not select PostgreSQL. All runtime connections still open DuckDB.
- Schema creation is embedded in application code and is invoked opportunistically by write paths.
- Most writes rely on DuckDB autocommit and closing the connection; the code has no explicit transaction scopes.
- Game refresh operations generally use `DELETE` followed by `INSERT`. A failure between those statements can leave data missing or partially replaced.
- A full game bundle is assembled by several independent connections and therefore is not atomic as a unit.
- Evidence writes use DuckDB's `INSERT OR REPLACE`; ingestion tables are generally refreshed with delete-then-insert.
- JSON documents are stored as `TEXT` and timestamps are naive DuckDB `TIMESTAMP` values.
- The schema has primary keys but no foreign keys, check constraints, secondary indexes, or broadly applied `NOT NULL` constraints.
- Local background jobs are persisted, but job claiming is not atomic and is not safe for multiple workers or API instances.

These facts defined the starting point for Phase 2 and the later repository abstraction.

## Storage Entry Points and Coupling

| File | Responsibility | Current coupling |
|---|---|---|
| `api/nba_agent/db.py` | Storage configuration, DuckDB connection creation, schema creation | Imports DuckDB, returns `DuckDBPyConnection`, embeds all DDL |
| `api/nba_agent/official_ingest.py` | Fetch and normalize official NBA data | Opens DuckDB directly, executes refresh SQL, persists raw payloads, uses DuckDB connection type annotations |
| `api/nba_agent/tools.py` | Cache checks, analysis queries, evidence persistence, lineup inference, analysis-run persistence | Opens connections directly, contains DuckDB-specific `INSERT OR REPLACE`, catches DuckDB exceptions, passes DuckDB connections to helpers |
| `api/nba_agent/ingestion_jobs.py` | Persist and retrieve local ingestion-job state | Opens connections directly, creates schema opportunistically, updates state without compare-and-set or locking |
| `api/nba_agent/service.py` | Shared domain-service facade | Stores and propagates a filesystem `db_path`; no backend-neutral storage dependency |
| `api/nba_agent/analysis.py` | Deterministic analysis orchestration | Passes `db_path` into cache, query, and evidence functions |
| `api/nba_agent/agent.py` | Deterministic agent flow | Passes `db_path` throughout resolution, ingestion, analysis, and evidence expansion |
| `api/nba_agent/openai_agent.py` | Legacy OpenAI agent flow | Passes `db_path` into cache and analysis operations |
| `api/nba_agent/responses_agent.py` | Responses API agent flow | Constructs `NBAService(db_path)` and writes analysis runs through a direct persistence helper |
| `api/routes.py` | HTTP API | Uses module defaults, exposes storage configuration, and starts in-process background ingestion jobs |
| `api/nba_agent/bootstrap_fixture.py` | Legacy fixture import | Opens DuckDB and SQLite directly; uses DuckDB CSV functions and DuckDB-specific casts/string functions |
| `scripts/nba_agent/web_app.py` | Legacy application entry point | Reaches application functions that default to the local DuckDB path |

## Schema Inventory

All production tables are created by `create_schema` in `api/nba_agent/db.py`.

| Table | Primary key | Logical owner | Write pattern | Main readers |
|---|---|---|---|---|
| `raw_responses` | `response_id` | Official ingestion | Append one payload per upstream request | Audit/debugging; no current product query path |
| `games` | `game_id` | Official ingestion or legacy fixture import | Delete game row, then insert replacement | Cache status, snapshot, all analysis contexts |
| `box_scores_team` | (`game_id`, `team_side`) | Official ingestion or legacy fixture import | Delete game rows, then insert two replacements | Snapshot, advanced fallback, possession analysis |
| `box_scores_player` | (`game_id`, `player_id`) | Official ingestion or legacy fixture import | Delete game rows, then bulk insert replacements | Player context and cache completeness |
| `box_scores_advanced_team` | (`game_id`, `team_id`) | Official ingestion | Delete game rows, then bulk insert replacements | Advanced context and cache completeness |
| `play_by_play_events` | (`game_id`, `eventnum`) | Official ingestion or legacy fixture import | Delete game rows, then bulk insert replacements | Decisive runs, possessions, evidence rehydration, lineup inference |
| `lineup_stints` | `stint_id` | Official rotation ingestion or substitution inference | Delete by game and source, then `INSERT OR REPLACE` | Lineup context |
| `evidence_packets` | `packet_id` | Analysis tools | `INSERT OR REPLACE`; same packet ID replaces prior payload | Evidence detail and status counts |
| `analysis_runs` | `run_id` | Responses agent | Append-only insert with generated UUID-based ID | No current list/read path in application code |
| `ingestion_jobs` | `job_id` | Ingestion job runner | Insert queued job, then unconditional updates by ID | Job status endpoint |

### Current Type and Constraint Characteristics

- Identifiers are stored as `TEXT`, including NBA numeric identifiers.
- Statistical measures use `DOUBLE`; scores and event numbers use `INTEGER`.
- Request, response, evidence, packet-ID, and job-result JSON are stored as serialized `TEXT`.
- `fetched_at`, `imported_at`, `created_at`, and `updated_at` use `TIMESTAMP DEFAULT current_timestamp`.
- Only primary-key columns receive implicit non-null enforcement.
- There are no foreign keys from child tables to `games`.
- There are no checks for `team_side`, job status, confidence, period, scores, or non-negative durations.
- There are no secondary indexes for `game_id`, timestamps, status, or source columns.
- There are no schema-version records or migrations; repeated `CREATE TABLE IF NOT EXISTS` calls are the only schema-management mechanism.

## Operation Inventory

### Schema and Configuration

| Operation | Behavior |
|---|---|
| `storage_config` | Defaults to DuckDB; accepts `duckdb` or `postgres`; requires `DATABASE_URL` for `postgres`; returns the local DuckDB path for either setting |
| `connect` | Always calls `duckdb.connect(path, read_only=...)`; it does not consult `storage_config` |
| `create_schema` | Executes ten independent `CREATE TABLE IF NOT EXISTS` statements |
| `initialize_database` | Creates the parent directory, opens a writable DuckDB connection, creates the schema, and closes it |

### Official Ingestion Writes

| Operation | Tables | Semantics |
|---|---|---|
| `persist_raw_response` | `raw_responses` | Append using a generated UUID-based ID; serializes request and response with `json.dumps(default=str)` |
| `fetch_recent_completed_games(..., db_path=...)` | `raw_responses` | Optionally initializes the schema and stores the complete league-log response |
| `import_official_game_and_team_box` | `raw_responses`, `games`, `box_scores_team` | Stores two raw responses; deletes the existing game and team rows; inserts one game and two team rows |
| `import_official_advanced_team_box` | `raw_responses`, `box_scores_advanced_team` | Stores raw response; deletes all advanced rows for the game; bulk inserts replacements |
| `import_official_player_box` | `raw_responses`, `box_scores_player` | Stores raw response; deletes all player rows for the game; bulk inserts replacements |
| `import_official_play_by_play` | `raw_responses`, `play_by_play_events` | Requires a game row; stores raw response; deletes all events for the game; bulk inserts replacements |
| `import_official_game_rotation` | `raw_responses`, `lineup_stints` | Stores raw response; deletes official rotation rows for the game; replaces rows by `stint_id` |
| `import_official_game_bundle` | All normalized game-data tables except evidence/runs/jobs | Calls five import functions sequentially; rotation failure is downgraded to a warning, all other failures propagate |

### Analysis and Evidence Writes

| Operation | Tables | Semantics |
|---|---|---|
| `persist_evidence_packets` | `evidence_packets` | No-op success for an empty list; bulk `INSERT OR REPLACE`; catches only `duckdb.IOException` and returns `False` for that error |
| `with_persisted_packets` | `evidence_packets` | Conditionally invokes persistence; callers do not inspect the returned success flag |
| `persist_analysis_run` | `analysis_runs` | Appends one row with a generated UUID-based run ID and serialized packet IDs |
| `infer_lineup_stints_from_substitutions` | `lineup_stints` | Reads substitution events, deletes prior inferred rows for the game, and replaces generated low-confidence rows |

### Ingestion Job Writes

| Operation | Tables | Semantics |
|---|---|---|
| `create_ingestion_job` | `ingestion_jobs` | Initializes schema, inserts a generated job with `queued` status, and returns it |
| `update_ingestion_job` | `ingestion_jobs` | Validates status in Python, then unconditionally updates matching ID; silently succeeds when the ID does not exist |
| `run_ingestion_job` | `ingestion_jobs` and game-data tables | Moves to `fetching`; stores `ready` or `partial` after ingestion; catches every exception and stores `failed` with its message |

### Read Operations

| Area | Operations and behavior |
|---|---|
| Cache inspection | `get_cached_games_status` counts required child rows; `ensure_game_cached` treats a game as complete only with a game row, two team rows, two advanced rows, at least one player row, and at least one play-by-play row |
| Game and box score | `get_game_snapshot` and `get_box_score` return structured `not_found` results instead of raising when the game row is missing |
| Lineups | `get_lineup_stints` queries official/inferred rows and triggers substitution inference when no matching rows exist |
| Analytical contexts | `find_decisive_runs`, `get_possession_summary`, `get_advanced_game_context`, and `get_player_game_context` execute direct SQL and build evidence packets in memory |
| Evidence detail | `rehydrate_evidence_packet` first reads a stored packet; for known packet families it may re-query play-by-play or regenerate snapshot/context details |
| Jobs | `get_ingestion_job` returns `None` for an unknown ID and deserializes `result_json` when present |

## Transaction and Atomicity Baseline

No application function explicitly issues `BEGIN`, `COMMIT`, or `ROLLBACK`, and connections are not managed with context managers or `try/finally` cleanup.

Current consequences:

- Each DuckDB statement is effectively committed independently.
- Delete-then-insert refreshes are not guaranteed to be atomic across the refresh operation.
- Raw responses can be committed even when normalization later fails.
- A failure after a delete can leave a normalized table empty or partially repopulated.
- `import_official_game_bundle` spans multiple independently committed connections, so a game can have a mixture of old and new component data.
- The job transition and the data ingestion it describes are not in one transaction.
- Exceptions can bypass `con.close()` in functions without `try/finally`.

This behavior should be preserved only where it is an intentional audit characteristic, such as retaining a raw upstream response after a normalization failure. Normalized refresh operations should become atomic in PostgreSQL.

## Idempotency Baseline

- Official normalized imports are logically idempotent for a game because they delete the selected game scope and recreate it.
- `evidence_packets` and `lineup_stints` are logically idempotent by deterministic primary key and `INSERT OR REPLACE`.
- `raw_responses`, `analysis_runs`, and `ingestion_jobs` are append-oriented and generate a new UUID-based ID on every call.
- Re-running a full bundle produces additional raw-response records even when normalized data is unchanged.
- No database constraint prevents two queued ingestion jobs for the same game.
- No atomic compare-and-set prevents two workers from running the same queued job.

## Error-Handling Baseline

- Configuration errors raise `RuntimeError` for an unknown backend or missing PostgreSQL URL.
- Cache inspection catches any `duckdb.Error` and falls back to official ingestion.
- Evidence persistence catches only `duckdb.IOException`, converts it to `False`, and otherwise propagates errors.
- Missing game rows usually produce structured `not_found` responses.
- Official ingestion generally propagates provider and database errors.
- Game-rotation ingestion is optional inside a full bundle; its errors become warnings.
- The local job runner catches all ingestion exceptions and persists a `failed` state.
- There is no common database error model, retry classification, retry budget, or statement timeout.

## Concurrency Baseline

The implementation is designed for a single local process and file-backed database.

- In-process FastAPI background tasks execute jobs without a durable worker queue.
- Jobs are not claimed atomically.
- Job state updates do not verify the prior state.
- There is no uniqueness rule for active jobs by game.
- Multiple refreshes for one game can interleave delete and insert operations.
- Connection pooling and pool sizing do not exist.
- No advisory locks or row locks coordinate ingestion by game.

PostgreSQL implementation work must define these semantics rather than reproduce unsafe concurrency behavior.

## Existing Test Coverage

Before Phase 1, tests covered:

- Schema creation at a table-presence level.
- Presence of the `ingestion_jobs` table.
- Default DuckDB storage configuration.
- Selected agent, evaluation, and web behavior.

Phase 1 adds characterization coverage for:

- The exact production table set.
- Primary-key definitions.
- Timestamp defaults and JSON-as-text baseline types.
- Idempotent schema initialization.
- PostgreSQL configuration validation without implying PostgreSQL runtime support.
- Evidence replacement semantics.
- Append-only analysis-run behavior.
- Ingestion-job creation, lifecycle updates, result serialization, missing-job behavior, and invalid-state rejection.

These tests intentionally describe the current implementation. Later phases may update them when a behavior is deliberately changed and documented.

## Gaps and Engineering Risks

| Priority | Gap | Required future treatment |
|---|---|---|
| High | Backend flag does not select a backend | Introduce a real backend-neutral connection/repository boundary |
| High | Delete-then-insert refreshes are not transactional | Use explicit PostgreSQL transactions and upserts/staging where appropriate |
| High | Job claiming is not concurrency-safe | Add atomic state transitions and row-level locking or equivalent |
| High | Full game ingestion is not atomic | Define component-level versus bundle-level transaction policy |
| High | No foreign keys or domain constraints | Define canonical PostgreSQL relationships and constraints in Phase 2 |
| Medium | JSON stored as text | Select JSONB columns and validate serialization contracts |
| Medium | No indexes beyond primary keys | Derive indexes from recorded query paths and verify with query plans later |
| Medium | Connection cleanup is not exception-safe | Use managed sessions/connections and explicit rollback |
| Medium | Evidence persistence errors can be silently ignored | Define consistent storage error propagation and observability |
| Medium | Raw responses have no retention | Add retention metadata, policy, and cleanup operation |
| Low | Legacy fixture bootstrap depends on DuckDB-specific SQL | Keep as a development adapter or rewrite only if it remains supported |

## Decisions Deferred to Phase 2 or Later

- Exact foreign-key delete behavior for audit tables and analysis history.
- Whether raw responses remain in PostgreSQL long-term or later move to object storage.
- Which currently nullable fields become required.
- Whether a full game bundle is one transaction or a set of independently visible component transactions.
- Whether DuckDB remains a supported runtime backend or only a test/development adapter.
- Whether legacy fixture bootstrap remains supported after PostgreSQL cutover.
- Whether duplicate active ingestion jobs are rejected, coalesced, or returned to the caller as an existing job.

## Phase 1 Exit Criteria

- [x] Every storage operation has an identified owner and purpose.
- [x] Direct database coupling and DuckDB-specific behavior are identified.
- [x] Current transaction, refresh, idempotency, error, and concurrency behavior is documented.
- [x] Table keys, types, relationships, and missing constraints are documented.
- [x] Existing coverage and missing coverage are identified.
- [x] Characterization tests protected the critical behavior needed before Phase 2.

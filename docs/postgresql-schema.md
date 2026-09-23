# Canonical PostgreSQL Schema

Phase 2 establishes the versioned PostgreSQL schema. It is deliberately a
target schema rather than a copy of DuckDB DDL: structured documents are
`JSONB`, operational timestamps are `TIMESTAMPTZ`, and relationships and
state constraints are enforced by PostgreSQL.

The canonical application schema comprises the ten operational tables defined
by revision `20260922_01`. Revision `20260922_03` additionally creates
`seed_player_game_logs` solely to preserve the legacy historical dataset. It
has no stable primary key in the source and is not part of the normal
application write path. Its one-time transfer and rerun constraints are
recorded in [the migration plan](postgresql-migration-plan.md).

Revision `20260923_01` adds `harness_runs`: independently identified run records
with JSONB checkpoints, constrained status, explicit stopping reason, and
timezone-aware creation/update timestamps. Runs can exist before a game is
resolved, so this table deliberately has no game foreign key. A creation-time
index supports later retention queries. See [harness operations](harness.md).

Revision `20260923_02` links follow-up questions into conversations. It adds
nullable `conversation_id` and `parent_run_id` columns to `harness_runs`, a
self-referencing foreign key from `parent_run_id` to `run_id`, and an index on
`(conversation_id, created_at)` for reading a conversation in order. Runs
created before this revision keep null values and are not listed as
conversations.

## Relationships and deletion policy

`games` is the parent of normalized game data. Its box scores, play-by-play,
lineup stints, and evidence packets use `ON DELETE CASCADE`; they have no
meaning without their game. `analysis_runs` uses `ON DELETE SET NULL` so that
historical analysis remains auditable if a game record is deliberately
removed. `raw_responses` has no foreign key because an upstream response may
be captured before a game exists locally (for example, a league-wide log).

## Domain controls

- `ingestion_jobs.status` is one of `queued`, `fetching`, `ready`, `partial`,
  or `failed`.
- Team-side, confidence, period, score, duration, and event-number fields
  have constraints where the domain has a stable bound.
- Required payloads (`request_json`, `response_json`, `payload_json`, and
  `packet_ids_json`) use non-null `JSONB` columns.

## Indexing rationale

Indexes cover the observed application paths: game/date lookup, child records
by game and team/period, evidence lookup by game/type, job lookup by status or
game, and raw-response retention by fetch timestamp. Primary keys cover all
idempotent conflict identities. Query-plan tuning remains a production
operations concern once realistic load exists.

## Migration commands

Use an explicit PostgreSQL URL; the command never defaults to DuckDB:

```bash
source .venv/bin/activate
POSTGRES_CONNECTION_STRING="$POSTGRES_TEST_DATABASE_URL" alembic upgrade head
POSTGRES_CONNECTION_STRING="$POSTGRES_TEST_DATABASE_URL" alembic current
POSTGRES_CONNECTION_STRING="$POSTGRES_TEST_DATABASE_URL" alembic downgrade -1
```

For the disposable development service, set `POSTGRES_TEST_DATABASE_URL` from
`.env.test.example` or provide its value directly. Do not point these commands
at a shared or production database without the normal deployment review and
backup process.

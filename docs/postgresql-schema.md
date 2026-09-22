# Canonical PostgreSQL Schema

Phase 2 establishes the versioned PostgreSQL schema. It is deliberately a
target schema rather than a copy of DuckDB DDL: structured documents are
`JSONB`, operational timestamps are `TIMESTAMPTZ`, and relationships and
state constraints are enforced by PostgreSQL.

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
DATABASE_URL="$POSTGRES_TEST_DATABASE_URL" alembic upgrade head
DATABASE_URL="$POSTGRES_TEST_DATABASE_URL" alembic current
DATABASE_URL="$POSTGRES_TEST_DATABASE_URL" alembic downgrade -1
```

For the disposable development service, set `POSTGRES_TEST_DATABASE_URL` from
`.env.test.example` or provide its value directly. Do not point these commands
at a shared or production database without the normal deployment review and
backup process.

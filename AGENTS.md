# Repository Guide for Agents

## Current State

- The clean-repository migration is complete; its provenance is in
  `docs/MIGRATION-PROVENANCE.md`. Do not modify `/Users/patrick/Developer/nba`
  as part of normal work.
- PostgreSQL is the active configured datastore. The historical DuckDB cache
  was transferred on 2026-09-22; see
  `docs/postgresql-phase-7-historical-transfer.md`.
- DuckDB is a temporary development and rollback adapter only. Do not add new
  production dependencies on a DuckDB file.
- Azure deployment/cutover is intentionally pending. Do not deploy or change
  cloud resources without explicit user authorization.

## Working Rules

- Keep secrets in ignored `.env` files. Runtime PostgreSQL configuration uses
  `NBA_STORAGE_BACKEND=postgres` and `DATABASE_URL`; never print connection
  strings.
- Activate the project environment with `source .venv/bin/activate`. Do not
  introduce Conda.
- Apply schema changes through Alembic and test them against the disposable
  PostgreSQL service; application startup must not own PostgreSQL DDL.
- Preserve the storage boundary in `api/nba_agent/storage/`. New application
  code must not construct DuckDB or psycopg connections directly.
- Use `pytest -q` for the standard suite. For PostgreSQL integration coverage,
  start `docker compose up -d postgres-test` and supply the explicit test URL
  documented in `docs/postgresql-development.md`.

## Documentation Map

- `README.md`: current application setup and runtime model.
- `docs/architecture-v2.md`: current application boundaries.
- `docs/postgresql-migration-plan.md`: migration status; Phase 8 is next.
- `docs/postgresql-phase-*.md`: point-in-time phase records; append a
  supersession note rather than rewriting their historical assertions.
- `docs/capstone-scope.md`: forward-looking course scope, not a statement that
  every listed feature exists today.

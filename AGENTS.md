# Repository Instructions

## Project layout

- `api/` contains the FastAPI application and NBA domain logic.
- `api/nba_agent/storage/` owns storage adapters and repositories; callers use
  the storage boundary rather than driver-specific connections.
- `frontend/` is the Vite/React client.
- `migrations/` is the source of truth for PostgreSQL schema changes.
- `docs/` contains architecture, operational guidance, and historical phase
  records. Consult the relevant document instead of duplicating changing
  project status in this file.

## Engineering rules

- Keep secrets, database URLs, and runtime data in ignored environment or data
  files; never print or commit them.
- Use `source .venv/bin/activate` for Python work. Do not introduce Conda.
- Add or change PostgreSQL schema only through Alembic migrations. Application
  startup must not create or alter PostgreSQL schema.
- Preserve parameterized queries, explicit transactions, and the storage
  boundary when changing persistence behavior.
- Update user-facing or operational documentation when behavior, configuration,
  or deployment requirements change. Preserve historical phase documents; add
  a short supersession note instead of rewriting their point-in-time record.

## Verification

- Run `pytest -q` for Python changes when practical.
- For PostgreSQL integration coverage, use the disposable `postgres-test`
  service and explicit test URL documented in `docs/postgresql-development.md`.
- For frontend changes, run `npm run build` from `frontend/`.
- Report checks run and any checks intentionally not run.

# PostgreSQL Development Prerequisites

## Python Environment

The project targets Python 3.12. The repository contains a `.python-version`
file, and the local virtual environment is created at `.venv`.

Activate it before running Python tooling:

```bash
source .venv/bin/activate
python --version
```

The expected interpreter is Python 3.12. Install project dependencies with:

```bash
pip install -r requirements.txt
```

Alembic is declared in `requirements.txt`. The versioned PostgreSQL schema is
defined in `migrations/`; application startup does not create PostgreSQL
tables.

## Disposable PostgreSQL Service

`compose.yaml` defines a local PostgreSQL 16 service named `postgres-test`.
It binds only to loopback on port `55432` by default and stores its database in
a container `tmpfs`. Data is therefore disposable and is lost when the
container is removed.

The checked-in credentials are intentionally restricted to this disposable
local service. Never reuse them in a shared or deployed environment.

Start and check the service:

```bash
docker compose up -d postgres-test
docker compose ps postgres-test
```

The default test connection URL is:

```text
postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test
```

Copy `.env.test.example` to an ignored `.env.test` only when local overrides
are needed. Test and migration commands should receive the test URL explicitly;
they must not default to a production or developer database.

Stop and remove the disposable service with:

```bash
docker compose down
```

## Local verification

Verify the Python environment and local test suite with:

```bash
source .venv/bin/activate
pytest -q
python -c "import alembic, psycopg2, sqlalchemy"
```

The test suite forces the default backend to an isolated temporary DuckDB
database, regardless of the developer application's ignored `.env`. Tests that
exercise PostgreSQL opt in explicitly with `POSTGRES_TEST_DATABASE_URL`; they
never inherit `POSTGRES_CONNECTION_STRING` or `NBA_POSTGRES_SCHEMA`.

Then confirm a connection to the disposable database using the test URL.

## Schema migrations

Supply an explicit URL when operating on a database. Alembic refuses to infer
or fall back to a local DuckDB file:

```bash
source .venv/bin/activate
POSTGRES_CONNECTION_STRING=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test alembic upgrade head
POSTGRES_CONNECTION_STRING=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test alembic current
```

The PostgreSQL integration test uses a unique temporary schema inside this
disposable database, migrates it from zero to `head`, verifies the schema, and
downgrades it. Run it together with the suite using:

```bash
POSTGRES_TEST_DATABASE_URL=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test pytest -q
```

## Active local application database

The active local API uses PostgreSQL when the ignored `.env` sets
`NBA_STORAGE_BACKEND=postgres` and `POSTGRES_CONNECTION_STRING`. Apply
migrations before starting against a fresh database:

```bash
source .venv/bin/activate
alembic upgrade head
```

Alembic loads the repository's ignored `.env` for local commands. An exported
shell variable or deployment environment takes precedence, so CI and production
must inject `POSTGRES_CONNECTION_STRING` explicitly rather than relying on a
file bundled with the application.

Do not use the disposable test URL for the active application, and do not put
the active connection string in committed files.

## Runtime and operations

`PostgresStorage` uses a bounded process-local connection pool. Each storage
scope is transactional; successful scopes commit and database failures roll
back. Queries remain parameterized through the storage boundary, and startup
checks the Alembic version instead of creating PostgreSQL tables.

| Setting | Default | Purpose |
| --- | ---: | --- |
| `NBA_DB_POOL_MIN` | 1 | Warm pooled connections |
| `NBA_DB_POOL_MAX` | 5 | Upper bound per application process |
| `NBA_DB_CONNECT_TIMEOUT_SECONDS` | 5 | Bound failed connection attempts |
| `NBA_DB_STATEMENT_TIMEOUT_MS` | 10000 | Cancel unexpectedly slow statements |

Keep the combined maximum pool size below the database connection limit,
including administrative and migration connections. `GET /api/health/storage`
checks the active adapter without exposing connection details.

`raw_responses` retains redacted upstream captures for 60 days by default.
Run bounded cleanup batches from a scheduler when deployed:

```bash
source .venv/bin/activate
NBA_STORAGE_BACKEND=postgres POSTGRES_CONNECTION_STRING='postgresql://...' \
  python scripts/cleanup_raw_responses.py --retention-days 60 --batch-size 500
```

The command reports deletion counts only. Take an encrypted backup and verify
a restore into an isolated database before every production schema migration.

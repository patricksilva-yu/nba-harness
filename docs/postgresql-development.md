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

## Verification

Before Phase 2 implementation begins, verify:

```bash
source .venv/bin/activate
pytest -q
python -c "import alembic, psycopg2, sqlalchemy"
```

Then confirm a connection to the disposable database using the test URL.

## Schema migrations

Supply an explicit URL when operating on a database. Alembic refuses to infer
or fall back to a local DuckDB file:

```bash
source .venv/bin/activate
DATABASE_URL=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test alembic upgrade head
DATABASE_URL=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test alembic current
```

The PostgreSQL integration test uses a unique temporary schema inside this
disposable database, migrates it from zero to `head`, verifies the schema, and
downgrades it. Run it together with the suite using:

```bash
POSTGRES_TEST_DATABASE_URL=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test pytest -q
```

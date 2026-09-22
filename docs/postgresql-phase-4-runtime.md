# PostgreSQL Migration Phase 4: Runtime Backend

Phase 4 makes PostgreSQL an executable storage backend. It does not change the
default: DuckDB remains the default local adapter while PostgreSQL is selected
only by setting both `NBA_STORAGE_BACKEND=postgres` and `DATABASE_URL`.

## Runtime behavior

- `PostgresStorage` owns driver creation and a process-local bounded
  `ThreadedConnectionPool` (default minimum 1, maximum 5 connections).
- Each `open()` scope is a transaction: a normal `close()` commits and a
  database failure marks the scope for rollback before the pooled connection is
  returned.
- The adapter converts the storage boundary's qmark parameters to psycopg2
  parameters. Application queries therefore remain parameterized; values are
  never interpolated into SQL.
- PostgreSQL connections use a five-second connection timeout and a ten-second
  statement timeout by default. `NBA_DB_POOL_MIN`, `NBA_DB_POOL_MAX`,
  `NBA_DB_CONNECT_TIMEOUT_SECONDS`, and `NBA_DB_STATEMENT_TIMEOUT_MS` allow
  explicit deployment overrides.
- Schema ownership remains with Alembic. PostgreSQL startup verifies
  `alembic_version` and gives an actionable error if migrations have not run;
  it never executes application-owned `CREATE TABLE` statements.
- JSONB values are normalized at the repository boundary so the application
  sees the same Python structures it saw when DuckDB stored JSON text.

## Idempotency and concurrent jobs

Evidence and lineup writes now use explicit `INSERT ... ON CONFLICT DO UPDATE`
semantics on both adapters. Revision `20260922_02` adds a partial unique index
that permits only one queued or fetching ingestion job per game. A job is
claimed with an atomic `UPDATE ... WHERE status = 'queued' RETURNING job_id`,
so duplicate worker deliveries do not perform duplicate ingestion.

The adapter does not blindly retry writes after an ambiguous connection loss:
that could duplicate an upstream fetch or conceal a failed transaction. The
atomic conflict keys and job claims make retry policy safe to add at the worker
layer when that worker is introduced.

## Deploying PostgreSQL mode

1. Apply migrations as a deployment step: `DATABASE_URL=... alembic upgrade head`.
2. Configure `NBA_STORAGE_BACKEND=postgres` and the same `DATABASE_URL`.
3. Start the service. It will fail clearly rather than create an unversioned
   schema if migrations are missing.

DuckDB is not opened in this mode. The first cache miss fetches official NBA
data and persists it in PostgreSQL; no historical DuckDB cache is required.

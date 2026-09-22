# PostgreSQL Migration Phase 6: Verification and Parity

Phase 6 verifies the storage replacement with deterministic records in isolated
PostgreSQL schemas. It does not use live NBA API requests, so failures identify
storage behavior rather than an upstream availability change.

## Automated coverage

- Alembic upgrades an empty PostgreSQL schema through every revision and
  downgrades it cleanly.
- PostgreSQL repository writes verify JSONB decoding, idempotent evidence
  replacement, bounded raw-response retention, and rollback after a failed
  statement.
- The same seeded team box score produces equivalent public tool output from
  DuckDB and PostgreSQL.
- With `NBA_STORAGE_BACKEND=postgres`, the HTTP box-score endpoint reads the
  PostgreSQL schema and returns the expected record count.
- Two simultaneous workers attempt to claim one queued job; exactly one wins.
- Existing DuckDB characterization tests remain in the suite.

## Running verification

Start the disposable service, then supply only its explicit test URL:

```bash
docker compose up -d postgres-test
source .venv/bin/activate
POSTGRES_TEST_DATABASE_URL=postgresql://nba_test:nba_test_local_only@127.0.0.1:55432/nba_test pytest -q
```

The PostgreSQL tests create a unique non-public schema per test and remove it
afterward. `NBA_POSTGRES_SCHEMA` exists only to let those tests point the
application runtime at an isolated schema; normal deployments should leave it
unset and use the PostgreSQL default schema.

## Result

The defined behavior standard is met for the tested cache/read, evidence,
retention, transaction, job-claim, and API paths:

```text
Same seeded records
→ equivalent box-score response
→ equivalent persisted evidence behavior
→ PostgreSQL-mode API response
```

This phase deliberately did not use the live NBA provider. Historical DuckDB
transfer was subsequently completed and recorded in
[`postgresql-phase-7-historical-transfer.md`](postgresql-phase-7-historical-transfer.md).
Operational smoke tests against the NBA provider remain a deployment
responsibility.

# PostgreSQL Migration Phase 5: Retention and Operations

## Raw-response policy

`raw_responses` preserves upstream request/response captures for diagnosis and
source traceability. Its initial default retention is **60 days**. Configure
it with `NBA_RAW_RESPONSE_RETENTION_DAYS`; production values should normally
remain within the planned 30–90 day range.

Before persistence, request and response payloads are recursively redacted for
credential-like keys, including authorization, API-key, token, secret,
password, cookie, and session fields. Redaction happens before JSON
serialization, so neither adapter stores those values.

Run one bounded cleanup batch with:

```bash
source .venv/bin/activate
NBA_STORAGE_BACKEND=postgres DATABASE_URL='postgresql://...' \
  python scripts/cleanup_raw_responses.py --retention-days 60 --batch-size 500
```

The command deletes at most `NBA_RAW_RESPONSE_RETENTION_BATCH_SIZE` records
(500 by default), ordered oldest first, then reports only the deletion count.
Run it from a daily scheduler; repeat batches if its output remains nonzero.
It logs counts and backend identity only, never payloads or URLs.

## Health and runtime settings

`GET /api/health/storage` performs a `SELECT 1` using the active adapter. It
returns the backend name and `ok`, or an HTTP 503 without exposing connection
details when storage is unavailable.

PostgreSQL defaults are deliberately conservative:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `NBA_DB_POOL_MIN` | 1 | Warm pooled connections |
| `NBA_DB_POOL_MAX` | 5 | Upper bound per application process |
| `NBA_DB_CONNECT_TIMEOUT_SECONDS` | 5 | Bound failed connection attempts |
| `NBA_DB_STATEMENT_TIMEOUT_MS` | 10000 | Cancel unexpectedly slow statements |

Size the maximum pool across all service processes below the database’s
connection limit; include migrations, administrators, and monitoring in that
calculation.

## Backup, restore, and future payload storage

For a deployed PostgreSQL service, take automated encrypted logical or
physical backups at least daily and retain a tested restore point before every
schema migration. A restore drill should recover into an isolated database,
run `alembic current`, and verify representative games, evidence packets, and
ingestion-job records. Never test restores by overwriting the live database.

If raw payload volume becomes material, retain the relational metadata and move
large immutable bodies to object storage. That change requires a separate
schema migration, retention policy, access control design, and restore test;
it is not implicit in this phase.

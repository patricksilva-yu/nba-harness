# NBA Analyst Agent

Evidence-first NBA postgame analysis app centered on a custom harness that
governs MCP tool use over a PostgreSQL runtime datastore.

## Architecture Direction

[Architecture V3](docs/architecture-v3.md) is the accepted target architecture.
MCP is the required boundary between the agent harness and basketball data
tools. The research question is whether a custom harness can improve how an
agent selects, sequences, verifies, and stops using MCP tools.

The superseded direct-function prototype recorded in
[Architecture V2](docs/architecture-v2.md) has been removed; the MCP harness is
the only analysis path.

## Current Shape

- `api/` contains the FastAPI app, HTTP routes, auth, MCP server, harness and ingestion.
- `api/nba_agent/harness/` is the custom controller that governs MCP tool use.
- `api/nba_agent/service.py` is the basketball domain core behind the MCP server and ingestion jobs.
- `api/nba_agent/mcp_server.py` exposes the agent-facing tool boundary over the domain service.
- `frontend/` contains the standalone React UI served by Vite.
- `api/nba_agent/storage/` contains the storage contract plus DuckDB and PostgreSQL adapters.
- PostgreSQL is the active configured backend for this repository; the migrated historical cache is in the configured PostgreSQL database.
- `data/nba_agent.duckdb` is an ignored legacy/local rollback artifact, not the active datastore when PostgreSQL mode is configured.
- `docs/` contains the architecture, capstone scope, storage migration records, and operational guidance.
- `tests/` contains the regression tests.

## Run Locally

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
```

In another terminal, run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:3000`. The dev server forwards `/api` requests (including
the answer stream) to `NBA_API_PROXY_TARGET`, `http://127.0.0.1:8000` by default;
set it in `frontend/.env` if the API runs on another port. Asking a question
requires `alembic upgrade head` for PostgreSQL, because every harness run is
saved.

The UI is a React app built with Tailwind CSS v4 and the Catalyst UI kit
(`frontend/src/components/`, from Tailwind Plus). Application code lives in
`frontend/src/app/`. Add `?config=basic` or `?config=verification` to the URL to
try a lighter harness configuration during development.

After signing in, the home page lets users follow NBA teams and see their
completed games already in the database. Select a game to ask about it, or use
the sidebar's New question action. Favorites are saved per account; apply
`alembic upgrade head` before using them with PostgreSQL. This page does not
send notifications or generate analyses automatically.

Accounts use Supabase Auth. Set `SUPABASE_URL` (and optionally
`NBA_ADMIN_USER_IDS`) in `.env`, or set `NBA_AUTH_MODE=disabled` to run without
sign-in during local development. Asking and saved conversations need an
account; traces and ingestion are for admins. See [docs/auth.md](docs/auth.md).

## Harness

Every question runs through the MCP harness: a custom controller with mandatory
MCP, claim verification, targeted investigation, bounded execution and durable
traces. Its three configurations (`basic`, `verification`, `investigation`) are
the evaluated variants. See [harness operation and design](docs/harness.md) for
configuration, API examples and known limits. Apply `alembic upgrade head`
before using the harness with PostgreSQL.

## Model-Facing Tools

The primary MCP harness uses five task-level tools:

- `resolve_game`
- `ensure_game_data`
- `get_game_analysis_context` (sections include `stakes`, which the harness also attaches automatically once game data is cached; see [harness operations](docs/harness.md#stakes-context-added-2026-09-23))
- `get_game_window`
- `get_evidence_detail`

`resolve_game` matches team names and abbreviations as whole words (abbreviations that are everyday words, such as `WAS` or `DEN`, only in capitals) and understands written dates: `April 12, 2026`, `Apr 12`, `12 April 2026`, `4/12/2026`, `on 4/12`, `2026-04-12`, `last night`. A date without a year means its most recent past occurrence, and a dated question searches the whole season that contains the date.

The MCP server exposes exactly these tools; the harness also checks them
against a versioned allowlist.

## Ingestion Jobs

Cache misses can be run outside an analysis request through `POST /api/ingestion-jobs`. Poll `GET /api/ingestion-jobs/{job_id}` for `queued`, `fetching`, `ready`, `partial`, or `failed`.

## Data Store Model

Game data is stored in two layers:

- **Season results (every game).** `LeagueGameLog` returns every completed game of a season in one request. Each time a question resolves a game, the current season's regular-season and playoff results are refreshed and any new games are inserted into `games` as results-only rows. This powers the `stakes` section (series record, clinching games, team record and streaks). Backfill or refresh seasons with:

```bash
source .venv/bin/activate
python -m api.nba_agent.sync_results --season 2025-26 --season 2024-25
```

- **Game detail (on demand).** Box scores, play-by-play and advanced stats are fetched only when the user asks about a game and the active storage backend is missing required rows. There is no scheduled ETL for detail. The import reads the season and season type from the game ID (`0042300405` → 2023-24 Playoffs), so past-season games load the same way as current ones.

`games_ensure_game_cached` is the internal tool name. Conceptually, it ensures the local data store has:

- one `games` row
- two team box-score rows
- player box-score rows
- play-by-play rows
- two advanced team rows

PostgreSQL mode requires both `NBA_STORAGE_BACKEND=postgres` and `POSTGRES_CONNECTION_STRING`; the schema must be at the Alembic head before the API starts. The repository's local `.env` is configured this way. DuckDB remains available only as a temporary development/rollback adapter while deployment cutover is pending; it is not opened in PostgreSQL mode.

For a fresh PostgreSQL database, run:

```bash
source .venv/bin/activate
alembic upgrade head
```

Use the disposable DuckDB or PostgreSQL test configuration only for tests; never commit `.env` or connection strings.

## Test

```bash
.venv/bin/pytest -q
```

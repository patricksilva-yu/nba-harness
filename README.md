# NBA Analyst Agent

Evidence-first NBA postgame analysis app with a shared domain service, direct OpenAI Responses tools, an optional FastMCP adapter, and a PostgreSQL runtime datastore.

## Current Shape

- `api/` contains the FastAPI app, HTTP routes, analyst logic, MCP server, ingestion, and OpenAI adapter.
- `api/nba_agent/service.py` is the application core used by the API, Responses tools, and MCP adapter.
- `api/nba_agent/responses_agent.py` is the primary OpenAI integration and returns validated structured analysis.
- `api/nba_agent/mcp_server.py` is an optional interoperability adapter over the same service.
- `frontend/` contains the standalone React UI served by Vite.
- `prompts/` contains the editable OpenAI analyst prompt.
- `api/nba_agent/storage/` contains the storage contract plus DuckDB and PostgreSQL adapters.
- PostgreSQL is the active configured backend for this repository; the migrated historical cache is in the configured PostgreSQL database.
- `data/nba_agent.duckdb` is an ignored legacy/local rollback artifact, not the active datastore when PostgreSQL mode is configured.
- `docs/` contains the architecture, capstone scope, storage migration records, and operational guidance.
- `tests/` contains the regression tests for the current PoC workflow.

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

Open `http://127.0.0.1:3000`.

`scripts.nba_agent.web_app:app` remains as a compatibility entrypoint.

## Modes

- `deterministic`: no OpenAI API call; uses local routing and deterministic memo builders.
- `responses_tools`: primary mode; the Responses API calls four direct application function tools and returns JSON-schema output.
- `local_agents_sdk_mcp`: legacy compatibility mode using the local FastMCP server over stdio.
- `remote_responses_mcp`: legacy scaffold, not wired.

## Model-Facing Tools

The primary Responses path exposes four task-level tools:

- `resolve_game`
- `ensure_game_data`
- `get_game_analysis_context`
- `get_evidence_detail`

The MCP server exposes the same four preferred tools and retains the old granular tools temporarily for client compatibility.

## Ingestion Jobs

Cache misses can be run outside an analysis request through `POST /api/ingestion-jobs`. Poll `GET /api/ingestion-jobs/{job_id}` for `queued`, `fetching`, `ready`, `partial`, or `failed`.

## Data Store Model

There is no scheduled ETL. A game is fetched only when the user asks about it and the active storage backend is missing required rows.

`games_ensure_game_cached` is the internal tool name. Conceptually, it ensures the local data store has:

- one `games` row
- two team box-score rows
- player box-score rows
- play-by-play rows
- two advanced team rows

PostgreSQL mode requires both `NBA_STORAGE_BACKEND=postgres` and `DATABASE_URL`; the schema must be at the Alembic head before the API starts. The repository's local `.env` is configured this way. DuckDB remains available only as a temporary development/rollback adapter while deployment cutover is pending; it is not opened in PostgreSQL mode.

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

Run the representative deterministic evaluation set against the local cache:

```bash
.venv/bin/python -m api.nba_agent.evaluation
```

The evaluation cases live in `evals/postgame_cases.json` and check routing, required themes, forbidden claims, and evidence coverage.
The default run is network-independent and scores committed fixture results. Add `--live` to exercise the current local cache and on-demand ingestion.

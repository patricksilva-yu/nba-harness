# NBA Analyst Agent

Evidence-first NBA postgame analysis app with a shared domain service, direct OpenAI Responses tools, an optional FastMCP adapter, and a DuckDB local data store.

## Current Shape

- `api/` contains the FastAPI app, HTTP routes, analyst logic, MCP server, ingestion, and OpenAI adapter.
- `api/nba_agent/service.py` is the application core used by the API, Responses tools, and MCP adapter.
- `api/nba_agent/responses_agent.py` is the primary OpenAI integration and returns validated structured analysis.
- `api/nba_agent/mcp_server.py` is an optional interoperability adapter over the same service.
- `frontend/` contains the standalone React UI served by Vite.
- `prompts/` contains the editable OpenAI analyst prompt.
- `data/nba_agent.duckdb` is the local ask-driven data store for fetched game data, evidence packets, and analysis history.
- `docs/` contains the design doc and Excalidraw architecture diagram.
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

## Local Data Store Model

There is no scheduled ETL. A game is fetched only when the user asks about it and DuckDB is missing required rows.

`games_ensure_game_cached` is the internal tool name. Conceptually, it ensures the local data store has:

- one `games` row
- two team box-score rows
- player box-score rows
- play-by-play rows
- two advanced team rows

DuckDB is the supported local mode. Set `NBA_STORAGE_BACKEND=postgres` with `DATABASE_URL` only after applying the PostgreSQL migration for a multi-user deployment; the application rejects an implicit PostgreSQL configuration.

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

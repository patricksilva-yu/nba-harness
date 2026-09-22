# NBA Analyst MCP Repository Migration Handoff (Completed Archive)

> **Status: completed on 2026-09-21.** This document is the historical runbook
> for moving `/Users/patrick/Developer/nba` into this clean repository. It is
> retained for provenance, not as current operating guidance. The move's source
> commit and exclusions are recorded in
> [`MIGRATION-PROVENANCE.md`](MIGRATION-PROVENANCE.md). For current storage and
> deployment work, use [`postgresql-migration-plan.md`](postgresql-migration-plan.md)
> and the phase records instead.

## Mission

Move the current NBA Analyst project from this repository into a clean, new directory and Git repository without losing the active proof-of-concept work. Preserve the working local application, tests, evaluation fixtures, architecture documents, and deployment scaffolding. Do not carry secrets, generated dependencies, caches, or large legacy datasets into the new repository by default.

The source of truth is the **current working tree**, not only the latest Git commit. The source repository contains substantial uncommitted changes and untracked files that are part of the current architecture.

Before doing any migration work, record:

- Source directory: `/Users/patrick/Developer/nba`
- Target directory: `/Users/patrick/Developer/nba-harness`
- Migration date and source commit SHA
- The complete output of `git status --short`

Do not delete or modify the source repository as part of this migration.

## Product Scope to Preserve

The capstone is an evidence-first NBA postgame analysis application. A user identifies a completed NBA game, asks a bounded question, receives an evidence-supported answer, and can inspect the evidence and execution details.

The intended final system includes:

- NBA game resolution and ask-driven data ingestion
- A shared NBA domain service
- MCP-compatible tools for basketball data and evidence
- A custom Python agent harness with explicit run state and limits
- Claim verification and targeted follow-up investigation loops
- Structured run records, errors, stopping reasons, latency, token use, and estimated cost
- A web UI with Analysis, Investigation, and Evaluation views
- Comparative evaluation of:
  1. basic tool calling,
  2. tool calling plus claim verification,
  3. verification plus adaptive evidence gathering
- Azure deployment using a static frontend, containerized backend/services, and PostgreSQL

The primary scope reference is `docs/capstone-scope.md`. Preserve it unchanged during the repository move. Do not expand the product into a general NBA chatbot, betting product, prediction system, or multi-agent swarm.

## Current Architecture

The current code is a proof of concept moving toward the capstone design.

```text
React/Vite frontend
        |
        v
FastAPI routes
        |
        v
NBAService (shared domain boundary)
   |            |                 |
   v            v                 v
deterministic   OpenAI Responses  FastMCP compatibility adapter
analysis        function tools
        \          |             /
         \         v            /
          DuckDB + official NBA ingestion
```

Important boundaries:

- `api/nba_agent/service.py`: shared application/domain service
- `api/nba_agent/responses_agent.py`: primary OpenAI Responses integration with structured output
- `api/nba_agent/mcp_server.py`: optional MCP adapter and legacy compatibility tools
- `api/routes.py`: HTTP endpoints
- `api/nba_agent/ingestion_jobs.py`: persisted local background-ingestion job states
- `api/nba_agent/db.py`: DuckDB schema and storage configuration contract
- `api/nba_agent/tools.py`: deterministic data and evidence operations
- `api/nba_agent/official_ingest.py`: official NBA data ingestion
- `frontend/`: React/Vite client
- `evals/postgame_cases.json`: deterministic evaluation cases

The preferred model-facing tools are:

- `resolve_game`
- `ensure_game_data`
- `get_game_analysis_context`
- `get_evidence_detail`

The granular MCP tools and the Agents SDK stdio path remain only for compatibility. New work should use the shared service and the consolidated four-tool surface.

## Required Migration Set

Copy these paths from the current working tree, including uncommitted changes and untracked files:

```text
.dockerignore
.env.example
.github/workflows/docker-images.yml
.gitignore
README.md
requirements.txt
pytest.ini

api/
frontend/.dockerignore
frontend/.env.example
frontend/Dockerfile
frontend/index.html
frontend/package.json
frontend/package-lock.json
frontend/src/

prompts/
scripts/nba_agent/
tests/
evals/

docs/architecture-v2.md
docs/capstone-scope.md
docs/diagrams/nba-agent-mcp-architecture.excalidraw
docs/MIGRATION.md
```

Review and migrate these only if they remain intentionally supported:

```text
scripts/migrate_to_postgres.py
migrate_player_game_log.sql
sql/01_data_preparation.sql
docs/nba-analyst-agent-swarm-design.md
```

Notes:

- `scripts/migrate_to_postgres.py` is potentially useful, but it is a generic table-copy utility and is not a completed PostgreSQL application backend.
- `migrate_player_game_log.sql` and `sql/01_data_preparation.sql` belong to older player-log/PostgreSQL experiments and are not part of the current request path.
- `docs/nba-analyst-agent-swarm-design.md` contains useful early product thinking, but its “swarm” filename is misleading: the current scope explicitly excludes a multi-agent swarm unless evaluation later proves it necessary. Prefer renaming it to an archive/legacy design location or clearly marking it superseded.

## Do Not Copy by Default

Exclude all of the following:

```text
.git/
.env
.venv/
.pytest_cache/
**/__pycache__/
frontend/node_modules/
frontend/dist/
data/*.duckdb*
old/
output/playwright/
.vscode/
.agents/
.claude/
skills-lock.json
*.log
.DS_Store
```

Also omit the untracked root `package-lock.json` unless the new repository deliberately gains a root Node package. The active frontend lockfile is `frontend/package-lock.json`.

Reasons:

- `.env` may contain secrets and must never be committed or copied casually.
- Python and Node dependencies must be recreated from lock/requirements files.
- `frontend/dist` is a build artifact.
- `data/nba_agent.duckdb` is local runtime state and is ignored by Git.
- `old/` is about 2.8 GB of historical notebooks and databases. It is not required for the current application and should be archived separately if needed.
- `output/` contains generated course artifacts, not application source. If the capstone outline is still needed, move it to separate course-document storage or explicitly add a `docs/course/` policy rather than silently treating it as application code.

## Local Data Decision

The normal migration should create an empty `data/` directory, optionally with a tracked `.gitkeep`, and let the application initialize/fetch data on demand.

If preserving the current local cache is explicitly required, copy `data/nba_agent.duckdb` out of band after stopping all processes that may write to it. Treat it as private runtime data, keep it ignored by Git, and verify the copied database separately. Do not commit it to the new repository.

The current DuckDB schema includes:

- `raw_responses`
- `games`
- `box_scores_team`
- `box_scores_player`
- `box_scores_advanced_team`
- `play_by_play_events`
- `lineup_stints`
- `evidence_packets`
- `analysis_runs`
- `ingestion_jobs`

## Historical Environment Contract

Create a local `.env` from `.env.example`; do not copy the old `.env`.

```dotenv
OPENAI_API_KEY=
NBA_OPENAI_MODEL=gpt-5.5
NBA_OPENAI_AGENT_MODE=responses_tools
NBA_MCP_SERVER_URL=
NBA_OPENAI_AGENT_INSTRUCTIONS=
NBA_STORAGE_BACKEND=duckdb
DATABASE_URL=
```

Important behavior:

- `deterministic` mode does not require an OpenAI key.
- `responses_tools` is the preferred model-backed mode and requires `OPENAI_API_KEY`.
- `local_agents_sdk_mcp` is a legacy compatibility mode.
- `remote_responses_mcp` is only a scaffold and is not wired.
- At the time of this handoff, PostgreSQL runtime support had not been implemented. This statement is superseded: PostgreSQL runtime support, migrations, parity tests, and the historical transfer are complete. See `docs/postgresql-phase-4-runtime.md` through `docs/postgresql-phase-7-historical-transfer.md`.

Frontend local configuration:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Migration Procedure

1. **Capture the source state.** Save the source commit SHA, `git status --short`, and a file inventory. The current branch has important modifications and untracked files, so copying only tracked files or cloning the old remote will produce an incomplete application.
2. **Create the new directory and repository.** Initialize a fresh Git repository in `<NEW_DIRECTORY>`. Do not nest it inside the source repository.
3. **Copy the required migration set.** Preserve relative paths. Copy selected optional files only after applying the decisions above.
4. **Recreate ignored runtime directories.** At minimum, create `data/`. Do not copy caches or installed dependencies.
5. **Review repository hygiene before the first commit.** Confirm `.env`, database files, virtual environments, Node modules, frontend builds, old data, and generated outputs are absent from Git staging.
6. **Recreate Python dependencies.** Use Python 3.12 to create a new virtual environment and install `requirements.txt`.
7. **Recreate frontend dependencies.** Run `npm ci` inside `frontend/` using Node 22.
8. **Run the acceptance checks below.** Fix path/import assumptions rather than adding the old directory to `PYTHONPATH`.
9. **Initialize the new remote.** Add `<NEW_GIT_REMOTE>`, make a clean initial commit, and push only after reviewing the staged file list.
10. **Record provenance.** Add the original repository URL and source commit SHA to the migration commit message or a short provenance section in the new README.

## Acceptance Checks

Run from the new repository root unless otherwise noted.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q

cd frontend
npm ci
npm run build
```

Expected baseline from the source working tree on 2026-09-21:

- Python tests: **37 passed**
- Frontend production build: **successful**

Then perform a local smoke test:

```bash
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm run dev
```

Verify:

- The UI opens at `http://127.0.0.1:3000`.
- `GET /api/db-status` responds.
- `GET /api/openai-agent/config` reports the expected mode and storage configuration.
- A deterministic request can run without an OpenAI API key when suitable fixture/cache data exists.
- `responses_tools` fails clearly when no OpenAI key is configured and works when a valid key is supplied.
- The MCP server imports and exposes the preferred consolidated tools.
- No code or configuration still contains `/Users/patrick/Developer/nba` as a required runtime path.

Run the network-independent evaluation:

```bash
.venv/bin/python -m api.nba_agent.evaluation
```

Do not use the live evaluation or NBA ingestion as a required migration check unless network access and endpoint behavior are available; keep external-service validation separate from repository integrity.

## Docker and CI Checks

The repository includes:

- `api/Dockerfile` for the FastAPI backend
- `frontend/Dockerfile` for a Vite build served by nginx
- `.github/workflows/docker-images.yml` for tests, frontend build, and GHCR image builds

Validate both image builds after the local tests. Review the workflow’s registry/repository names after attaching the new Git remote; image names derive from the new GitHub repository identity.

The frontend image accepts `VITE_API_BASE_URL` at build time. Ensure the deployed frontend points to the deployed API and that CORS/runtime routing are explicitly configured for the selected Azure layout.

## Known Gaps: Preserve, Do Not Misrepresent

The repository does not yet fully implement the capstone definition of done. Migration success means preserving the current baseline, not claiming these items are finished.

- The custom harness does not yet expose the complete explicit run state, elapsed-time/token/cost budgets, bounded retry policy, and stopping-reason record described in the scope.
- Claim verification and adaptive investigation are not yet implemented as the two complete, inspectable loops required by the scope.
- The evaluation fixture is a useful start, but the planned three-configuration comparison, held-out set, repeatability runs, manual review, and reporting are incomplete.
- The UI has analysis functionality but does not yet constitute all three finished Analysis, Investigation, and Evaluation views.
- PostgreSQL application storage is now implemented end to end; schema migrations, runtime selection, operations, verification, and the historical transfer are recorded in the PostgreSQL phase documents.
- Azure infrastructure, secret management, monitoring, database provisioning, and deployment workflow are not complete.
- Background ingestion uses FastAPI in-process background tasks and local persisted job state; it is not yet a durable distributed job system.
- The remote MCP Responses mode is not wired.

Keep these as a prioritized post-migration backlog. Do not “fix” them during the mechanical move unless the task is explicitly expanded.

## Migration Completion Report

When finished, report:

- New absolute directory
- New remote URL
- Source commit SHA and whether uncommitted source changes were included
- Exact paths copied, omitted, archived, or renamed
- Whether the DuckDB cache was copied out of band or recreated empty
- Python test result
- Frontend build result
- Docker/CI validation result
- Any changed import paths, configuration, or documentation
- Any remaining migration blockers
- Confirmation that no secrets, `.env`, dependency directories, generated builds, or legacy databases were committed

The migration is complete only when the clean checkout in the new repository can recreate dependencies and pass the acceptance checks without depending on the old directory.

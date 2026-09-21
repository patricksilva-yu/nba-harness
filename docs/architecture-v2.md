# NBA Analyst Architecture V2

## Decision

The NBA domain service is the center of the application. HTTP, OpenAI Responses function tools, and MCP are adapters over that service. MCP is no longer an internal transport requirement.

## Request Flow

1. FastAPI resolves the requested game through `NBAService`.
2. Missing data is cached synchronously for an immediate question or through a persisted ingestion job.
3. Deterministic tools calculate game context and evidence packets.
4. In `responses_tools` mode, the Responses API receives four typed function tools and must return the structured analysis JSON schema.
5. Citation packet IDs are checked against packets produced by the domain service; invented IDs are discarded.
6. React renders structured fields and expandable evidence instead of parsing the answer as the source of truth.

## Boundaries

- `service.py`: NBA operations and evidence assembly.
- `responses_agent.py`: model orchestration and structured output.
- `mcp_server.py`: optional interoperability interface.
- `routes.py`: HTTP transport.
- `ingestion_jobs.py`: local background ingestion state.
- `db.py`: local DuckDB schema and explicit storage configuration.

## Storage

DuckDB remains the supported local analytical store. A shared deployed service should use PostgreSQL after completing the existing migration path. Setting the PostgreSQL backend without a database URL is an error; the application must never silently share a local DuckDB file in multi-user mode.

## Evaluation

Representative postgame cases live in `evals/postgame_cases.json`. Each case defines the intended route, acceptable required themes, forbidden claims, and minimum evidence coverage. This suite should grow before the tool surface or agent count grows.

## Compatibility

The granular MCP tools and the Agents SDK stdio mode remain temporarily available. New application work should use `responses_tools` and the four consolidated domain tools. Remove the legacy surface only after external MCP clients have migrated.

# MCP harness operations and design

Implemented 2026-09-23 against [Architecture V3](architecture-v3.md).

## Running

Activate `.venv`, install `requirements.txt`, configure `OPENAI_API_KEY` and
`NBA_OPENAI_MODEL` explicitly, and run `alembic upgrade head` before using
PostgreSQL. Revision `20260923_01` adds `harness_runs` and `20260923_02` adds
conversation links; startup never runs DDL against PostgreSQL. Existing local DuckDB databases are initialized through
their compatibility adapter.

`POST /api/ask` defaults to `mode: "mcp_harness"` and
`harness_configuration: "investigation"`. Example request:

```json
{
  "question": "Who won this game, and what was the final score?",
  "game_id": "0042500303",
  "mode": "mcp_harness",
  "harness_configuration": "investigation"
}
```

All harness runs are saved, regardless of the legacy `persist` option. The
legacy `max_evidence` option does not truncate harness citations: every cited
packet is returned. The response includes `analysis.headline`,
`analysis.claims`, citations, `analysis_run_id`, `conversation_id`,
`stop_reason`, usage and the complete observable trace. `GET /api/runs/{run_id}`
retrieves the durable record. The existing deterministic and direct Responses
modes remain explicitly labelled development prototypes.

The primary harness stores its Responses API calls in the OpenAI project logs
and emits an Agents SDK trace for each run, including streamed requests. The trace groups model decisions,
MCP calls, and fact-checks under the `NBA MCP Harness` workflow. The app's
**Show your work → Time & cost** panel displays the OpenAI trace ID, and the
saved run includes `openai_trace_id` for searching in OpenAI Logs. Select the
OpenAI project associated with the app's API key. OpenAI logging requires a
project whose data retention policy permits stored responses and traces; the
app's PostgreSQL run record remains the complete local audit trail.

### Traces page

The app's **Traces** page (`/traces`) is the developer view of every saved run.
It lists runs newest first with outcome, game, duration, tokens and turn/tool
counts, searchable by question or run ID and filterable by outcome, status and
conversation. `/traces/{run_id}` shows the run as a span tree with a timeline:
model decisions and fact-checks (with their full inputs and outputs, as a chat
view or JSON), MCP calls with arguments and results, verification and
investigation groups, and harness events such as rejected drafts. Selecting a
span updates the URL (`?span=`), so any step can be linked. The page reads the
existing run records through `GET /api/traces` and `GET /api/traces/{run_id}`;
it needs no separate tracing service or storage, and it includes runs saved
before it existed. Static hosting must rewrite unknown paths to `index.html`
(`frontend/public/staticwebapp.config.json` does this for Azure Static Web Apps).

### Streaming progress

`POST /api/ask/stream` accepts the same body as `/api/ask` (harness mode only)
and responds with server-sent events:

```text
event: step     data: {"sequence": 4, "kind": "mcp_call_completed", "name": "resolve_game", "game": {...}, ...}
event: step     data: {"sequence": 9, "kind": "verification", "findings": [...], ...}
event: result   data: {...the run as the UI renders it...}
```

Each `step` is sent only after that event is durably checkpointed, so the
stream never shows progress the run record lacks. Steps are compact public
views: model inputs, raw model output and full tool results stay in the trace
and are not streamed. `result` has the `/api/ask` shape without `trace`, plus
the same public `events`. An `error` event carries a generic message; raw
exception text is never streamed. Configuration errors and invalid follow-ups
fail with an ordinary HTTP status before streaming starts. Closing the
connection cancels the run, which is saved as `cancelled`.

The harness runs on the API's event loop for this endpoint. Checkpoint writes
are short synchronous storage calls, which is acceptable for the single-user
deployment; a multi-user deployment should move runs to a worker.

### Follow-up questions and conversations

Send `parent_run_id` with a completed run's `analysis_run_id` to ask a
follow-up. The new run joins the parent's conversation and stays on the
parent's game: it starts with that game, its cache status and its verified
evidence ledger already in place, and `resolve_game` is rejected. The model
receives up to five earlier turns (question, headline, claims) as context, not
as evidence; every claim must still cite a ledger packet, and inherited packets
keep `inherited_from` provenance. Each follow-up is verified independently, so
every run remains a complete evaluation unit. To ask about another game, start
a new conversation.

A missing parent returns 404, an unfinished one 409, and a `game_id` that
differs from the parent's game 400. `GET /api/conversations` lists recent
conversations by their opening question; `GET /api/conversations/{id}` returns
each run in order with its public events.

### Game flow

`GET /api/games/{game_id}/flow` returns the score margin (away team's
perspective) at every scoring change, including overtime, for the UI's
game-flow chart. Like the box-score route, it reads stored play-by-play
directly for display and is page context only; it is not agent evidence and cannot be cited.

The service is intended for the existing single-user deployment. Run retrieval
has the same access boundary as the rest of the API; it is not a public,
multi-tenant audit endpoint.

## Execution and evidence

The application starts a local stdio MCP server using the active Python
interpreter and configured storage backend. It discovers actual MCP schemas,
applies a five-tool versioned allowlist, hashes the approved schemas and exposes
those schemas to Responses. Function-call messages are model proposals;
execution always uses the MCP client. The harness never imports NBAService,
reads basketball tables, or substitutes direct calls on failure.

MCP schemas retain optional argument semantics (`strict: false` on the model
projection); the client validates arguments against the discovered JSON Schema
and rejects extra keys. Structured answers and verifier outputs use strict
JSON Schema. Results are checked against discovered output schemas, game scope,
packet identifiers and provenance before entering the ledger. The controller
requires resolve → ensure cache → evidence, and detail requests must identify a
previously received packet. Valid analysis sections come from the discovered
schema: `sections` is an enumerated, described list, so an invented section name
is rejected before it reaches MCP. MCP context calls save their packets on the server
so subsequent detail calls can retrieve them.

The ledger retains packet content, source, confidence, game, invocation
arguments, time received, and a pointer to the result event. Packet conflicts
are explicit failures; earlier evidence is not overwritten. Empty results,
repeated evidence and rejected calls contribute to the no-progress counter.
Three consecutive steps without progress stop the run. A successful resolve,
cache preparation, new packet or new detail constitutes progress.
After a failed fact-check, the next decision receives one compact copy of the
evidence ledger and review feedback, rather than the earlier full tool transcript.

## Answer contract

Contract version `mcp-harness-v2` adds a headline. A draft with claims must
include `headline`: one plain-language sentence with its own packet IDs. The
verifier receives it as the final indexed claim with role `headline` and must
also judge it a faithful, non-overstated summary; an unsupported headline is
revised like any other claim. Drafts without a headline are rejected with
feedback. Runs that stop without a supported answer return a null headline.
Runs recorded under `mcp-harness-v1` have no headline.

Each claim may also carry a `follow_up`: a question a fan would naturally ask
next about the same game, shown under that claim as a one-tap follow-up. The
model may attach one to at most three claims. Because a question can smuggle in
an unverified claim, the verifier returns `follow_up_ok` for every finding; a
follow-up survives only if its claim is supported and `follow_up_ok` is true in
the final review, and at most three are returned. A failed follow-up is dropped,
never repaired, and never changes its claim's classification. Unverified
(`basic`) answers return no follow-ups.

A supported result lists `analysis.removed_claims`: claims that a review
rejected and that are absent from the final answer, each with its
classification and the verifier's reason.

## Evidence tools (contract `mcp-harness-v3`)

The model works from overview to detail. Section descriptions travel in the MCP
schema, so the model sees what each returns and what it cannot answer.

| Tool / section | Returns |
| --- | --- |
| `periods` section | Points per period, score and leader at each break, each team's largest lead with its clock time, lead changes and ties |
| `runs` section | The top three scoring stretches with start/end clock, score and margin change |
| `snapshot`, `players`, `advanced`, `possessions`, `lineups` | Final score and traditional team box score, leading player lines, team efficiency, whole-game event counts, low-confidence rotation counts |
| `get_game_window(game_id, period, from_clock, to_clock, end_period)` | One packet for any stretch of game time: score before and after, points, shooting and turnovers per team, per-player points and shooting, and the plays (scoring plays and turnovers only for very long windows) |
| `get_evidence_detail` on a run | The run's plays plus per-player totals for the run |

All are computed from stored play-by-play and box scores; nothing is inferred
beyond the recorded scores and event types. Windows include events exactly at
their start clock. Contract `v3` added `get_game_window`, the `periods` section
and section descriptions; runs recorded under earlier versions used four tools.

## Configurations and verification limits

| Configuration | Behavior after the first cited draft |
| --- | --- |
| `basic` | Return with `answered_unverified`; no claim-verification pass |
| `verification` | Review and revise using the existing ledger; further MCP gathering is closed |
| `investigation` | Review, authorize bounded targeted MCP gathering for evidence gaps, revise and review again |

All configurations use the same model adapter, MCP server and approved tool set.
The verifier receives only the draft's indexed claims and cited ledger entries.
It must return one classification for every claim: supported, unsupported,
conflicting or insufficient. Missing citations and incomplete reviews cannot
approve an answer. Failed drafts, findings and revision instructions remain in
the trace. Only a fully supported reviewed draft returns `supported`; reaching
a limit returns an empty claim set with an explicit limitation. Basic answers
are clearly marked unverified.

The initial semantic verifier uses a separate model call. It can make mistakes
or share the generator's biases; `supported` means the configured checks passed,
not an independently proven truth. Controlled tests demonstrate repairs and
investigation, but held-out accuracy and comparative improvements still require
the capstone evaluation. Prompt instructions constrain tool-output injection
and require uncertainty about inferred/partial evidence; they are not a formal
semantic security guarantee.

## Budgets and recovery

Every field of `Limits` can be configured with `NBA_HARNESS_<UPPERCASE_FIELD>`.
The token preflight estimates tokens from request bytes and reserves space for
instructions and output; completed model calls are charged using the provider's
reported token usage. This keeps large game evidence from exhausting the run
budget solely because JSON byte length exceeds its token count.

| Field | Default |
| --- | ---: |
| `model_turns` (includes verifier requests) | 12 |
| `tool_calls` (includes actual retries) | 12 |
| `verification_passes` | 3 |
| `investigation_passes` | 2 |
| `retries` | 1 |
| `seconds` | 180 |
| `operation_seconds` | 45 |
| `total_tokens` | 200000 |
| `output_tokens` per request | 4000 |

The controller preflights each model request using a conservative UTF-8 byte
reservation plus output allowance, then accounts for API-reported token usage.
Unavailable usage is charged against the reservation and marked estimated.
Dollar accounting is enabled only with explicit `input_usd_per_million` and
`output_usd_per_million` rates for the selected model. Set `max_cost_usd` to
enforce a dollar budget; the configuration rejects a cap without both rates.
Without rates the estimate is `null`, never a misleading zero. Cached-input
discounts are not assumed. These are conservative application estimates, not a
provider billing guarantee.

Read-tool timeouts/OS transport failures get at most the configured retry count.
Ingestion is not automatically retried after an unknown outcome. Model errors
stop the run without automatic replay, with usage conservatively reserved.
SDK model retries are disabled so they cannot evade accounting. Malformed
arguments, duplicate calls and tool execution failures become structured
feedback. Tool results larger than 500 KB are rejected. The global deadline
also covers MCP initialization; cleanup/persistence may add a small overhead.

Terminal reasons include `supported`, `answered_unverified`,
`insufficient_evidence`, `no_progress`, `tool_limit`, `iteration_limit`,
`verification_limit`, `token_limit`, `cost_limit`, `time_limit`, `error`, and
`cancelled`. Investigation exhaustion closes additional gathering; remaining
revision/verification budgets still apply.

## Trace persistence and retention

Each event atomically checkpoints a run's JSON record through the storage
repository. No database connection stays open over a model/MCP network wait.
Started operations are saved before execution; results, rejected requests,
errors, retries, reviews and terminal decisions are saved afterward. The single
controller is the sole writer, and terminal records cannot be updated through
the repository. Storage failure fails the request rather than claiming a
durable success. An abrupt process kill leaves a `running` record with its last
checkpoint; it must not be interpreted as completed or automatically replayed.

Trace payloads contain user questions and basketball evidence. Credential-like
fields, configured secrets and credential-bearing URLs are redacted. Raw
exception messages and hidden/encrypted model reasoning are not persisted.
Model credentials are not passed to the NBA MCP subprocess. Responses storage
is disabled; encrypted reasoning items are used only in the transient model
conversation to support stateless continuation.

For this capstone, run records and compact tool evidence are retained through
evaluation and final reporting. Restrict database/backup access accordingly;
they are not covered by the separate 60-day `raw_responses` cleanup. Export any
required evaluation records before deliberately removing runs. Automatic run
retention and interrupted-run recovery are future operational work, not silent
startup mutations.

## Verification

`pytest -q` exercises real in-process MCP and real stdio MCP with scripted
model decisions, including a FastAPI-to-storage test. PostgreSQL integration
uses only the explicitly configured disposable database described in
[PostgreSQL development](postgresql-development.md). Tests cover migration
upgrade/downgrade and durable JSONB run records. `npm run build` checks the UI.

Live-model smoke tests require authorization to send the question and cached
NBA evidence to the configured model provider. Local protocol/behavior tests
do not measure live-model answer quality.

## Implementation sources

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling): application execution of model proposals, call/output pairing, strict-schema constraints.
- [OpenAI Agents SDK integrations](https://developers.openai.com/api/docs/guides/agents/integrations-observability): MCP runtime and observability options. V3 permits Responses as the decision runtime; the custom controller owns the loop.
- [MCP tool specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools): discovery, input/output schemas, structured results and separate protocol/execution errors.
- [FastMCP client](https://gofastmcp.com/clients/client): explicit session lifecycle and tool invocation. Implementation was also checked against installed FastMCP 3.3.1 signatures.
- [Codex tool registry](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/registry.rs): inspected as an example of centralized dispatch, accounting and trace boundaries; no Codex source was copied.

Sources consulted on 2026-09-23. The historical scope's initial SDK choice is
preserved; this implementation follows the runtime flexibility accepted in V3.

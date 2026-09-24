# NBA Analyst Architecture V3: MCP-First Harness

**Status:** Accepted

**Decision date:** 2026-09-23

**Supersedes:** [Architecture V2](architecture-v2.md)

**Implementation note (2026-09-23):** The primary `mcp_harness` path now
implements MCP discovery/execution, bounded control, evidence, verification,
investigation and durable traces. See [harness operations](harness.md) for the
implemented contracts, verification limitations and deployment requirements.
The transition sequence below remains the original design record.

## Research Question

> Can a custom harness improve how an agent selects, sequences, verifies, and
> stops using MCP tools?

This question defines the system boundary and the evaluation design. MCP is not
an optional interoperability layer in the target architecture. It is the
required interface between the agent harness and the basketball data tools in
every evaluated agent configuration.

## Decision

The custom Python harness owns the agent execution loop. The model may propose
an MCP tool call, but the harness governs whether and how the call is executed,
records the result, determines what remains unresolved, and decides whether to
continue, verify, investigate, recover, revise, or stop.

The harness is not valuable because it merely transports tool calls. It is
valuable because it governs MCP tool selection, evidence gathering,
verification, recovery, and stopping.

`NBAService` remains the transport-neutral basketball domain layer, but the
agent harness must not call it directly to retrieve basketball data. The MCP
server is the agent-facing boundary over that service. HTTP routes may still
call application services for non-agent operational features, and the harness
may persist its own run state through storage repositories; neither path may be
used to bypass MCP when gathering evidence for an agent answer.

## System Flow

```text
React UI
  -> FastAPI request boundary
  -> custom harness controller
  -> model proposes the next action
  -> harness policy and budget checks
  -> MCP client
  -> NBA MCP server
  -> NBAService
  -> storage repositories
  -> PostgreSQL
```

Results return through the same controlled path. The harness adds each MCP
result to the evidence ledger before another model or deterministic verification
step can use it.

## Architectural Invariants

1. Every model-driven basketball data or evidence request crosses the MCP
   boundary.
2. Every evaluated configuration uses the same MCP server, approved tool set,
   model family, source data, and question set unless a reported experiment
   deliberately varies one of them.
3. The harness owns execution limits and terminal stopping decisions; these are
   not left solely to model judgment.
4. MCP results are treated as untrusted structured input. The harness validates
   schemas, associates provenance, and records errors before using results.
5. Important factual and numerical claims must reference evidence obtained from
   MCP tools.
6. Tool failures, retries, verification failures, revisions, and stopping
   reasons are durable run events, not only log messages.
7. The harness never silently switches from MCP to a direct service or database
   call when an MCP operation fails.

## Harness Responsibilities

### Tool discovery and selection

- Establish an MCP client session and retrieve tool definitions from the NBA
  MCP server.
- Apply a versioned allowlist so an unexpected server capability is not exposed
  automatically.
- Present the approved MCP schemas to the model without maintaining a divergent
  handwritten tool contract.
- Validate tool names and arguments before execution. Invalid requests become
  explicit run events and structured feedback; arguments are not silently
  rewritten.

### Sequencing and run state

- Maintain the resolved game, current question, completed actions, evidence
  ledger, claims under review, unresolved issues, and prior failures.
- Decide whether a proposed call is relevant, redundant, or disallowed by the
  current state.
- Prevent duplicate or circular calls unless a bounded retry or deliberate
  re-check is recorded.
- Keep model turns, MCP calls, verification passes, and investigation passes
  within separate measurable budgets.

### Evidence gathering

- Normalize successful MCP results into evidence records with tool name,
  arguments, game scope, source, timestamps, confidence, and packet identifiers.
- Preserve missing, partial, inferred, and conflicting evidence as explicit
  states.
- Permit the answer generator and verifier to use only evidence present in the
  run ledger.

### Verification

- Identify the answer's important factual and numerical claims.
- Compare each claim with its cited evidence and classify it as supported,
  unsupported, conflicting, or insufficient.
- Revise, qualify, or remove failed claims, then verify the revised answer.
- Preserve the original claim, result, supporting packet identifiers, and any
  revision for inspection and evaluation.

### Investigation

- Convert an unresolved claim into a targeted evidence need rather than issuing
  an open-ended research request.
- Select the smallest relevant MCP call or sequence likely to resolve that need.
- Add the new result to the same evidence ledger and return to verification.
- Detect no-progress cycles, repeated evidence, and unavailable data.

### Recovery and stopping

- Apply bounded retries only to failures classified as transient and safe to
  retry.
- Record permanent tool errors, invalid results, timeouts, and model failures as
  structured states.
- Stop with one explicit terminal reason, such as `supported`,
  `insufficient_evidence`, `no_progress`, `tool_limit`, `iteration_limit`,
  `time_limit`, `cost_limit`, or `error`.
- Produce a qualified answer or refusal when limits are reached; never convert a
  failed investigation into unsupported certainty.

## MCP Tool Boundary

The preferred task-level MCP tools remain:

- `resolve_game`
- `ensure_game_data`
- `get_game_analysis_context`
- `get_evidence_detail`

**Update (2026-09-23):** contract `mcp-harness-v3` adds `get_game_window` for
evidence about a specific stretch of game time. See [harness operations](harness.md).

The MCP server owns the mapping from these stable capabilities to `NBAService`.
Granular compatibility tools may remain during migration, but the harness uses
only its versioned allowlist. Tool schemas and structured error contracts must
be tested independently of the model.

The model runtime may still be the OpenAI Responses API or Agents SDK. That
choice does not change the boundary: discovered and approved MCP capabilities
are the source of the model-facing tool definitions, and actual execution is
performed through the MCP client. A direct Python function with equivalent
behavior is not an acceptable substitute in capstone evaluation runs.

## Controlled Loops

```text
question
  -> select and call MCP tools
  -> draft answer from the evidence ledger
  -> verify claims
       -> supported: stop
       -> repairable wording: revise and verify again
       -> missing or conflicting evidence: investigate through MCP
  -> enforce no-progress and resource limits
  -> stop with a recorded reason
```

The verification loop decides whether the current answer is adequately
supported. The investigation loop decides which additional MCP evidence, if
any, is worth obtaining. The harness runs and stops both loops.

## Run Record and Observability

Each run must persist enough information to reconstruct the controlled process:

- configuration and version identifiers;
- model, prompt, MCP server, and tool-allowlist versions;
- question and resolved game scope;
- ordered model decisions and MCP calls;
- validated arguments, results, errors, retries, and durations;
- accumulated evidence and provenance;
- claims, verification classifications, and revisions;
- investigation reasons and outcomes;
- iteration, tool-call, elapsed-time, token, and estimated-cost usage;
- final answer, limitations, and stopping reason.

Secrets, authorization data, and raw credentials must never be stored in the run
record. Raw external responses remain subject to the documented retention and
redaction policy.

## Evaluation Design

The experiment compares harness behavior rather than transport choices. All
three configurations therefore use MCP:

1. **Basic MCP agent:** bounded MCP tool use without a claim-verification loop.
2. **MCP plus verification:** the same agent and MCP tools with claim checking
   and answer repair.
3. **MCP plus verification and investigation:** the same system with targeted
   follow-up MCP evidence gathering.

The independent variable is the added harness control. Questions, games, source
records, model settings, MCP server, and tool set remain fixed as far as
practical. Reported measures include factual accuracy, evidence support,
appropriate uncertainty, successful repair, tool efficiency, latency, token
usage, estimated cost, stopping behavior, and repeatability.

## Component Boundaries

- `harness/` (target): explicit controller, run state, policies, budgets,
  verification, investigation, recovery, and stopping.
- `mcp_server.py`: required agent-facing basketball capability boundary.
- MCP client adapter (target): session lifecycle, tool discovery, schema
  projection, invocation, and error normalization.
- `service.py`: transport-neutral basketball operations and evidence assembly
  behind MCP.
- `storage/`: PostgreSQL and local compatibility adapters plus repositories.
- `routes.py`: HTTP boundary that starts runs and retrieves run records.
- React UI: analysis, investigation trace, and evaluation views.

## Transition from V2

> **Update (2026-09-24):** The transition is complete. The direct Responses
> prototype, the deterministic agent, the Agents SDK modes and the MCP server's
> older granular tools have been removed; the harness is the only analysis
> path. The sequence below is preserved as the point-in-time plan.

The current repository still contains a direct Responses function-tool
prototype. It demonstrated typed tools, structured answers, and a shared domain
service, but it bypasses MCP and therefore cannot be the primary capstone path.

The migration sequence is:

1. Add an MCP client boundary with lifecycle and contract tests.
2. Route the custom harness's approved tool execution through that client.
3. Make the MCP-controlled harness the primary analysis mode.
4. Add verification, investigation, recovery, budgets, and durable run events.
5. Run behavioral parity checks against the prototype for representative games.
6. Retain the direct path only as a clearly labelled development comparator if
   it has evaluation value; otherwise remove it after MCP parity is established.
7. Assert in evaluation tests that every basketball evidence call was recorded
   as an MCP invocation.

Until this transition is complete, documentation and UI labels must distinguish
the direct-function prototype from the accepted MCP-first target architecture.

## Consequences

This design adds MCP session management, another explicit failure boundary, and
contract-version testing. In return, it makes the project internally coherent:
the harness is evaluated on its ability to govern real MCP tool use, the same
tool boundary is shared across configurations, and improvements cannot be
attributed to silently bypassing the protocol under study.

// Translates public harness events into the fan-facing step list.

const SECTIONS = {
  snapshot: 'the final score',
  periods: 'quarter-by-quarter scoring',
  advanced: 'team efficiency',
  runs: 'scoring runs',
  possessions: 'possession data',
  players: 'player lines',
  lineups: 'rotations',
}

export const STOP_TEXT = {
  supported: 'Every claim is backed by evidence',
  answered_unverified: 'Answered without a fact-check',
  insufficient_evidence: "The game data doesn't cover this question",
  no_progress: 'It kept hitting dead ends, so it stopped instead of guessing',
  tool_limit: 'It reached the limit on data lookups',
  iteration_limit: 'It reached the limit on thinking steps',
  verification_limit: 'It ran out of fact-check attempts',
  token_limit: 'It reached its size budget',
  cost_limit: 'It reached its cost budget',
  time_limit: 'It ran out of time',
  cancelled: 'You stopped it',
  error: 'Something went wrong',
}

const DRAFT_REJECTED = {
  missing_evidence: 'Some claims had no evidence behind them',
  missing_headline: 'It was missing a headline',
  invalid_answer_schema: 'It came back malformed',
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
const quarter = (p) => (p <= 4 ? `Q${p}` : p === 5 ? 'OT' : `${p - 4}OT`)

function windowLabel(args = {}) {
  let start = `${quarter(args.period)} ${args.from_clock ?? 'start'}`
  let end = `${quarter(args.end_period ?? args.period)} ${args.to_clock ?? '0:00'}`
  return `${start} → ${end}`
}

function sectionList(args) {
  let names = (args?.sections ?? []).map((s) => SECTIONS[s] ?? s)
  if (names.length <= 1) return names[0] ?? 'game data'
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

function activityFor(event) {
  if (event.kind === 'model_requested') return event.purpose === 'verification' ? 'Fact-checking the draft' : 'Thinking'
  if (event.kind !== 'mcp_call_started') return null
  return {
    resolve_game: 'Finding the game',
    ensure_game_data: 'Loading play-by-play and box scores',
    get_game_analysis_context: `Pulling ${sectionList(event.arguments)}`,
    get_game_window: `Looking closely at ${windowLabel(event.arguments)}`,
    get_evidence_detail: 'Checking the details behind a piece of evidence',
  }[event.name]
}

function stepFor(e) {
  switch (e.kind) {
    case 'run_started':
      return e.parent_run_id
        ? { title: 'Picked up from your last question', detail: `${plural(e.inherited_packets, 'piece')} of evidence already checked` }
        : null
    case 'mcp_discovered':
      return { title: 'Connected to the NBA data tools', detail: `${plural(e.tools?.length ?? 0, 'approved tool')}` }
    case 'mcp_call_completed':
      if (e.name === 'resolve_game') return { title: 'Found the game', detail: e.game?.label }
      if (e.name === 'ensure_game_data') return { title: 'Loaded play-by-play and box scores' }
      if (e.name === 'get_evidence_detail') return { title: 'Checked the plays behind a piece of evidence' }
      if (e.name === 'get_game_window') return { title: `Looked closely at ${windowLabel(e.arguments)}`, detail: 'Every play, plus who scored' }
      return { title: `Pulled ${sectionList(e.arguments)}`, detail: `${plural(e.evidence?.length ?? 0, 'piece')} of evidence` }
    case 'mcp_call_failed':
      return { title: 'A data lookup failed', detail: e.error, tone: 'warn' }
    case 'retry':
      return { title: 'Retrying that lookup', tone: 'warn' }
    case 'tool_rejected':
      return { title: "Skipped a lookup the rules don't allow", detail: e.error, tone: 'warn' }
    case 'answer_drafted':
      return e.claim_count
        ? { title: 'Wrote a draft', detail: `${plural(e.claim_count, 'claim')}${e.has_headline ? ' and a headline' : ''}` }
        : { title: 'Found nothing it could support', tone: 'warn' }
    case 'draft_rejected':
      return { title: 'Sent the draft back', detail: DRAFT_REJECTED[e.reason] ?? e.reason, tone: 'warn' }
    case 'verification': {
      let findings = e.findings ?? []
      let failed = findings.filter((f) => f.classification !== 'supported')
      return failed.length
        ? { title: `Fact-check: ${failed.length} of ${findings.length} need work`, detail: failed[0].reason, tone: 'warn' }
        : { title: `Fact-check: all ${findings.length} backed by evidence` }
    }
    case 'verification_failed':
      return { title: "The fact-check didn't complete", tone: 'warn' }
    case 'investigation_started':
      return { title: 'Looking for more data', detail: e.needs?.[0] }
    case 'investigation_completed':
      return e.new_packets
        ? { title: `Found ${plural(e.new_packets, 'new piece')} of evidence` }
        : { title: 'No new evidence turned up', tone: 'warn' }
    case 'revision_requested':
      return { title: 'Rewriting the draft' }
    case 'evidence_conflict':
      return { title: 'Two pieces of evidence disagreed', tone: 'warn' }
    case 'game_unresolved':
      return { title: "Couldn't tell which game you meant", tone: 'stop' }
    case 'model_error':
    case 'run_error':
      return { title: 'Something went wrong', tone: 'stop' }
    case 'run_stopped':
      return e.reason === 'supported' || e.reason === 'answered_unverified'
        ? { title: 'Done', detail: STOP_TEXT[e.reason] }
        : { title: 'Stopped', detail: STOP_TEXT[e.reason] ?? e.reason, tone: 'stop' }
    default:
      return null
  }
}

export function buildSteps(events) {
  let steps = []
  let activity = null
  for (let event of events) {
    let step = stepFor(event)
    if (step) steps.push({ ...step, at: event.elapsed_seconds ?? 0, event })
    let next = activityFor(event)
    if (next) activity = next
    else if (event.kind === 'model_response' || step) activity = null
  }
  return { steps, activity }
}

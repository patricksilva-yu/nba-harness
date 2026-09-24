export const OUTCOMES = {
  supported: ['Supported', 'green'],
  answered_unverified: ['Unverified', 'amber'],
  insufficient_evidence: ['Insufficient evidence', 'amber'],
  game_unresolved: ['Game unresolved', 'sky'],
  no_progress: ['No progress', 'orange'],
  iteration_limit: ['Turn limit', 'orange'],
  tool_limit: ['Tool limit', 'orange'],
  token_limit: ['Token limit', 'orange'],
  cost_limit: ['Cost limit', 'orange'],
  time_limit: ['Time limit', 'orange'],
  verification_limit: ['Verification limit', 'orange'],
  cancelled: ['Cancelled', 'zinc'],
  error: ['Error', 'red'],
}

export function outcome(trace) {
  if (trace.status === 'running') return ['Running', 'blue']
  return OUTCOMES[trace.stop_reason] ?? [trace.stop_reason ?? 'Unknown', 'zinc']
}

export function seconds(value) {
  if (value == null) return '–'
  if (value < 1) return `${Math.round(value * 1000)}ms`
  if (value < 60) return `${value.toFixed(value < 10 ? 2 : 1)}s`
  return `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`
}

export function tokens(value) {
  if (value == null) return '–'
  return value >= 10_000 ? `${(value / 1000).toFixed(1)}k` : value.toLocaleString()
}

export function relativeTime(iso) {
  if (!iso) return '–'
  let diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

export const absoluteTime = (iso) => (iso ? new Date(iso).toLocaleString() : '')
export const shortId = (id) => (id ? id.replace(/^harness_/, '').slice(0, 8) : '–')

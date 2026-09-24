import { supabase } from './supabase'

// Empty in development (Vite forwards /api); set for a separately hosted API.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

// The signed-in user's access token; supabase-js refreshes it before expiry.
async function accessToken({ refresh = false } = {}) {
  if (!supabase) return null
  let { data } = refresh ? await supabase.auth.refreshSession() : await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

async function request(path, options = {}, { retried = false } = {}) {
  let token = await accessToken({ refresh: retried })
  let headers = { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError("Can't reach the analysis service. Check that the API is running.", 0)
  }
  // A token can expire between the refresh check and the request: refresh once and retry.
  if (response.status === 401 && token && !retried) return request(path, options, { retried: true })
  if (!response.ok) {
    let detail = null
    try {
      detail = (await response.json()).detail
    } catch {
      // Non-JSON error bodies fall back to the status text.
    }
    throw new ApiError(typeof detail === 'string' ? detail : `Request failed (${response.status})`, response.status)
  }
  return response
}

async function getJSON(path, { signal } = {}) {
  return (await request(path, { signal })).json()
}

export const api = {
  me: () => getJSON('/api/me'),
  favoriteTeams: () => getJSON('/api/me/favorite-teams'),
  favoriteGames: () => getJSON('/api/me/favorite-games'),
  addFavoriteTeam: (team_abbr) => request('/api/me/favorite-teams', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ team_abbr }),
  }),
  removeFavoriteTeam: (abbr) => request(`/api/me/favorite-teams/${encodeURIComponent(abbr)}`, { method: 'DELETE' }),
  recentGames: () => getJSON('/api/recent-games?season_type=Auto&limit=8'),
  conversations: () => getJSON('/api/conversations?limit=20'),
  conversation: (id) => getJSON(`/api/conversations/${encodeURIComponent(id)}`),
  breakdown: (gameId) => getJSON(`/api/games/${encodeURIComponent(gameId)}/breakdown`),
  gameFlow: (gameId, options) => getJSON(`/api/games/${encodeURIComponent(gameId)}/flow`, options),
  traces: (filters, options) => {
    let query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== '' && v != null))
    return getJSON(`/api/traces?${query}`, options)
  },
  trace: (runId, options) => getJSON(`/api/traces/${encodeURIComponent(runId)}`, options),
}

// POST /api/ask/stream: calls onStep for each harness event and resolves with
// the final run. EventSource is GET-only, so the stream is read by hand.
export async function askStream(body, { onStep, signal }) {
  let response = await request('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  let reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    let { value, done } = await reader.read()
    if (done) break
    buffer += value
    let boundary
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      let block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let event = 'message'
      let data = ''
      for (let line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (!data) continue
      let payload = JSON.parse(data)
      if (event === 'step') onStep(payload)
      else if (event === 'result') return payload
      else if (event === 'error') throw new ApiError(payload.detail, 500)
    }
  }
  throw new ApiError('The connection closed before the answer was ready.', 0)
}

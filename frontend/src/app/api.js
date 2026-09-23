// Empty in development (Vite forwards /api); set for a separately hosted API.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, options)
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError("Can't reach the analysis service. Check that the API is running.", 0)
  }
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

export async function getJSON(path, { signal } = {}) {
  return (await request(path, { signal })).json()
}

export const api = {
  recentGames: () => getJSON('/api/recent-games?season_type=Auto&limit=8'),
  conversations: () => getJSON('/api/conversations?limit=20'),
  conversation: (id) => getJSON(`/api/conversations/${encodeURIComponent(id)}`),
  gameFlow: (gameId, options) => getJSON(`/api/games/${encodeURIComponent(gameId)}/flow`, options),
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

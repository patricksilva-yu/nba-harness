import { useCallback, useEffect, useRef, useState } from 'react'
import { Navbar, NavbarLabel, NavbarSection } from '../components/navbar'
import { api, askStream } from './api'
import { AppShell } from './AppShell'
import { useAuth } from './auth'
import { AppSidebar, BrandMark } from './AppSidebar'
import { Composer } from './Composer'
import { EmptyState } from './EmptyState'
import { formatGameDate, GameHeader } from './GameHeader'
import { Inspector } from './Inspector'
import { ReliabilityView } from './ReliabilityView'
import { navigate, useLocation } from './router'
import { TraceDetail } from './traces/TraceDetail'
import { TracesList } from './traces/TracesList'
import { firstRunWindow, Turn } from './Turn'

// Fans always get the full harness; ?config=basic|verification is for development.
const CONFIGURATION = ['basic', 'verification', 'investigation'].includes(new URLSearchParams(location.search).get('config'))
  ? new URLSearchParams(location.search).get('config')
  : 'investigation'

const NEW_CONVERSATION = { id: null, gameId: null, gameRow: null, turns: [], status: 'ready' }
const newKey = () => `turn-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

function turnFromRun(run) {
  let status = run.stop_reason === 'cancelled' ? 'cancelled' : run.status === 'running' ? 'error' : 'done'
  return {
    key: run.analysis_run_id,
    question: run.question,
    status,
    events: run.events ?? [],
    result: run,
    error: status === 'error' ? "This run was interrupted before it finished." : null,
  }
}

// Refetches when `version` changes: a finished run may have just cached the game.
function useGameFlow(gameId, version) {
  let [flow, setFlow] = useState(null)
  useEffect(() => {
    if (!gameId) return setFlow(null)
    let controller = new AbortController()
    api.gameFlow(gameId, { signal: controller.signal }).then(setFlow, () => {})
    return () => controller.abort()
  }, [gameId, version])
  return flow
}

function gameLabel(game) {
  let score = `${game.away} ${game.awayScore} @ ${game.home} ${game.homeScore}`
  return [score, game.stage, formatGameDate(game.date)].filter(Boolean).join(' · ')
}

function describeGame(gameId, flow, row, resolution) {
  if (!gameId) return null
  let stage = (seasonType, number) => (seasonType === 'Playoffs' ? (number ? `Playoffs · Game ${number}` : 'Playoffs') : null)
  let date = row?.game_date ?? resolution?.game_date
  let stageText = stage(row?.season_type ?? resolution?.season_type, resolution?.series_game_number)
  if (flow?.game_id === gameId && flow.status !== 'not_found') {
    return { away: flow.away_team_abbr, home: flow.home_team_abbr, awayScore: flow.away_score, homeScore: flow.home_score, date, stage: stageText }
  }
  if (row) return { away: row.away_team_abbr, home: row.home_team_abbr, awayScore: row.away_score, homeScore: row.home_score, date, stage: stageText }
  return null
}

function NoTraceAccess() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pt-[8vh] sm:px-6">
      <h1 className="text-lg/7 font-semibold text-zinc-950 dark:text-white">Traces are for the Postgame Desk team</h1>
      <p className="mt-2 text-sm/6 text-zinc-500 dark:text-zinc-400">Your account doesn't have access to run traces.</p>
    </div>
  )
}

export function App() {
  let route = useLocation()
  let { isAdmin } = useAuth()
  let [section, setView] = useState('ask')
  // Traces are URL-addressed (/traces, /traces/:runId); the other views are app state.
  let traceRoute = route.path.match(/^\/traces(?:\/([^/]+))?\/?$/)
  let view = traceRoute ? 'traces' : section
  let [games, setGames] = useState({ status: 'loading', items: [] })
  let [conversations, setConversations] = useState({ status: 'loading', items: [] })
  let [conversation, setConversation] = useState(NEW_CONVERSATION)
  let [panel, setPanel] = useState({ open: false, turnKey: null, tab: 'evidence', packetId: null, step: null })
  let abortRef = useRef(null)
  let busy = conversation.turns.some((t) => t.status === 'running')

  let refreshConversations = useCallback(() => {
    api.conversations().then(
      (data) => setConversations({ status: 'ok', items: data.conversations }),
      () => setConversations((c) => ({ ...c, status: 'error' }))
    )
  }, [])

  useEffect(() => {
    api.recentGames().then(
      (data) => setGames({ status: 'ok', items: data.games ?? [] }),
      () => setGames({ status: 'error', items: [] })
    )
    refreshConversations()
    // Also runs on sign-out, which unmounts the app.
    return () => abortRef.current?.abort()
  }, [refreshConversations])

  let latestResult = conversation.turns.findLast((t) => t.result)?.result
  let resolvedEvent = conversation.turns.flatMap((t) => t.events).findLast((e) => e.kind === 'mcp_call_completed' && e.game?.game_id)
  let gameId = conversation.gameId ?? latestResult?.game_id ?? resolvedEvent?.game.game_id ?? null
  let fetchedFlow = useGameFlow(gameId, conversation.turns.filter((t) => t.status === 'done').length)
  let flow = fetchedFlow?.game_id === gameId ? fetchedFlow : null
  let row = conversation.gameRow ?? games.items.find((g) => g.game_id === gameId)
  let game = describeGame(gameId, flow, row, latestResult?.resolution)

  let updateTurn = (key, change) =>
    setConversation((c) => ({ ...c, turns: c.turns.map((t) => (t.key === key ? { ...t, ...change(t) } : t)) }))

  async function ask(question, replaceKey) {
    if (busy) return
    let parent = conversation.turns.findLast((t) => t.status === 'done' && t.result?.status === 'completed')
    let body = { question, harness_configuration: CONFIGURATION }
    if (parent) body.parent_run_id = parent.result.analysis_run_id
    else if (gameId) body.game_id = gameId

    let key = newKey()
    let turn = { key, question, status: 'running', events: [], result: null, error: null }
    setConversation((c) => ({
      ...c,
      status: 'ready',
      turns: replaceKey ? c.turns.map((t) => (t.key === replaceKey ? turn : t)) : [...c.turns, turn],
    }))
    setPanel((p) => ({ ...p, open: false }))
    requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }))

    let controller = new AbortController()
    abortRef.current = controller
    try {
      let result = await askStream(body, {
        signal: controller.signal,
        onStep: (event) => {
          updateTurn(key, (t) => ({ events: [...t.events, event] }))
          if (event.kind === 'run_started') setConversation((c) => ({ ...c, id: c.id ?? event.conversation_id }))
        },
      })
      updateTurn(key, () => ({ status: 'done', result, events: result.events }))
      setConversation((c) => ({ ...c, id: c.id ?? result.conversation_id, gameId: c.gameId ?? result.game_id }))
      requestAnimationFrame(() => document.getElementById(`turn-${key}`)?.scrollIntoView({ behavior: 'smooth' }))
    } catch (error) {
      if (error.name === 'AbortError') updateTurn(key, () => ({ status: 'cancelled' }))
      else updateTurn(key, () => ({ status: 'error', error: error.message }))
    } finally {
      abortRef.current = null
      refreshConversations()
    }
  }

  function startConversation(next) {
    if (busy) return
    setView('ask')
    navigate('/')
    setPanel((p) => ({ ...p, open: false }))
    setConversation({ ...NEW_CONVERSATION, ...next })
  }

  // Picking a game for an unresolved question asks it again, now pinned to that game.
  function pickGame(game, question) {
    startConversation({ gameId: game.game_id, gameRow: game, pendingQuestion: question })
  }

  useEffect(() => {
    if (!conversation.pendingQuestion || !conversation.gameId || conversation.turns.length) return
    let question = conversation.pendingQuestion
    setConversation((c) => ({ ...c, pendingQuestion: null }))
    ask(question)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.pendingQuestion, conversation.gameId])

  async function openConversation(id) {
    if (busy || id === conversation.id) {
      navigate('/')
      return setView('ask')
    }
    startConversation({ id, status: 'loading' })
    try {
      let data = await api.conversation(id)
      let turns = data.runs.map(turnFromRun)
      setConversation({ ...NEW_CONVERSATION, id, turns, gameId: data.runs.findLast((r) => r.game_id)?.game_id ?? null })
    } catch (error) {
      setConversation({ ...NEW_CONVERSATION, id, status: 'error', error: error.message })
    }
  }

  let openPanel = (turnKey, tab, focus = {}) =>
    setPanel({ open: true, turnKey, tab, packetId: focus.packetId ?? null, step: focus.step ?? null })
  let panelTurn = conversation.turns.find((t) => t.key === panel.turnKey && t.result)
  let firstAnswered = conversation.turns.find((t) => t.status === 'done')?.key

  return (
    <AppShell
      navbar={
        <Navbar>
          <NavbarSection>
            <BrandMark className="size-6" />
            <NavbarLabel className="font-semibold">Postgame Desk</NavbarLabel>
          </NavbarSection>
        </Navbar>
      }
      sidebar={
        <AppSidebar
          view={view}
          games={games}
          conversations={conversations}
          currentGameId={conversation.turns.length ? null : conversation.gameId}
          currentConversationId={conversation.id}
          onView={(v) => {
            setView(v)
            navigate('/')
            setPanel((p) => ({ ...p, open: false }))
          }}
          onNewQuestion={() => startConversation({})}
          onSelectGame={(g) => startConversation({ gameId: g.game_id, gameRow: g })}
          onSelectConversation={openConversation}
        />
      }
      panelOpen={view === 'ask' && panel.open && !!panelTurn}
      onClosePanel={() => setPanel((p) => ({ ...p, open: false }))}
      panel={
        panelTurn && (
          <Inspector
            turn={panelTurn}
            tab={panel.tab}
            focusPacket={panel.packetId}
            focusStep={panel.step}
            onTab={(tab) => setPanel((p) => ({ ...p, tab, packetId: null, step: null }))}
            onClose={() => setPanel((p) => ({ ...p, open: false }))}
          />
        )
      }
    >
      {view === 'traces' ? (
        isAdmin === null ? null : !isAdmin ? (
          <NoTraceAccess />
        ) : traceRoute[1] ? (
          <TraceDetail key={traceRoute[1]} runId={decodeURIComponent(traceRoute[1])} params={route.params} />
        ) : (
          <TracesList params={route.params} />
        )
      ) : view === 'reliability' ? (
        <ReliabilityView />
      ) : (
        <>
          {game && <GameHeader game={game} />}
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-4 pt-7 pb-4 sm:px-6" aria-live="polite">
            {conversation.status === 'loading' && <p className="pt-[6vh] text-sm text-zinc-500">Loading conversation…</p>}
            {conversation.status === 'error' && (
              <p className="pt-[6vh] text-sm text-red-700 dark:text-red-400">Couldn't open that conversation. {conversation.error}</p>
            )}
            {conversation.status === 'ready' && conversation.turns.length === 0 && (
              <EmptyState
                wrongGameQuestion={conversation.wrongGameQuestion}
                game={game}
                recentGames={games.items}
                onAsk={(q) => ask(q)}
                onSelectGame={(g) => startConversation({ gameId: g.game_id, gameRow: g })}
              />
            )}
            {conversation.turns.map((turn) => (
              <Turn
                key={turn.key}
                turn={turn}
                gameLabel={turn.key === conversation.turns[0].key && game ? gameLabel(game) : null}
                onWrongGame={() => startConversation({ wrongGameQuestion: turn.question })}
                flow={flow}
                showChart={turn.key === (firstAnswered ?? conversation.turns[0]?.key) || Boolean(turn.result && firstRunWindow(turn.result))}
                activePacket={panel.open && panel.turnKey === turn.key ? panel.packetId : null}
                busy={busy}
                onOpenStep={(step) => openPanel(turn.key, 'steps', { step })}
                onCite={(packetId) => openPanel(turn.key, 'evidence', { packetId })}
                onShowWork={() => openPanel(turn.key, 'evidence')}
                onAsk={(q) => ask(q)}
                onPickGame={(g) => pickGame(g, turn.question)}
                onStop={() => abortRef.current?.abort()}
                onRetry={() => ask(turn.question, turn.key)}
              />
            ))}
          </div>
          {conversation.status !== 'loading' && (
            <Composer
              hint={
                conversation.turns.length && game
                  ? `Follow-ups stay on ${game.away} @ ${game.home}. For another game, start a New question.`
                  : null
              }
              disabled={busy}
              placeholder={
                conversation.turns.length ? 'Ask a follow-up…' : game ? `Ask about this game…` : 'Ask about any recent game…'
              }
              onSubmit={(question) => ask(question)}
            />
          )}
        </>
      )}
    </AppShell>
  )
}

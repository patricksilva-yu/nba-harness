import { ArrowPathIcon, ArrowUpRightIcon } from '@heroicons/react/16/solid'
import { useEffect, useState } from 'react'
import { Button } from '../components/button'
import { api } from './api'
import { GameFlowChart } from './GameFlowChart'

const number = (value) => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })
const shooting = (row, made, attempted) => row?.[made] == null || row?.[attempted] == null ? '—' : `${number(row[made])}/${number(row[attempted])}`

function TeamComparison({ rows, game }) {
  let away = rows.find((row) => row.team_side === 'away')
  let home = rows.find((row) => row.team_side === 'home')
  let stats = [
    ['Field goals', (r) => shooting(r, 'fgm', 'fga')],
    ['Three-pointers', (r) => shooting(r, 'fg3m', 'fg3a')],
    ['Free throws', (r) => shooting(r, 'ftm', 'fta')],
    ['Rebounds', (r) => number(r?.reb)],
    ['Assists', (r) => number(r?.ast)],
    ['Turnovers', (r) => number(r?.tov)],
  ]
  return (
    <section aria-labelledby="team-stats-heading">
      <h2 id="team-stats-heading" className="text-base/7 font-semibold text-zinc-950 dark:text-white">Team comparison</h2>
      <table className="mt-3 w-full text-sm/6 tabular-nums">
        <caption className="sr-only">Saved team box score</caption>
        <thead>
          <tr className="border-b border-zinc-950/10 dark:border-white/10">
            <th scope="col" className="py-2 text-left font-normal text-zinc-500">Stat</th>
            {[game.away_team_abbr, game.home_team_abbr].map((abbr) => (
              <th scope="col" key={abbr} className="py-2 text-right font-score font-bold text-zinc-950 dark:text-white">{abbr}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stats.map(([label, value]) => (
            <tr key={label} className="border-b border-zinc-950/5 last:border-0 dark:border-white/5">
              <th scope="row" className="py-2 text-left font-normal text-zinc-500 dark:text-zinc-400">{label}</th>
              <td className="py-2 text-right font-medium text-zinc-950 dark:text-white">{value(away)}</td>
              <td className="py-2 text-right font-medium text-zinc-950 dark:text-white">{value(home)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function GameOverview({ gameId, flow, onAsk }) {
  let [state, setState] = useState({ gameId: null, data: null, error: null })
  let [version, setVersion] = useState(0)
  useEffect(() => {
    let controller = new AbortController()
    setState({ gameId, data: null, error: null })
    api.gameOverview(gameId, { signal: controller.signal }).then(
      (data) => setState({ gameId, data, error: null }),
      (error) => { if (!controller.signal.aborted) setState({ gameId, data: null, error: error.message }) }
    )
    return () => controller.abort()
  }, [gameId, version])

  if (state.gameId !== gameId || (!state.data && !state.error)) {
    return <p role="status" className="py-6 text-sm/6 text-zinc-500">Loading saved game stats…</p>
  }
  if (state.error) return (
    <div className="space-y-3 py-4">
      <p role="alert" className="text-sm/6 text-zinc-600 dark:text-zinc-400">Couldn't load saved stats. {state.error}</p>
      <Button outline onClick={() => setVersion((v) => v + 1)}>Try again</Button>
    </div>
  )

  let { game, teams, players, stats_available: available, stats_updated_at: updated } = state.data
  let chart = flow?.game_id === gameId && flow.status === 'ok' && flow.points?.length > 1
  let updatedDate = updated ? new Date(updated) : null
  return (
    <div className="space-y-8 pb-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs/5 font-medium tracking-wider text-zinc-500 uppercase dark:text-zinc-400">Game desk</p>
          <h1 className="mt-1 text-2xl/8 font-semibold tracking-tight text-zinc-950 dark:text-white">{available ? 'The game, by the numbers.' : 'Final score saved.'}</h1>
          <p className="mt-2 max-w-lg text-sm/6 text-zinc-500 dark:text-zinc-400">
            {available ? 'Explore the saved stats, then ask about the moments that mattered.' : 'Only the final score is saved. Asking a question will also request the game’s detailed stats.'}
          </p>
        </div>
        <Button plain aria-label="Refresh saved game stats" onClick={() => setVersion((v) => v + 1)}>
          <ArrowPathIcon className="size-4" />
        </Button>
      </div>

      {chart && (
        <section aria-labelledby="scoring-flow-heading" className="rounded-xl bg-zinc-50 px-3 pt-4 pb-2 ring-1 ring-zinc-950/5 sm:px-5 dark:bg-white/[0.025] dark:ring-white/10">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 px-1">
            <h2 id="scoring-flow-heading" className="text-sm/6 font-semibold text-zinc-950 dark:text-white">How the lead moved</h2>
            <span className="text-xs/5 text-zinc-500">{game.away_team_abbr} above · {game.home_team_abbr} below</span>
          </div>
          <GameFlowChart flow={flow} />
        </section>
      )}

      {available && <TeamComparison rows={teams} game={game} />}

      {players.length > 0 && (
        <section aria-labelledby="scoring-leaders-heading">
          <h2 id="scoring-leaders-heading" className="text-base/7 font-semibold text-zinc-950 dark:text-white">Scoring leaders</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm/6 tabular-nums">
              <thead>
                <tr className="border-b border-zinc-950/10 text-xs text-zinc-500 dark:border-white/10">
                  <th scope="col" className="py-2 text-left font-normal">Player</th>
                  {['PTS', 'REB', 'AST'].map((stat) => <th scope="col" key={stat} className="px-2 py-2 text-right font-normal">{stat}</th>)}
                </tr>
              </thead>
              <tbody>
                {players.map((player) => (
                  <tr key={player.player_id} className="border-b border-zinc-950/5 last:border-0 dark:border-white/5">
                    <th scope="row" className="py-2.5 text-left font-medium text-zinc-950 dark:text-white">
                      {player.player_name}<span className="ml-2 text-xs font-normal text-zinc-500">{player.team_abbr}</span>
                    </th>
                    <td className="px-2 py-2.5 text-right font-score font-bold text-zinc-950 dark:text-white">{number(player.pts)}</td>
                    <td className="px-2 py-2.5 text-right text-zinc-600 dark:text-zinc-400">{number(player.reb)}</td>
                    <td className="px-2 py-2.5 text-right text-zinc-600 dark:text-zinc-400">{number(player.ast)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="border-t border-zinc-950/10 pt-5 dark:border-white/10" aria-labelledby="ask-game-heading">
        <h2 id="ask-game-heading" className="text-base/7 font-semibold text-zinc-950 dark:text-white">Go beyond the score</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {['What decided this game?', 'Which players made the biggest difference?'].map((question) => (
            <Button key={question} outline onClick={() => onAsk(question)}>{question}<ArrowUpRightIcon className="size-4" /></Button>
          ))}
        </div>
        <p className="mt-3 text-xs/5 text-zinc-500 dark:text-zinc-400">Questions generate an AI answer checked against the game data. Browsing these stats does not generate an answer.</p>
      </section>
      {updatedDate && !Number.isNaN(updatedDate.valueOf()) && <p className="text-xs/5 text-zinc-400">Stats saved {updatedDate.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>}
    </div>
  )
}

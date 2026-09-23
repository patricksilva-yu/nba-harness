import { team } from './teams'

function TeamScore({ abbr, score, won, reverse }) {
  return (
    <span className={`flex items-center gap-2 ${reverse ? 'flex-row-reverse' : ''}`}>
      <span className="rounded-[5px] px-1.5 py-0.5 font-score text-[13px]/4 font-bold tracking-wide text-white" style={{ background: team(abbr).color }}>
        {abbr}
      </span>
      <span
        className={`font-score text-[26px]/none tabular-nums ${won ? 'font-bold text-zinc-950 dark:text-white' : 'font-semibold text-zinc-400 dark:text-zinc-500'}`}
      >
        {score}
      </span>
    </span>
  )
}

export function formatGameDate(value) {
  if (!value) return null
  let date = new Date(`${String(value).slice(0, 10)}T12:00:00`)
  return Number.isNaN(date) ? null : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

// `game`: { away, home, awayScore, homeScore, date, stage }
export function GameHeader({ game }) {
  let awayWon = game.awayScore > game.homeScore
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-950/5 bg-white/85 backdrop-blur-md lg:rounded-t-lg dark:border-white/5 dark:bg-zinc-900/85">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 sm:px-6">
        <div
          className="flex items-center gap-3.5"
          aria-label={`Final score: ${team(game.away).name} ${game.awayScore}, ${team(game.home).name} ${game.homeScore}`}
        >
          <TeamScore abbr={game.away} score={game.awayScore} won={awayWon} />
          <span className="text-[13px] text-zinc-400">at</span>
          <TeamScore abbr={game.home} score={game.homeScore} won={!awayWon} reverse />
        </div>
        <div className="text-[13px] text-zinc-500 max-sm:w-full sm:ml-auto dark:text-zinc-400">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">Final</span>
          {[game.stage, formatGameDate(game.date)].filter(Boolean).map((part) => ` · ${part}`)}
        </div>
      </div>
    </header>
  )
}

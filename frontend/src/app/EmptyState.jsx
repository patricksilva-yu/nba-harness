import { team } from './teams'

function suggestionsFor(game) {
  let [winner, loser] = game.awayScore > game.homeScore ? [game.away, game.home] : [game.home, game.away]
  let w = team(winner).name
  let l = team(loser).name
  return [
    { question: `What decided this game?`, hint: 'Runs, efficiency and key players' },
    { question: `When did the ${w} take control?`, hint: 'Scoring runs and momentum swings' },
    { question: `Who was the best player on the floor?`, hint: 'Player lines and plus/minus' },
    { question: `Why couldn't the ${l} keep up?`, hint: 'Shooting, turnovers and rebounding' },
  ]
}

function Suggestion({ question, hint, onAsk }) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onAsk(question)}
        className="h-full w-full rounded-xl p-3.5 text-left ring-1 ring-zinc-950/10 transition hover:shadow-sm hover:ring-zinc-950/20 dark:ring-white/10 dark:hover:ring-white/20"
      >
        <span className="block text-[15px]/6 text-zinc-950 dark:text-white">{question}</span>
        {hint && <span className="mt-1 block text-[13px]/5 text-zinc-500 dark:text-zinc-400">{hint}</span>}
      </button>
    </li>
  )
}

export function EmptyState({ game, wrongGameQuestion, recentGames, onAsk, onSelectGame }) {
  if (game) {
    return (
      <div className="flex flex-col gap-5 pt-[6vh]">
        <p className="text-xs/5 font-semibold tracking-wider text-zinc-500 uppercase dark:text-zinc-400">
          {team(game.away).name} at {team(game.home).name}
        </p>
        <h2 className="text-2xl/8 font-semibold tracking-tight text-balance text-zinc-950 sm:text-[1.75rem]/9 dark:text-white">
          What do you want to know about this game?
        </h2>
        <p className="max-w-[52ch] text-base/7 text-zinc-500 dark:text-zinc-400">
          Ask anything about what happened on the floor. Every claim is checked against the play-by-play and box score
          before you see it.
        </p>
        <ul className="grid gap-2.5 sm:grid-cols-2">
          {suggestionsFor(game).map((s) => (
            <Suggestion key={s.question} {...s} onAsk={onAsk} />
          ))}
        </ul>
      </div>
    )
  }

  let latest = recentGames[0]
  return (
    <div className="flex flex-col gap-5 pt-[6vh]">
      {wrongGameQuestion && (
        <p className="rounded-lg bg-amber-400/15 px-3.5 py-2.5 text-sm/6 text-zinc-700 dark:bg-amber-400/10 dark:text-zinc-300">
          Pick the game you meant, then ask again: <span className="font-medium">“{wrongGameQuestion}”</span>. Naming the
          round or date, like “Game 5 of the Finals”, also helps.
        </p>
      )}
      <h2 className="text-2xl/8 font-semibold tracking-tight text-balance text-zinc-950 sm:text-[1.75rem]/9 dark:text-white">
        Ask about any recent game
      </h2>
      <p className="max-w-[52ch] text-base/7 text-zinc-500 dark:text-zinc-400">
        Name the teams in your question, or pick a game first. Every claim is checked against the play-by-play and box
        score before you see it.
      </p>
      {latest && (
        <ul className="grid gap-2.5 sm:grid-cols-2">
          <Suggestion
            question={`Why did the ${team(latest.away_score > latest.home_score ? latest.away_team_abbr : latest.home_team_abbr).name} win their last game?`}
            hint={latest.label}
            onAsk={onAsk}
          />
          <Suggestion question="Who had the biggest scoring run last night?" hint="Finds the game first" onAsk={onAsk} />
        </ul>
      )}
      {recentGames.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-xs/5 font-semibold tracking-wider text-zinc-500 uppercase dark:text-zinc-400">Or pick a game</p>
          <div className="flex flex-wrap gap-2">
            {recentGames.slice(0, 6).map((g) => (
              <button
                key={g.game_id}
                type="button"
                onClick={() => onSelectGame(g)}
                className="rounded-full px-3.5 py-1.5 text-sm/5 text-zinc-700 tabular-nums ring-1 ring-zinc-950/15 hover:bg-zinc-950/[0.03] hover:text-zinc-950 dark:text-zinc-300 dark:ring-white/15 dark:hover:bg-white/5 dark:hover:text-white"
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

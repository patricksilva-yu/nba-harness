import { ChevronRightIcon, StarIcon } from '@heroicons/react/20/solid'
import { StarIcon as StarOutlineIcon } from '@heroicons/react/24/outline'
import clsx from 'clsx'
import { useCallback, useEffect, useState } from 'react'
import { Badge } from '../components/badge'
import { Button } from '../components/button'
import { Heading, Subheading } from '../components/heading'
import { Text } from '../components/text'
import { api } from './api'
import { CONFERENCES, fullName } from './favorites-data'
import { formatGameDate } from './GameHeader'
import { team } from './teams'

function TeamMark({ abbr, className = 'size-10 text-[15px]' }) {
  return (
    <span
      className={clsx(className, 'grid shrink-0 place-items-center rounded-lg font-score font-bold tracking-wide text-white ring-1 ring-white/15 ring-inset')}
      style={{ background: team(abbr).color }}
      aria-hidden="true"
    >
      {abbr}
    </span>
  )
}

// A final from the followed team's side: result, score, opponent.
function perspective(game, abbr) {
  let home = game.home_team_abbr === abbr
  let [ours, theirs] = home ? [game.home_score, game.away_score] : [game.away_score, game.home_score]
  return {
    won: ours > theirs,
    score: `${ours}–${theirs}`,
    opponent: home ? game.away_team_abbr : game.home_team_abbr,
    venue: home ? 'vs' : '@',
  }
}

function Result({ won }) {
  return <Badge color={won ? 'green' : 'red'}>{won ? 'W' : 'L'}</Badge>
}

function TeamCard({ abbr, games, onSelectGame }) {
  let [latest, ...earlier] = games
  return (
    <section aria-label={fullName(abbr)} className="rounded-xl bg-white ring-1 ring-zinc-950/10 dark:bg-zinc-900 dark:ring-white/10">
      <div className="flex items-center gap-3 px-4 pt-4">
        <TeamMark abbr={abbr} />
        <Subheading>{fullName(abbr)}</Subheading>
      </div>

      {latest ? (
        <LatestGame abbr={abbr} game={latest} onSelect={() => onSelectGame(latest)} />
      ) : (
        <Text className="px-4 pt-3 pb-4">No finals in the database yet.</Text>
      )}

      {earlier.length > 0 && (
        <ul className="border-t border-zinc-950/5 px-2 py-1.5 dark:border-white/5">
          {earlier.map((game) => {
            let view = perspective(game, abbr)
            return (
              <li key={game.game_id}>
                <button
                  type="button"
                  onClick={() => onSelectGame(game)}
                  className="flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left text-sm/6 hover:bg-zinc-950/[2.5%] dark:hover:bg-white/5"
                >
                  <Result won={view.won} />
                  <span className="font-medium text-zinc-950 tabular-nums dark:text-white">{view.score}</span>
                  <span className="text-zinc-500 dark:text-zinc-400">
                    {view.venue} {view.opponent}
                  </span>
                  <span className="ml-auto text-xs text-zinc-500 dark:text-zinc-400">{formatGameDate(game.game_date)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function LatestGame({ abbr, game, onSelect }) {
  let view = perspective(game, abbr)
  return (
    <button type="button" onClick={onSelect} className="group block w-full px-4 pt-3 pb-4 text-left">
      <div className="text-xs/5 text-zinc-500 dark:text-zinc-400">
        Final{game.season_type === 'Playoffs' ? ' · Playoffs' : ''} · {formatGameDate(game.game_date)}
      </div>
      <div className="mt-1 flex items-center gap-3">
        <Result won={view.won} />
        <span className="font-score text-3xl/none font-bold text-zinc-950 tabular-nums dark:text-white">{view.score}</span>
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          {view.venue} {team(view.opponent).name}
        </span>
      </div>
      <div className="mt-3 flex items-center gap-1 text-sm/6 font-medium text-zinc-950 dark:text-white">
        Read the breakdown
        <ChevronRightIcon className="size-4 text-zinc-400 transition group-hover:translate-x-0.5" />
      </div>
    </button>
  )
}

function TeamPicker({ selected, onToggle, onDone, first }) {
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Heading>{first ? 'Pick your teams' : 'Your teams'}</Heading>
          <Text className="mt-1">Star the teams you follow. Their latest games show up on your home page.</Text>
        </div>
        <Button onClick={onDone} disabled={!selected.length}>
          Done
        </Button>
      </div>
      {CONFERENCES.map((conference) => (
        <section key={conference.name} className="mt-8">
          <Subheading level={3} className="mb-3">
            {conference.name}
          </Subheading>
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {conference.teams.map(([abbr, name]) => {
              let on = selected.includes(abbr)
              return (
                <li key={abbr}>
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => onToggle(abbr)}
                    className={clsx(
                      'flex w-full items-center gap-3 rounded-lg p-2 text-left ring-1 transition',
                      on
                        ? 'bg-amber-50 ring-amber-400/60 dark:bg-amber-400/10 dark:ring-amber-400/40'
                        : 'ring-zinc-950/10 hover:ring-zinc-950/20 dark:ring-white/10 dark:hover:ring-white/20'
                    )}
                  >
                    <TeamMark abbr={abbr} className="size-8 text-[13px]" />
                    <span className="flex-1 text-sm/6 font-medium text-zinc-950 dark:text-white">{name}</span>
                    {on ? (
                      <StarIcon className="size-5 text-amber-400" />
                    ) : (
                      <StarOutlineIcon className="size-5 text-zinc-400" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </>
  )
}

export function Home({ onSelectGame }) {
  let [teams, setTeams] = useState(null)
  let [games, setGames] = useState([])
  // null, or 'setup' on a first visit with no teams, or 'edit'.
  let [picker, setPicker] = useState(null)
  let [error, setError] = useState(null)

  let loadGames = useCallback(() => api.favoriteGames().then((data) => setGames(data.games)), [])

  useEffect(() => {
    Promise.all([api.favoriteTeams(), loadGames()]).then(
      ([data]) => {
        setTeams(data.teams)
        if (!data.teams.length) setPicker('setup')
      },
      (reason) => setError(reason.message)
    )
  }, [loadGames])

  // The star flips at once; a failed save flips just that team back.
  async function toggle(abbr) {
    let on = !teams.includes(abbr)
    let flip = (add) => setTeams((current) => (add ? [...current, abbr] : current.filter((t) => t !== abbr)))
    setError(null)
    flip(on)
    try {
      await (on ? api.addFavoriteTeam(abbr) : api.removeFavoriteTeam(abbr))
    } catch (reason) {
      flip(!on)
      setError(reason.message)
    }
  }

  function done() {
    setPicker(null)
    loadGames().catch((reason) => setError(reason.message))
  }

  if (teams === null) {
    return error ? <Text className="px-6 pt-10">Couldn't load your teams. {error}</Text> : null
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pt-8 pb-12 sm:px-6">
      {error && (
        <p role="alert" className="mb-4 text-sm/6 text-red-600 dark:text-red-500">
          {error}
        </p>
      )}
      {picker ? (
        <TeamPicker selected={teams} onToggle={toggle} onDone={done} first={picker === 'setup'} />
      ) : (
        <>
          <div className="flex items-center justify-between gap-4">
            <Heading>Your teams</Heading>
            <Button outline onClick={() => setPicker('edit')}>
              Edit teams
            </Button>
          </div>
          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
            {teams.map((abbr) => (
              <TeamCard key={abbr} abbr={abbr} games={games.filter((g) => g.team_abbr === abbr)} onSelectGame={onSelectGame} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

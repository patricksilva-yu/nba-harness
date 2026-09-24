import * as Headless from '@headlessui/react'
import { ArrowRightIcon, PlusIcon, StarIcon, XMarkIcon } from '@heroicons/react/20/solid'
import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { useAuth } from './auth'
import { NBA_TEAMS } from './favorites-data'
import { formatGameDate } from './GameHeader'
import { team } from './teams'

const nameByAbbr = Object.fromEntries(NBA_TEAMS.map(({ abbr, name }) => [abbr, name]))

function TeamBadge({ abbr, large = false }) {
  return (
    <span
      className={`grid shrink-0 place-items-center rounded-xl font-score font-bold tracking-wide text-white ${large ? 'size-14 text-2xl' : 'size-9 text-base'}`}
      style={{ background: team(abbr).color }}
    >
      {abbr}
    </span>
  )
}

export function Home({ onSelectGame }) {
  let { user } = useAuth()
  let [favorites, setFavorites] = useState({ status: 'loading', teams: [] })
  let [games, setGames] = useState({ status: 'loading', items: [] })
  let [open, setOpen] = useState(false)
  let [query, setQuery] = useState('')
  let [working, setWorking] = useState(null)
  let [error, setError] = useState('')

  let refresh = useCallback(async () => {
    try {
      let [favoriteData, gameData] = await Promise.all([api.favoriteTeams(), api.favoriteGames()])
      setFavorites({ status: 'ok', teams: favoriteData.teams })
      setGames({ status: 'ok', items: gameData.games })
    } catch (reason) {
      setFavorites((current) => ({ ...current, status: 'error' }))
      setGames((current) => ({ ...current, status: 'error' }))
      setError(reason.message)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh, user?.id])

  async function add(abbr) {
    setWorking(abbr)
    setError('')
    try {
      await api.addFavoriteTeam(abbr)
      await refresh()
      setOpen(false)
      setQuery('')
    } catch (reason) {
      setError(reason.message)
    } finally {
      setWorking(null)
    }
  }

  async function remove(abbr) {
    setWorking(abbr)
    setError('')
    try {
      await api.removeFavoriteTeam(abbr)
      await refresh()
    } catch (reason) {
      setError(reason.message)
    } finally {
      setWorking(null)
    }
  }

  let available = NBA_TEAMS.filter(({ abbr, name }) =>
    !favorites.teams.includes(abbr) && `${name} ${abbr}`.toLowerCase().includes(query.trim().toLowerCase())
  )

  return (
    <div className="min-h-full bg-[#f8f7f3] text-zinc-950 dark:bg-zinc-900 dark:text-white lg:rounded-lg">
      <div className="relative overflow-hidden border-b border-zinc-200 bg-[#17251f] px-5 py-11 text-white sm:px-9 sm:py-14 lg:rounded-t-lg">
        <div className="pointer-events-none absolute -top-28 -right-12 size-96 rounded-full border border-white/10" />
        <div className="pointer-events-none absolute -top-14 right-2 size-72 rounded-full border border-white/10" />
        <div className="relative mx-auto max-w-5xl">
          <p className="mb-5 text-[11px] font-bold tracking-[.22em] text-[#b9d3bd] uppercase">Your postgame desk</p>
          <h1 className="max-w-2xl font-score text-5xl leading-[.92] font-bold tracking-tight sm:text-7xl">The games that<br />matter to you.</h1>
          <p className="mt-5 max-w-lg text-sm/6 text-[#d5dfd7]">Follow your NBA teams to keep their final scores and game breakdowns close at hand.</p>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-5 py-9 sm:px-9 sm:py-12">
        {error && <p role="alert" className="mb-6 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>}

        <section aria-labelledby="favorites-heading">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="mb-1 text-[11px] font-bold tracking-[.18em] text-[#657e6b] uppercase">01 / Your lineup</p>
              <h2 id="favorites-heading" className="font-score text-3xl font-bold sm:text-4xl">Favorite teams</h2>
            </div>
            <button type="button" onClick={() => { setError(''); setOpen(true) }} className="inline-flex items-center gap-2 rounded-lg bg-[#17251f] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#344c3c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#588869] dark:bg-white dark:text-zinc-950">
              <PlusIcon className="size-4" /> Add another team
            </button>
          </div>

          {favorites.status === 'loading' && <p className="py-10 text-sm text-zinc-500">Loading your teams…</p>}
          {favorites.status === 'error' && <button type="button" onClick={refresh} className="text-sm font-semibold underline">Retry loading your teams</button>}
          {favorites.status === 'ok' && favorites.teams.length === 0 && (
            <div className="rounded-2xl border border-dashed border-[#b9c9bb] bg-white px-6 py-12 text-center dark:border-zinc-700 dark:bg-zinc-800">
              <StarIcon className="mx-auto size-8 text-[#62816a]" />
              <h3 className="mt-4 font-score text-2xl font-bold">Start with your team</h3>
              <p className="mx-auto mt-2 max-w-sm text-sm/6 text-zinc-500 dark:text-zinc-400">Choose a team and this page will keep its recent games in view.</p>
              <button type="button" onClick={() => setOpen(true)} className="mt-6 rounded-lg bg-[#17251f] px-5 py-2.5 text-sm font-semibold text-white dark:bg-white dark:text-zinc-950">Choose a team</button>
            </div>
          )}
          {favorites.status === 'ok' && favorites.teams.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {favorites.teams.map((abbr) => (
                <div key={abbr} className="flex items-center gap-4 rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-700 dark:bg-zinc-800">
                  <TeamBadge abbr={abbr} large />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold">{nameByAbbr[abbr]}</div>
                    <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">Following · NBA</div>
                  </div>
                  <button type="button" disabled={working === abbr} onClick={() => remove(abbr)} aria-label={`Remove ${nameByAbbr[abbr]} from favorites`} title="Remove favorite" className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-50 dark:hover:bg-zinc-700 dark:hover:text-white"><XMarkIcon className="size-4" /></button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="mt-12 border-t border-zinc-200 pt-8 dark:border-zinc-700" aria-labelledby="games-heading">
          <p className="mb-1 text-[11px] font-bold tracking-[.18em] text-[#657e6b] uppercase">02 / Around your teams</p>
          <h2 id="games-heading" className="font-score text-3xl font-bold sm:text-4xl">Recent finals</h2>
          <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">Select a game to ask for an evidence-backed breakdown.</p>
          {games.status === 'loading' && <p className="mt-7 text-sm text-zinc-500">Loading games…</p>}
          {games.status === 'ok' && games.items.length === 0 && (
            <p className="mt-7 rounded-xl border border-zinc-200 bg-white px-5 py-6 text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800">{favorites.teams.length ? 'No completed games for your teams are in the database yet.' : 'Your teams’ games will appear here once you choose a favorite.'}</p>
          )}
          {games.status === 'ok' && games.items.length > 0 && (
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {games.items.map((game) => (
                <button type="button" key={game.game_id} onClick={() => onSelectGame(game)} className="group rounded-2xl border border-zinc-200 bg-white p-5 text-left transition hover:border-[#7a9d81] hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#588869] dark:border-zinc-700 dark:bg-zinc-800">
                  <div className="mb-4 flex items-center justify-between text-[11px] font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400"><span>Final · {game.season_type}</span><span>{formatGameDate(game.game_date)}</span></div>
                  {[['away_team_abbr', 'away_score'], ['home_team_abbr', 'home_score']].map(([abbrKey, scoreKey]) => (
                    <div key={abbrKey} className="flex items-center gap-3 py-1.5"><TeamBadge abbr={game[abbrKey]} /><span className="min-w-0 flex-1 truncate text-sm font-semibold">{nameByAbbr[game[abbrKey]] ?? game[abbrKey]}</span><span className="font-score text-2xl font-bold tabular-nums">{game[scoreKey]}</span></div>
                  ))}
                  <div className="mt-4 flex items-center gap-1 border-t border-zinc-100 pt-3 text-xs font-semibold text-[#42674a] dark:border-zinc-700 dark:text-[#9cc3a5]">Ask about this game <ArrowRightIcon className="size-3.5 transition group-hover:translate-x-1" /></div>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <Headless.Dialog open={open} onClose={setOpen} className="relative z-50">
        <Headless.DialogBackdrop className="fixed inset-0 bg-zinc-950/60" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Headless.DialogPanel className="flex max-h-[min(85vh,680px)] w-full max-w-lg flex-col rounded-2xl bg-white p-5 shadow-2xl dark:bg-zinc-900 sm:p-7">
            <div className="flex items-start justify-between gap-4"><div><Headless.DialogTitle className="font-score text-3xl font-bold">Add a team</Headless.DialogTitle><p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Search the NBA and choose a favorite.</p></div><button type="button" onClick={() => setOpen(false)} aria-label="Close team picker" className="rounded-lg p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800"><XMarkIcon className="size-5" /></button></div>
            <label htmlFor="team-search" className="mt-6 text-xs font-semibold text-zinc-600 dark:text-zinc-300">Search teams</label>
            <input id="team-search" autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. Toronto Raptors" className="mt-2 rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-sm outline-none focus:border-[#588869] dark:border-zinc-700 dark:bg-zinc-800" />
            <div className="mt-4 overflow-y-auto border-t border-zinc-100 dark:border-zinc-800">
              {available.length === 0 && <p className="py-8 text-center text-sm text-zinc-500">No more teams match that search.</p>}
              {available.map(({ abbr, name }) => <button type="button" key={abbr} disabled={!!working} onClick={() => add(abbr)} className="flex w-full items-center gap-3 border-b border-zinc-100 py-2.5 text-left hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-800 dark:hover:bg-zinc-800"><TeamBadge abbr={abbr} /><span className="flex-1 text-sm font-medium">{name}</span><PlusIcon className="size-4 text-zinc-400" /></button>)}
            </div>
          </Headless.DialogPanel>
        </div>
      </Headless.Dialog>
    </div>
  )
}

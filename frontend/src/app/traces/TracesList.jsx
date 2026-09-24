import { ArrowPathIcon, MagnifyingGlassIcon, XMarkIcon } from '@heroicons/react/16/solid'
import { useEffect, useState } from 'react'
import { Badge } from '../../components/badge'
import { Button } from '../../components/button'
import { Heading } from '../../components/heading'
import { Input, InputGroup } from '../../components/input'
import { Select } from '../../components/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/table'
import { api } from '../api'
import { navigate } from '../router'
import { absoluteTime, OUTCOMES, outcome, relativeTime, seconds, shortId, tokens } from './format'

const PAGE = 50

function withParams(params, change) {
  let next = new URLSearchParams(params)
  for (let [key, value] of Object.entries(change)) value ? next.set(key, value) : next.delete(key)
  if (!('offset' in change)) next.delete('offset')
  let query = next.toString()
  return `/traces${query ? `?${query}` : ''}`
}

export function TracesList({ params }) {
  let query = params.toString()
  let filters = {
    q: params.get('q') ?? '',
    stop_reason: params.get('stop_reason') ?? '',
    status: params.get('status') ?? '',
    conversation_id: params.get('conversation_id') ?? '',
    offset: Number(params.get('offset')) || 0,
  }
  let [search, setSearch] = useState(filters.q)
  let [state, setState] = useState({ status: 'loading', traces: [], total: 0 })
  let [reload, setReload] = useState(0)

  useEffect(() => setSearch(filters.q), [filters.q])

  // Debounced search keeps the URL (and so back/forward and sharing) in sync.
  useEffect(() => {
    if (search === filters.q) return
    let timer = setTimeout(() => navigate(withParams(params, { q: search.trim() }), { replace: true }), 300)
    return () => clearTimeout(timer)
  }, [search]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let controller = new AbortController()
    setState((s) => ({ ...s, status: s.traces.length ? 'refreshing' : 'loading' }))
    api.traces({ ...filters, limit: PAGE }, { signal: controller.signal }).then(
      (data) => setState({ status: 'ok', traces: data.traces, total: data.total }),
      (error) => error.name !== 'AbortError' && setState({ status: 'error', traces: [], total: 0, error: error.message })
    )
    return () => controller.abort()
  }, [query, reload]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while any listed run is still in progress.
  let running = state.traces.some((t) => t.status === 'running')
  useEffect(() => {
    if (!running) return
    let timer = setInterval(() => setReload((n) => n + 1), 3000)
    return () => clearInterval(timer)
  }, [running])

  let first = state.total ? filters.offset + 1 : 0
  let last = Math.min(filters.offset + PAGE, state.total)

  return (
    <div className="flex flex-col gap-5 px-4 py-6 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Heading>Traces</Heading>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Every harness run: model decisions, MCP lookups and fact-checks, step by step.
          </p>
        </div>
        <Button outline onClick={() => setReload((n) => n + 1)} aria-label="Refresh">
          <ArrowPathIcon className={state.status === 'refreshing' ? 'animate-spin' : ''} />
          Refresh
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-60 flex-1">
          <InputGroup>
            <MagnifyingGlassIcon data-slot="icon" />
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search questions or paste a run ID"
              aria-label="Search traces"
            />
          </InputGroup>
        </div>
        <div className="w-48">
          <Select
            aria-label="Outcome"
            value={filters.stop_reason}
            onChange={(e) => navigate(withParams(params, { stop_reason: e.target.value }))}
          >
            <option value="">All outcomes</option>
            {Object.entries(OUTCOMES).map(([value, [label]]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </Select>
        </div>
        <div className="w-40">
          <Select aria-label="Status" value={filters.status} onChange={(e) => navigate(withParams(params, { status: e.target.value }))}>
            <option value="">Any status</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </Select>
        </div>
      </div>

      {filters.conversation_id && (
        <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          Showing one conversation
          <Badge color="blue" className="font-mono">{shortId(filters.conversation_id)}</Badge>
          <button
            type="button"
            onClick={() => navigate(withParams(params, { conversation_id: '' }))}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium hover:bg-zinc-950/5 dark:hover:bg-white/10"
          >
            <XMarkIcon className="size-3.5" /> Clear
          </button>
        </div>
      )}

      {state.status === 'error' && <p className="text-sm text-red-700 dark:text-red-400">Couldn't load traces. {state.error}</p>}
      {state.status === 'loading' && <p className="text-sm text-zinc-500">Loading traces…</p>}
      {state.status !== 'loading' && state.status !== 'error' && state.traces.length === 0 && (
        <p className="text-sm text-zinc-500">No runs match these filters.</p>
      )}

      {state.traces.length > 0 && (
        <Table dense className="[--gutter:--spacing(4)] sm:[--gutter:--spacing(8)]">
          <TableHead>
            <TableRow>
              <TableHeader>Time</TableHeader>
              <TableHeader>Question</TableHeader>
              <TableHeader>Outcome</TableHeader>
              <TableHeader>Game</TableHeader>
              <TableHeader className="text-right">Duration</TableHeader>
              <TableHeader className="text-right">Tokens in / out</TableHeader>
              <TableHeader className="text-right">Turns · tools</TableHeader>
              <TableHeader>Conversation</TableHeader>
              <TableHeader>Run</TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {state.traces.map((t) => {
              let [label, color] = outcome(t)
              return (
                <TableRow key={t.run_id} href={`/traces/${encodeURIComponent(t.run_id)}`} title={t.question}>
                  <TableCell className="text-zinc-500 dark:text-zinc-400">
                    <span title={absoluteTime(t.created_at)}>{relativeTime(t.created_at)}</span>
                  </TableCell>
                  <TableCell className="max-w-sm truncate font-medium">
                    {t.parent_run_id && <span className="mr-1.5 text-zinc-400" title="Follow-up question">↳</span>}
                    {t.question}
                  </TableCell>
                  <TableCell><Badge color={color}>{label}</Badge></TableCell>
                  <TableCell className="max-w-48 truncate text-zinc-500 dark:text-zinc-400">{t.game_label ?? t.game_id ?? '–'}</TableCell>
                  <TableCell className="text-right tabular-nums">{seconds(t.duration_seconds)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {tokens(t.input_tokens)} <span className="text-zinc-400">/</span> {tokens(t.output_tokens)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {t.model_turns ?? '–'} <span className="text-zinc-400">·</span> {t.tool_calls ?? '–'}
                  </TableCell>
                  <TableCell>
                    {t.conversation_id && (
                      <button
                        type="button"
                        className="relative z-10 rounded-md px-1 font-mono text-xs text-blue-700 hover:bg-blue-500/10 dark:text-blue-400"
                        title="Show every run in this conversation"
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          navigate(withParams(new URLSearchParams(), { conversation_id: t.conversation_id }))
                        }}
                      >
                        {shortId(t.conversation_id)}
                      </button>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-zinc-500">{shortId(t.run_id)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      {state.total > PAGE && (
        <div className="flex items-center justify-between text-sm text-zinc-500 dark:text-zinc-400">
          <span className="tabular-nums">{first}–{last} of {state.total}</span>
          <div className="flex gap-2">
            <Button outline disabled={filters.offset === 0} onClick={() => navigate(withParams(params, { offset: String(Math.max(0, filters.offset - PAGE)) }))}>
              Previous
            </Button>
            <Button outline disabled={last >= state.total} onClick={() => navigate(withParams(params, { offset: String(filters.offset + PAGE) }))}>
              Next
            </Button>
          </div>
        </div>
      )}
      {state.total > 0 && state.total <= PAGE && (
        <p className="text-xs text-zinc-500 tabular-nums">{state.total} {state.total === 1 ? 'run' : 'runs'}</p>
      )}
    </div>
  )
}

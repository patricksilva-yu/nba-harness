import { ArrowLeftIcon, ChevronRightIcon } from '@heroicons/react/16/solid'
import clsx from 'clsx'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '../../components/badge'
import { Link } from '../../components/link'
import { api } from '../api'
import { navigate } from '../router'
import { CopyButton, JsonView } from './JsonView'
import { absoluteTime, outcome, seconds, shortId, tokens } from './format'

const TYPES = {
  run: ['Run', 'bg-zinc-900 dark:bg-white', 'zinc'],
  llm: ['LLM', 'bg-violet-500', 'violet'],
  tool: ['Tool', 'bg-sky-500', 'sky'],
  verify: ['Verify', 'bg-emerald-500', 'emerald'],
  investigation: ['Investigate', 'bg-amber-500', 'amber'],
  event: ['Event', 'bg-zinc-400', 'zinc'],
}
const STATUS = { ok: null, warning: ['Check failed', 'amber'], error: ['Error', 'red'], running: ['Running', 'blue'] }

function buildTree(spans) {
  let children = new Map()
  for (let span of spans) {
    let list = children.get(span.parent_id) ?? []
    list.push(span)
    children.set(span.parent_id, list)
  }
  return children
}

// Rows in display order, honoring collapsed spans and the event/search filters.
function visibleRows(spans, children, collapsed, { showEvents, filter }) {
  let rows = []
  let needle = filter.trim().toLowerCase()
  let matches = (span) => !needle || span.name.toLowerCase().includes(needle)
  let keep = new Set()
  if (needle) {
    let byId = new Map(spans.map((s) => [s.span_id, s]))
    for (let span of spans) {
      if (!matches(span)) continue
      for (let s = span; s; s = byId.get(s.parent_id)) keep.add(s.span_id)
    }
  }
  let walk = (span, depth) => {
    if (!showEvents && span.type === 'event' && span.status === 'ok') return
    if (needle && !keep.has(span.span_id)) return
    let kids = children.get(span.span_id) ?? []
    rows.push({ span, depth, hasChildren: kids.length > 0 })
    if (!collapsed.has(span.span_id) || needle) kids.forEach((k) => walk(k, depth + 1))
  }
  ;(children.get(null) ?? []).forEach((root) => walk(root, 0))
  return rows
}

function SpanRow({ row, total, selected, collapsed, onSelect, onToggle }) {
  let { span, depth, hasChildren } = row
  let [, dot] = TYPES[span.type] ?? TYPES.event
  let duration = span.end - span.start
  let left = total ? (span.start / total) * 100 : 0
  let width = total ? Math.max((duration / total) * 100, 0.4) : 0
  let status = STATUS[span.status]
  let ref = useRef(null)
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  return (
    <div
      ref={ref}
      role="treeitem"
      aria-selected={selected}
      aria-expanded={hasChildren ? !collapsed : undefined}
      onClick={() => onSelect(span.span_id)}
      className={clsx(
        'grid cursor-pointer grid-cols-[minmax(0,1fr)_minmax(6rem,40%)] items-center gap-3 border-l-2 py-1 pr-3 text-[13px]/5',
        selected
          ? 'border-blue-500 bg-blue-500/8 dark:bg-blue-400/10'
          : 'border-transparent hover:bg-zinc-950/3 dark:hover:bg-white/4'
      )}
    >
      <div className="flex min-w-0 items-center gap-1.5" style={{ paddingLeft: `${depth * 14 + 6}px` }}>
        {hasChildren ? (
          <button
            type="button"
            aria-label={collapsed ? 'Expand' : 'Collapse'}
            onClick={(e) => {
              e.stopPropagation()
              onToggle(span.span_id)
            }}
            className="-m-0.5 rounded p-0.5 text-zinc-400 hover:bg-zinc-950/5 dark:hover:bg-white/10"
          >
            <ChevronRightIcon className={clsx('size-3.5 transition-transform', !collapsed && 'rotate-90')} />
          </button>
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <span className={clsx('size-2 shrink-0 rounded-full', dot)} />
        <span className={clsx('truncate', span.type === 'event' ? 'font-mono text-xs text-zinc-500 dark:text-zinc-400' : 'font-medium text-zinc-950 dark:text-white')}>
          {span.name}
        </span>
        {status && <span className={clsx('size-1.5 shrink-0 rounded-full', status[1] === 'red' ? 'bg-red-500' : status[1] === 'amber' ? 'bg-amber-500' : 'bg-blue-500')} title={status[0]} />}
        <span className="ml-auto shrink-0 pl-2 text-xs text-zinc-500 tabular-nums">
          {span.tokens && <span className="mr-2 max-sm:hidden">{tokens(span.tokens.input + span.tokens.output)} tok</span>}
          {span.type !== 'event' && seconds(duration)}
        </span>
      </div>
      <div className="relative h-3.5 rounded-sm bg-zinc-950/3 dark:bg-white/4" aria-hidden>
        {span.type === 'event' ? (
          <span className={clsx('absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rotate-45', dot)} style={{ left: `${left}%` }} />
        ) : (
          <span className={clsx('absolute inset-y-0.5 rounded-[2px] opacity-80', dot)} style={{ left: `${left}%`, width: `${width}%` }} />
        )}
      </div>
    </div>
  )
}

function Section({ title, value, actions, children }) {
  return (
    <section className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">{title}</h3>
        <div className="flex items-center gap-1">
          {actions}
          {value !== undefined && value !== null && <CopyButton value={value} />}
        </div>
      </div>
      {children}
    </section>
  )
}

function textOf(content) {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) return content.map((part) => part.text ?? '').filter(Boolean).join('\n')
  return null
}

// Responses API items rendered as a conversation, like a chat log.
function ChatItem({ item }) {
  let [role, body, tone] = (() => {
    if (item.type === 'function_call') return [`Tool call · ${item.name}`, <JsonView value={item.arguments} openDepth={3} />, 'sky']
    if (item.type === 'function_call_output') return ['Tool result', <JsonView value={item.output} openDepth={1} />, 'sky']
    if (item.type === 'reasoning') return ['Reasoning', <p className="text-xs text-zinc-500 italic">Encrypted reasoning (not readable).</p>, 'zinc']
    let text = textOf(item.content)
    let role = item.role ?? item.type ?? 'item'
    return [role, text != null ? <JsonOrText text={text} /> : <JsonView value={item} />, role === 'assistant' ? 'violet' : 'zinc']
  })()
  return (
    <div className="grid gap-1.5 rounded-lg p-3 ring-1 ring-zinc-950/8 dark:ring-white/10">
      <div>
        <Badge color={tone} className="capitalize">{role}</Badge>
      </div>
      {body}
    </div>
  )
}

function JsonOrText({ text }) {
  try {
    if (/^\s*[[{]/.test(text)) return <JsonView value={JSON.parse(text)} openDepth={2} />
  } catch {
    // Fall through to plain text.
  }
  return <p className="text-[13px]/6 break-words whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">{text}</p>
}

function LlmBody({ span, mode }) {
  let input = span.inputs?.input ?? []
  let output = span.outputs?.items ?? []
  if (mode === 'json') {
    return (
      <>
        <Section title="Inputs" value={span.inputs}><JsonView value={span.inputs} /></Section>
        <Section title="Outputs" value={span.outputs}><JsonView value={span.outputs} /></Section>
      </>
    )
  }
  return (
    <>
      <Section title={`Input · ${input.length} messages`} value={input}>
        {span.inputs?.tools?.length > 0 && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Tools offered: {span.inputs.tools.join(', ')}</p>
        )}
        <div className="grid gap-2">{input.map((item, i) => <ChatItem key={i} item={item} />)}</div>
      </Section>
      <Section title="Output" value={span.outputs}>
        {span.outputs?.error && <p className="text-sm text-red-700 dark:text-red-400">{span.outputs.error}</p>}
        <div className="grid gap-2">{output.map((item, i) => <ChatItem key={i} item={item} />)}</div>
        {!output.length && !span.outputs?.error && <p className="text-sm text-zinc-500">No output recorded.</p>}
      </Section>
    </>
  )
}

function SpanDetail({ span }) {
  let [tab, setTab] = useState('io')
  let [mode, setMode] = useState('chat')
  let [label, , color] = TYPES[span.type] ?? TYPES.event
  let status = STATUS[span.status]
  let tabs = [['io', span.type === 'event' ? 'Details' : 'Inputs / Outputs'], ['attributes', 'Attributes']]

  return (
    <div className="flex min-h-0 flex-col">
      <div className="grid gap-2 border-b border-zinc-950/5 px-5 pt-4 dark:border-white/5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base/6 font-semibold text-zinc-950 dark:text-white">{span.name}</h2>
          <Badge color={color}>{label}</Badge>
          {status && <Badge color={status[1]}>{status[0]}</Badge>}
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500 tabular-nums dark:text-zinc-400">
          <span>Starts at +{seconds(span.start)}</span>
          {span.type !== 'event' && <span>Duration {seconds(span.end - span.start)}</span>}
          {span.tokens && <span>Tokens {tokens(span.tokens.input)} in / {tokens(span.tokens.output)} out</span>}
          <span className="font-mono">{span.span_id}</span>
        </div>
        <div className="-mb-px flex gap-4">
          {tabs.map(([key, name]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={clsx(
                'border-b-2 py-2 text-sm font-medium',
                tab === key ? 'border-zinc-950 text-zinc-950 dark:border-white dark:text-white' : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              )}
            >
              {name}
            </button>
          ))}
          {span.type === 'llm' && tab === 'io' && (
            <div className="ml-auto flex items-center gap-1 self-center rounded-lg bg-zinc-950/5 p-0.5 text-xs dark:bg-white/10">
              {['chat', 'json'].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={clsx('rounded-md px-2 py-0.5 font-medium capitalize', mode === m ? 'bg-white shadow-xs dark:bg-zinc-800' : 'text-zinc-500')}
                >
                  {m === 'chat' ? 'Pretty' : 'JSON'}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="grid min-h-0 content-start gap-5 overflow-y-auto px-5 py-4">
        {tab === 'attributes' ? (
          <Section title="Attributes" value={span.attributes}><JsonView value={span.attributes} openDepth={1} /></Section>
        ) : span.type === 'llm' ? (
          <LlmBody span={span} mode={mode} />
        ) : (
          <>
            {span.inputs != null && <Section title="Inputs" value={span.inputs}><JsonView value={span.inputs} /></Section>}
            {span.outputs != null && <Section title="Outputs" value={span.outputs}><JsonView value={span.outputs} /></Section>}
            {span.inputs == null && span.outputs == null && <p className="text-sm text-zinc-500">No inputs or outputs recorded.</p>}
          </>
        )}
      </div>
    </div>
  )
}

function Meta({ label, children }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-[11px] font-medium tracking-wide text-zinc-500 uppercase dark:text-zinc-400">{label}</dt>
      <dd className="flex items-center gap-1 text-[13px] text-zinc-950 tabular-nums dark:text-white">{children}</dd>
    </div>
  )
}

export function TraceDetail({ runId, params }) {
  let [state, setState] = useState({ status: 'loading' })
  let [collapsed, setCollapsed] = useState(() => new Set())
  let [showEvents, setShowEvents] = useState(true)
  let [filter, setFilter] = useState('')
  let [reload, setReload] = useState(0)
  let selectedId = params.get('span')

  useEffect(() => {
    let controller = new AbortController()
    api.trace(runId, { signal: controller.signal }).then(
      (data) => setState({ status: 'ok', ...data }),
      (error) => error.name !== 'AbortError' && setState({ status: 'error', error: error.message, code: error.status })
    )
    return () => controller.abort()
  }, [runId, reload])

  let running = state.trace?.status === 'running'
  useEffect(() => {
    if (!running) return
    let timer = setInterval(() => setReload((n) => n + 1), 2000)
    return () => clearInterval(timer)
  }, [running])

  let spans = state.spans ?? []
  let children = useMemo(() => buildTree(spans), [spans])
  let rows = useMemo(() => visibleRows(spans, children, collapsed, { showEvents, filter }), [spans, children, collapsed, showEvents, filter])
  let selected = spans.find((s) => s.span_id === selectedId) ?? spans[0]
  let total = spans[0] ? spans[0].end - spans[0].start : 0

  let select = (id) => navigate(`/traces/${encodeURIComponent(runId)}?span=${id}`, { replace: true })
  let toggle = (id) =>
    setCollapsed((c) => {
      let next = new Set(c)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  function onKeyDown(event) {
    let index = rows.findIndex((r) => r.span.span_id === selected?.span_id)
    let row = rows[index]
    if (event.key === 'ArrowDown' || event.key === 'j') select(rows[Math.min(index + 1, rows.length - 1)].span.span_id)
    else if (event.key === 'ArrowUp' || event.key === 'k') select(rows[Math.max(index - 1, 0)].span.span_id)
    else if (event.key === 'ArrowRight' && row?.hasChildren && collapsed.has(row.span.span_id)) toggle(row.span.span_id)
    else if (event.key === 'ArrowLeft' && row?.hasChildren && !collapsed.has(row.span.span_id)) toggle(row.span.span_id)
    else return
    event.preventDefault()
  }

  let back = (
    <Link href="/traces" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white">
      <ArrowLeftIcon className="size-4" /> Traces
    </Link>
  )
  if (state.status === 'loading') return <div className="grid gap-4 px-4 py-6 sm:px-8">{back}<p className="text-sm text-zinc-500">Loading trace…</p></div>
  if (state.status === 'error') {
    return (
      <div className="grid gap-4 px-4 py-6 sm:px-8">
        {back}
        <p className="text-sm text-red-700 dark:text-red-400">{state.code === 404 ? 'No run with this ID.' : `Couldn't load this trace. ${state.error}`}</p>
      </div>
    )
  }

  let t = state.trace
  let [label, color] = outcome(t)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="grid gap-3 border-b border-zinc-950/5 px-4 py-4 sm:px-6 dark:border-white/5">
        <div className="flex items-center justify-between gap-3">
          {back}
          <div className="flex items-center gap-1">
            <a
              href={`/api/runs/${encodeURIComponent(t.run_id)}`}
              target="_blank"
              rel="noreferrer"
              className="rounded-md px-1.5 py-0.5 text-xs font-medium text-zinc-500 hover:bg-zinc-950/5 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white"
            >
              Raw record ↗
            </a>
          </div>
        </div>
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
          <h1 className="min-w-0 flex-1 text-lg/7 font-semibold text-zinc-950 dark:text-white">{t.question}</h1>
          <Badge color={color}>{label}</Badge>
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-2">
          <Meta label="Run">
            <span className="font-mono">{shortId(t.run_id)}</span>
            <CopyButton value={t.run_id} label="Copy ID" />
          </Meta>
          <Meta label="Duration">{seconds(t.duration_seconds)}</Meta>
          <Meta label="Tokens">{tokens(t.input_tokens)} in / {tokens(t.output_tokens)} out</Meta>
          <Meta label="Turns · tools">{t.model_turns ?? '–'} · {t.tool_calls ?? '–'}</Meta>
          <Meta label="Model">{t.model ?? '–'}</Meta>
          <Meta label="Configuration">{t.configuration ?? '–'}</Meta>
          {(t.game_label || t.game_id) && <Meta label="Game">{t.game_label ?? t.game_id}</Meta>}
          {t.conversation_id && (
            <Meta label="Conversation">
              <Link href={`/traces?conversation_id=${encodeURIComponent(t.conversation_id)}`} className="font-mono text-blue-700 hover:underline dark:text-blue-400">
                {shortId(t.conversation_id)}
              </Link>
            </Meta>
          )}
          {t.parent_run_id && (
            <Meta label="Follow-up to">
              <Link href={`/traces/${encodeURIComponent(t.parent_run_id)}`} className="font-mono text-blue-700 hover:underline dark:text-blue-400">
                {shortId(t.parent_run_id)}
              </Link>
            </Meta>
          )}
          {t.openai_trace_id && (
            <Meta label="OpenAI trace">
              <span className="font-mono">{t.openai_trace_id.slice(0, 14)}…</span>
              <CopyButton value={t.openai_trace_id} />
            </Meta>
          )}
        </dl>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex min-h-0 flex-col border-zinc-950/5 max-lg:border-b lg:border-r dark:border-white/5">
          <div className="flex flex-wrap items-center gap-3 border-b border-zinc-950/5 px-3 py-2 dark:border-white/5">
            <input
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter spans"
              aria-label="Filter spans"
              className="min-w-0 flex-1 rounded-md bg-zinc-950/4 px-2 py-1 text-sm outline-none placeholder:text-zinc-400 focus:ring-2 focus:ring-blue-500 dark:bg-white/5"
            />
            <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
              <input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} />
              Events
            </label>
            <button
              type="button"
              className="text-xs font-medium text-zinc-500 hover:text-zinc-950 dark:hover:text-white"
              onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(spans.filter((s) => children.has(s.span_id) && s.parent_id).map((s) => s.span_id)))}
            >
              {collapsed.size ? 'Expand all' : 'Collapse all'}
            </button>
          </div>
          <div className="flex justify-between px-3 pt-1.5 pb-1 text-[11px] font-medium tracking-wide text-zinc-400 uppercase">
            <span>Span</span>
            <span className="w-[40%] text-right tabular-nums normal-case">0 → {seconds(total)}</span>
          </div>
          <div
            role="tree"
            aria-label="Spans"
            tabIndex={0}
            onKeyDown={onKeyDown}
            className="min-h-0 flex-1 overflow-y-auto pb-3 outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset lg:max-h-[calc(100svh-15rem)]"
          >
            {rows.map((row) => (
              <SpanRow
                key={row.span.span_id}
                row={row}
                total={total}
                selected={row.span.span_id === selected?.span_id}
                collapsed={collapsed.has(row.span.span_id)}
                onSelect={select}
                onToggle={toggle}
              />
            ))}
            {!rows.length && <p className="px-3 py-2 text-sm text-zinc-500">No spans match.</p>}
          </div>
          <p className="border-t border-zinc-950/5 px-3 py-1.5 text-[11px] text-zinc-400 dark:border-white/5">
            ↑↓ or j/k to move · ←→ to collapse · started {absoluteTime(t.created_at) || 'earlier'}
          </p>
        </div>
        <div className="flex min-h-0 flex-col lg:max-h-[calc(100svh-12rem)]">
          {selected && <SpanDetail key={selected.span_id} span={selected} />}
        </div>
      </div>
    </div>
  )
}

import { CheckCircleIcon, ExclamationTriangleIcon, XCircleIcon } from '@heroicons/react/16/solid'
import {
  ArrowPathIcon,
  ArrowTurnDownRightIcon,
  ChevronRightIcon,
  InformationCircleIcon,
  QueueListIcon,
  StopIcon,
} from '@heroicons/react/20/solid'
import clsx from 'clsx'
import { useEffect, useMemo, useState } from 'react'
import { Badge } from '../components/badge'
import { Button } from '../components/button'
import { describePacket } from './evidence'
import { GameFlowChart } from './GameFlowChart'
import { buildSteps, STOP_TEXT } from './steps'

const VERDICTS = {
  supported: { color: 'green', icon: CheckCircleIcon, label: 'Fact-checked' },
  answered_unverified: { color: 'amber', icon: ExclamationTriangleIcon, label: 'Not fact-checked' },
  insufficient_evidence: { color: 'red', icon: XCircleIcon, label: "Couldn't confirm an answer" },
}
const verdictFor = (reason) => VERDICTS[reason] ?? { color: 'red', icon: XCircleIcon, label: "Couldn't finish this answer" }

// Evidence in citation order: claims first, then anything only the headline cites.
export function citationOrder(result) {
  let analysis = result?.analysis ?? {}
  let order = []
  let claims = [...(analysis.claims ?? []), ...(analysis.headline_claim ? [analysis.headline_claim] : [])]
  for (let claim of claims) for (let id of claim.packet_ids) if (!order.includes(id)) order.push(id)
  return order
}

export function evidenceIndex(result) {
  return Object.fromEntries((result?.evidence ?? []).map((e) => [e.packet_id, e.payload]))
}

export function firstRunWindow(result) {
  let evidence = evidenceIndex(result)
  for (let id of citationOrder(result)) {
    let described = describePacket(evidence[id])
    if (described.window) return { packetId: id, ...described.window }
  }
  return null
}

export function CiteButton({ number, title, onClick, active }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Evidence ${number}: ${title}`}
      className={clsx(
        'mx-px inline-flex h-[19px] min-w-[19px] items-center justify-center rounded-[5px] px-1 align-[2px] text-[11.5px]/none font-bold tabular-nums transition-colors',
        active
          ? 'bg-orange-600 text-white dark:bg-orange-500'
          : 'bg-orange-500/12 text-orange-800 hover:bg-orange-600 hover:text-white dark:bg-orange-400/15 dark:text-orange-300 dark:hover:bg-orange-500 dark:hover:text-white'
      )}
    >
      {number}
    </button>
  )
}

// Emphasise scores, shooting lines and game clocks inside claim text.
function ClaimText({ text }) {
  return text.split(/(\d+[–-]\d+(?!\d|\.\d)|\d+ of \d+|\b\d{1,2}:\d{2}\b)/).map((part, i) =>
    i % 2 ? (
      <span key={i} className="font-semibold tabular-nums">
        {part}
      </span>
    ) : (
      part
    )
  )
}

function StepIcon({ state, tone }) {
  if (state === 'active')
    return <span className="z-10 size-[21px] animate-spin rounded-full border-[1.5px] border-orange-500 border-t-transparent motion-reduce:animate-none" />
  let styles = {
    done: 'bg-green-500/15 text-green-700 dark:text-green-400',
    warn: 'bg-amber-400/20 text-amber-700 dark:text-amber-400',
    stop: 'bg-red-500/15 text-red-700 dark:text-red-400',
  }
  let key = tone ?? 'done'
  let Icon = key === 'warn' ? ExclamationTriangleIcon : key === 'stop' ? XCircleIcon : CheckCircleIcon
  return (
    <span className={clsx('z-10 grid size-[21px] place-items-center rounded-full', styles[key])}>
      <Icon className="size-3.5" />
    </span>
  )
}

function RunSteps({ turn, onOpenStep, onStop }) {
  let running = turn.status === 'running'
  let [open, setOpen] = useState(running)
  useEffect(() => setOpen(running), [running])
  let { steps, activity } = useMemo(() => buildSteps(turn.events), [turn.events])
  let usage = turn.result?.usage
  let seconds = turn.events.at(-1)?.elapsed_seconds
  let rows = running ? [...steps, { title: activity ?? 'Starting', active: true }] : steps

  return (
    <div className="rounded-xl ring-1 ring-zinc-950/10 dark:ring-white/10">
      <div className="flex items-center">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 px-4 py-2.5 text-left text-sm/6 text-zinc-600 dark:text-zinc-300"
        >
          {running ? (
            <>
              <span className="inline-flex shrink-0 items-center gap-1.5 font-semibold text-orange-700 dark:text-orange-400">
                <span className="size-1.5 animate-pulse rounded-full bg-orange-500" />
                Working
              </span>
              <span className="truncate text-zinc-500 dark:text-zinc-400">{activity ?? 'Starting'}…</span>
            </>
          ) : (
            <>
              <span className="shrink-0 font-semibold text-zinc-950 dark:text-white">
                {turn.result?.stop_reason === 'supported' ? 'Worked for' : 'Stopped after'} {seconds != null ? `${seconds.toFixed(1)}s` : ''}
              </span>
              {usage && (
                <span className="truncate text-zinc-500 dark:text-zinc-400">
                  · {usage.tool_calls} data lookup{usage.tool_calls === 1 ? '' : 's'} · {usage.verification_passes} fact-check
                  {usage.verification_passes === 1 ? '' : 's'}
                </span>
              )}
            </>
          )}
          <ChevronRightIcon className={clsx('ml-auto size-4 shrink-0 fill-zinc-400 transition-transform', open && 'rotate-90')} />
        </button>
        {running && (
          <Button plain onClick={onStop} className="mr-1.5">
            <StopIcon />
            Stop
          </Button>
        )}
      </div>

      {open && (
        <ol className="px-4 pt-0.5 pb-3">
          {rows.map((step, i) => {
            let body = (
              <>
                <span className="block text-sm/5 text-zinc-950 dark:text-white">{step.active ? `${step.title}…` : step.title}</span>
                {step.detail && <span className="block text-[13px]/5 text-zinc-500 dark:text-zinc-400">{step.detail}</span>}
              </>
            )
            return (
              <li
                key={i}
                className={clsx(
                  'relative grid grid-cols-[21px_1fr_auto] items-start gap-x-2.5 py-1.5',
                  i < rows.length - 1 &&
                    'after:absolute after:top-7 after:-bottom-1.5 after:left-2.5 after:w-px after:bg-zinc-950/10 dark:after:bg-white/10'
                )}
              >
                <StepIcon state={step.active ? 'active' : 'done'} tone={step.tone} />
                {running || step.active ? (
                  <span className="pt-px">{body}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => onOpenStep(i)}
                    className="pt-px text-left hover:[&>span:first-child]:underline hover:[&>span:first-child]:decoration-zinc-950/30 hover:[&>span:first-child]:underline-offset-3 dark:hover:[&>span:first-child]:decoration-white/30"
                  >
                    {body}
                  </button>
                )}
                <span className="pt-0.5 text-xs text-zinc-500 tabular-nums dark:text-zinc-400">
                  {step.active ? '' : `${step.at.toFixed(1)}s`}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

function Note({ tone, icon: Icon, title, children }) {
  return (
    <div
      className={clsx(
        'grid grid-cols-[20px_1fr] gap-x-2.5 rounded-lg px-3.5 py-3 text-sm/6',
        tone === 'amber'
          ? 'bg-amber-400/15 text-zinc-700 dark:bg-amber-400/10 dark:text-zinc-300'
          : tone === 'red'
            ? 'bg-red-500/10 text-zinc-700 dark:text-zinc-300'
            : 'bg-zinc-950/[0.03] text-zinc-600 ring-1 ring-zinc-950/5 dark:bg-white/[0.03] dark:text-zinc-400 dark:ring-white/5'
      )}
    >
      <Icon
        className={clsx(
          'mt-0.5 size-5',
          tone === 'amber' ? 'fill-amber-600 dark:fill-amber-400' : tone === 'red' ? 'fill-red-600 dark:fill-red-400' : 'fill-zinc-400'
        )}
      />
      <div>
        {title && <span className="font-semibold text-zinc-950 dark:text-white">{title}</span>} {children}
      </div>
    </div>
  )
}

function FollowUpHook({ question, disabled, onAsk }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onAsk(question)}
      className="group mt-1.5 flex items-start gap-1.5 text-left text-[14.5px]/6 text-orange-800 disabled:cursor-not-allowed disabled:opacity-50 dark:text-orange-300"
    >
      <ArrowTurnDownRightIcon className="mt-1 size-4 shrink-0 fill-orange-500/70" />
      <span className="decoration-orange-500/40 underline-offset-3 group-enabled:group-hover:underline">{question}</span>
    </button>
  )
}

function GameChip({ label, onWrongGame }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-zinc-500 dark:text-zinc-400">
      <span>
        Answering about <span className="font-medium text-zinc-800 tabular-nums dark:text-zinc-200">{label}</span>
      </span>
      <span aria-hidden="true">·</span>
      <button
        type="button"
        onClick={onWrongGame}
        className="underline decoration-zinc-400/60 underline-offset-3 hover:text-zinc-950 dark:hover:text-white"
      >
        Wrong game?
      </button>
    </div>
  )
}

function Answer({ turn, flow, showChart, activePacket, busy, onCite, onShowWork, onAsk }) {
  let result = turn.result
  let analysis = result.analysis ?? {}
  let claims = analysis.claims ?? []
  let verdict = verdictFor(result.stop_reason)
  let order = citationOrder(result)
  let evidence = evidenceIndex(result)
  let window = firstRunWindow(result)
  let removed = analysis.removed_claims ?? []
  let checks = result.usage?.verification_passes ?? 0
  // The harness appends its own stop message; fans get the plain-language one instead.
  let limitations = (analysis.limitations ?? []).filter((l) => !l.startsWith('The harness stopped with'))
  let answered = claims.length > 0
  let cite = (id) => (
    <CiteButton
      key={id}
      number={order.indexOf(id) + 1}
      title={describePacket(evidence[id]).title}
      active={activePacket === id}
      onClick={() => onCite(id)}
    />
  )

  return (
    <div className="flex animate-[rise_.35s_ease_both] flex-col gap-4 motion-reduce:animate-none">
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-zinc-500 dark:text-zinc-400">
        <Badge color={verdict.color}>
          <verdict.icon className="size-3.5" />
          {verdict.label}
        </Badge>
        <span>
          {answered
            ? `${claims.length} claim${claims.length === 1 ? '' : 's'} · ${checks} check${checks === 1 ? '' : 's'}`
            : 'No supported answer'}
          {removed.length ? ` · ${removed.length} claim${removed.length === 1 ? '' : 's'} removed` : ''}
        </span>
      </div>

      {analysis.headline && (
        <h2 className="text-2xl/8 font-semibold tracking-tight text-balance text-zinc-950 max-sm:text-xl/7 dark:text-white">
          {analysis.headline}
        </h2>
      )}

      {showChart && flow?.status === 'ok' && (
        <figure className="rounded-xl p-4 ring-1 ring-zinc-950/10 dark:ring-white/10">
          <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="text-sm/6 font-semibold text-zinc-950 dark:text-white">Score margin, whole game</span>
            <span className="text-xs/5 text-zinc-500 dark:text-zinc-400">
              <span className="pointer-coarse:hidden">Hover to scrub</span>
              {window && (
                <>
                  <span className="pointer-coarse:hidden"> · </span>shaded run {cite(window.packetId)}
                </>
              )}
            </span>
          </figcaption>
          <GameFlowChart flow={flow} window={window} onSelectWindow={() => onCite(window.packetId)} />
        </figure>
      )}

      {answered ? (
        <>
          {/* Claims are written to read as one account; each keeps its own citations. */}
          <p className="max-w-[66ch] text-base/7 text-zinc-800 dark:text-zinc-200">
            {claims.map((claim, i) => (
              <span key={i}>
                <ClaimText text={claim.text} /> {claim.packet_ids.map(cite)}{' '}
              </span>
            ))}
          </p>
          {claims.some((c) => c.follow_up) && (
            <div className="flex flex-col">
              <span className="text-xs/5 font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">Dig deeper</span>
              {claims
                .filter((c) => c.follow_up)
                .map((c) => (
                  <FollowUpHook key={c.follow_up} question={c.follow_up} disabled={busy} onAsk={onAsk} />
                ))}
            </div>
          )}
        </>
      ) : (
        <p className="max-w-[66ch] text-base/7 text-zinc-800 dark:text-zinc-200">
          {result.stop_reason === 'insufficient_evidence'
            ? "The game data can't answer that one. Rather than guess, it stopped. Try asking about something that happened on the floor in this game."
            : `${STOP_TEXT[result.stop_reason] ?? 'It stopped early'}. Nothing it found could be fully checked, so there's no answer to show. Try again or rephrase the question.`}
        </p>
      )}

      {(removed.length > 0 || limitations.length > 0) && (
        <div className="grid gap-2.5">
          {removed.map((r) => (
            <Note key={r.text} tone="amber" icon={ExclamationTriangleIcon} title="Removed during fact-check.">
              <s className="text-zinc-500 dark:text-zinc-400">{r.text}</s>
              <br />
              {r.reason}
            </Note>
          ))}
          {limitations.map((text) => (
            <Note key={text} icon={InformationCircleIcon} title="What the data can't tell us.">
              {text}
            </Note>
          ))}
        </div>
      )}

      <div className="-ml-2.5">
        <Button plain onClick={onShowWork}>
          <QueueListIcon />
          Show your work
        </Button>
      </div>
    </div>
  )
}

export function Turn({ turn, gameLabel, flow, showChart, activePacket, busy, onOpenStep, onCite, onShowWork, onAsk, onStop, onRetry, onWrongGame }) {
  let running = turn.status === 'running'
  return (
    <section id={`turn-${turn.key}`} className="flex scroll-mt-20 flex-col gap-3.5">
      <div className="max-w-[min(34rem,88%)] self-end rounded-2xl rounded-br-md bg-zinc-950 px-4 py-2.5 text-[15px]/6 text-white dark:bg-zinc-700">
        {turn.question}
      </div>
      {gameLabel && <GameChip label={gameLabel} onWrongGame={onWrongGame} />}
      {(turn.events.length > 0 || running) && <RunSteps turn={turn} onOpenStep={onOpenStep} onStop={onStop} />}
      {/* Show the game as soon as it is known, so the wait already carries context. */}
      {running && showChart && flow?.status === 'ok' && (
        <figure className="rounded-xl p-4 ring-1 ring-zinc-950/10 dark:ring-white/10">
          <figcaption className="mb-2 text-sm/6 font-semibold text-zinc-950 dark:text-white">Score margin, whole game</figcaption>
          <GameFlowChart flow={flow} />
        </figure>
      )}
      {turn.status === 'done' && turn.result && (
        <Answer
          turn={turn}
          flow={flow}
          showChart={showChart}
          activePacket={activePacket}
          busy={busy}
          onCite={onCite}
          onShowWork={onShowWork}
          onAsk={onAsk}
        />
      )}
      {turn.status === 'cancelled' && (
        <Note icon={InformationCircleIcon}>You stopped this one. The partial run is saved, and you can ask again anytime.</Note>
      )}
      {turn.status === 'error' && (
        <Note tone="red" icon={XCircleIcon} title="That didn't work.">
          {turn.error}
          <div className="mt-2 -ml-2.5">
            <Button plain onClick={onRetry} disabled={busy}>
              <ArrowPathIcon />
              Try again
            </Button>
          </div>
        </Note>
      )}
    </section>
  )
}

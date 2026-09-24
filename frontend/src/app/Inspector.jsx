import * as Headless from '@headlessui/react'
import { XMarkIcon } from '@heroicons/react/20/solid'
import clsx from 'clsx'
import { useEffect, useMemo, useRef } from 'react'
import { Badge } from '../components/badge'
import { DescriptionDetails, DescriptionList, DescriptionTerm } from '../components/description-list'
import { describePacket } from './evidence'
import { buildSteps } from './steps'
import { citationOrder, evidenceIndex } from './Turn'

const TABS = ['evidence', 'steps', 'usage']
const CONFIGURATIONS = { basic: 'Answer only', verification: 'Fact-check', investigation: 'Fact-check + follow-up lookups' }
const CONFIDENCE = {
  high: ['High confidence', 'text-green-700 dark:text-green-400'],
  medium: ['Medium confidence', 'text-amber-700 dark:text-amber-400'],
  low: ['Low confidence', 'text-red-700 dark:text-red-400'],
}

function useScrollIntoView(active) {
  let ref = useRef(null)
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [active])
  return ref
}

function EvidenceCard({ entry, number, active }) {
  let ref = useScrollIntoView(active)
  let p = describePacket(entry)
  let [confidence, confidenceClass] = CONFIDENCE[p.confidence] ?? [p.confidence, 'text-zinc-500']

  return (
    <article
      ref={ref}
      className={clsx(
        'grid gap-2 rounded-xl p-3.5 ring-1 transition-shadow',
        active ? 'shadow-[0_0_0_4px] shadow-orange-500/15 ring-orange-500' : 'ring-zinc-950/10 dark:ring-white/10'
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-[19px] min-w-[19px] items-center justify-center rounded-[5px] bg-orange-500/12 px-1 text-[11.5px] font-bold text-orange-800 tabular-nums dark:bg-orange-400/15 dark:text-orange-300">
          {number}
        </span>
        <span className="text-sm/5 font-semibold text-zinc-950 dark:text-white">{p.title}</span>
        {p.inherited && <Badge>From an earlier answer</Badge>}
        {confidence && <span className={clsx('ml-auto text-xs font-medium', confidenceClass)}>{confidence}</span>}
      </div>
      {p.summary && <p className="text-[13.5px]/5 text-zinc-600 dark:text-zinc-400">{p.summary}</p>}
      {p.facts && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[13px]/5">
          {p.facts.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="text-zinc-500 dark:text-zinc-400">{term}</dt>
              <dd className="font-medium text-zinc-950 tabular-nums dark:text-white">{value ?? '–'}</dd>
            </div>
          ))}
        </dl>
      )}
      {p.table && (
        <table className="w-full text-[13px]/5 tabular-nums">
          <thead>
            <tr className="text-zinc-500 dark:text-zinc-400">
              <th className="py-0.5 text-left font-normal" />
              {p.table.teams.map((t) => (
                <th key={t} className="py-0.5 text-right font-semibold text-zinc-950 dark:text-white">{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {p.table.rows.map(([label, ...values]) => (
              <tr key={label}>
                <td className="py-0.5 text-zinc-500 dark:text-zinc-400">{label}</td>
                {values.map((v, i) => (
                  <td key={i} className="py-0.5 text-right font-medium text-zinc-950 dark:text-white">{v}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.players?.length > 0 && (
        <table className="w-full text-[13px]/5 tabular-nums">
          <thead>
            <tr className="text-zinc-500 dark:text-zinc-400">
              <th className="py-0.5 text-left font-normal">Scorers in this stretch</th>
              <th className="py-0.5 text-right font-normal">PTS</th>
              <th className="py-0.5 text-right font-normal">FG</th>
              <th className="py-0.5 text-right font-normal">FT</th>
            </tr>
          </thead>
          <tbody>
            {p.players.map((player) => (
              <tr key={`${player.team}-${player.player}`} className="text-zinc-950 dark:text-white">
                <td className="py-0.5">
                  {player.player} <span className="text-zinc-500 dark:text-zinc-400">{player.team}</span>
                </td>
                <td className="py-0.5 text-right font-semibold">{player.pts}</td>
                <td className="py-0.5 text-right">{player.fgm}-{player.fga}</td>
                <td className="py-0.5 text-right">{player.ftm}-{player.fta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.plays?.length > 0 && (
        <details className="group text-[12.5px]/5">
          <summary className="cursor-pointer text-zinc-600 select-none hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white">
            {p.plays.length} scoring plays
          </summary>
          <ol className="mt-1.5 grid gap-1">
            {p.plays.map((play) => (
              <li key={play.eventnum} className="grid grid-cols-[3.5rem_1fr] gap-x-2 tabular-nums">
                <span className="text-zinc-500 dark:text-zinc-400">
                  {play.period <= 4 ? `Q${play.period}` : 'OT'} {play.clock}
                </span>
                <span className="text-zinc-800 dark:text-zinc-200">
                  {play.description} <span className="text-zinc-500 dark:text-zinc-400">· {play.score}</span>
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
      {p.caveats.map((c) => (
        <p key={c} className="text-[12.5px]/5 text-amber-800 dark:text-amber-300/90">Note: {c}</p>
      ))}
      <div className="flex flex-wrap gap-x-3 font-mono text-[11px] text-zinc-500">
        {p.source && <span>{p.source}</span>}
        <span className="break-all">{p.id}</span>
      </div>
    </article>
  )
}

function StepRow({ step, active }) {
  let ref = useScrollIntoView(active)
  let { sequence, kind, at, elapsed_seconds, ...data } = step.event
  return (
    <div
      ref={ref}
      className={clsx(
        'grid grid-cols-[3rem_1fr] gap-x-3 border-t border-zinc-950/5 py-2.5 first:border-t-0 dark:border-white/5',
        active && '-mx-4 bg-orange-500/8 px-4'
      )}
    >
      <span className="pt-px text-xs text-zinc-500 tabular-nums dark:text-zinc-400">{step.at.toFixed(1)}s</span>
      <div className="min-w-0">
        <p className="text-[13.5px]/5 text-zinc-950 dark:text-white">{step.title}</p>
        <p className="mt-0.5 font-mono text-[11px] text-zinc-500">
          #{sequence} {kind}
        </p>
        {Object.keys(data).length > 0 && (
          <pre className="mt-1.5 max-h-60 overflow-auto rounded-md bg-zinc-950/[0.03] p-2.5 font-mono text-[11px]/4 text-zinc-700 ring-1 ring-zinc-950/5 dark:bg-white/[0.04] dark:text-zinc-300 dark:ring-white/5">
            {JSON.stringify(data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

function Budget({ used, limit }) {
  if (limit == null) return <span className="tabular-nums">{used}</span>
  return (
    <span className="inline-flex flex-col items-end gap-1.5">
      <span className="tabular-nums">
        {used} <span className="text-zinc-500 dark:text-zinc-400">of {limit}</span>
      </span>
      <span className="h-1 w-20 overflow-hidden rounded-full bg-zinc-950/10 dark:bg-white/10">
        <span className="block h-full rounded-full bg-zinc-600 dark:bg-zinc-300" style={{ width: `${Math.min(100, (used / limit) * 100)}%` }} />
      </span>
    </span>
  )
}

export function Inspector({ turn, tab, focusPacket, focusStep, onTab, onClose }) {
  let result = turn.result
  let order = citationOrder(result)
  let evidence = evidenceIndex(result)
  let { steps } = useMemo(() => buildSteps(turn.events), [turn.events])
  let usage = result?.usage
  let limits = result?.limits ?? {}
  let seconds = turn.events.at(-1)?.elapsed_seconds

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between px-4 pt-3.5">
        <h2 className="text-base/6 font-semibold text-zinc-950 dark:text-white">Show your work</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-8 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-950/5 hover:text-zinc-950 dark:hover:bg-white/5 dark:hover:text-white"
        >
          <XMarkIcon className="size-5" />
        </button>
      </div>

      <Headless.TabGroup selectedIndex={TABS.indexOf(tab)} onChange={(i) => onTab(TABS[i])} className="flex min-h-0 flex-1 flex-col">
        <Headless.TabList className="flex gap-1 border-b border-zinc-950/10 px-3 pt-2 dark:border-white/10">
          {[
            ['Evidence', order.length || null],
            ['Steps', steps.length || null],
            ['Time & cost', null],
          ].map(([label, count]) => (
            <Headless.Tab
              key={label}
              className="-mb-px border-b-2 border-transparent px-2.5 py-2 text-sm/5 font-medium text-zinc-500 focus:outline-none data-focus-visible:outline-2 data-focus-visible:outline-blue-500 data-hover:text-zinc-950 data-selected:border-zinc-950 data-selected:text-zinc-950 dark:text-zinc-400 dark:data-hover:text-white dark:data-selected:border-white dark:data-selected:text-white"
            >
              {label}
              {count != null && <span className="ml-1.5 text-xs text-zinc-400 tabular-nums">{count}</span>}
            </Headless.Tab>
          ))}
        </Headless.TabList>

        <Headless.TabPanels className="min-h-0 flex-1 overflow-y-auto px-4 pt-3.5 pb-6">
          <Headless.TabPanel className="grid gap-2.5 focus:outline-none">
            <p className="text-[12.5px]/5 text-zinc-500 dark:text-zinc-400">
              {order.length
                ? "Each numbered citation in the answer points to one of these. Evidence only comes from the NBA data tools, never from the model's memory."
                : 'Nothing is cited because no claim passed the fact-check. The Steps tab shows what was tried.'}
            </p>
            {order.map((id, i) => (
              <EvidenceCard key={id} entry={evidence[id]} number={i + 1} active={focusPacket === id} />
            ))}
          </Headless.TabPanel>

          <Headless.TabPanel className="focus:outline-none">
            <p className="mb-2 text-[12.5px]/5 text-zinc-500 dark:text-zinc-400">
              Every step of this run as it was recorded. The complete trace, including model inputs, is saved with run{' '}
              <span className="font-mono">{result?.analysis_run_id}</span>.
            </p>
            {steps.map((step, i) => (
              <StepRow key={step.event.sequence} step={step} active={focusStep === i} />
            ))}
          </Headless.TabPanel>

          <Headless.TabPanel className="focus:outline-none">
            {usage ? (
              <DescriptionList className="sm:grid-cols-[1fr_auto]!">
                <DescriptionTerm>Total time</DescriptionTerm>
                <DescriptionDetails className="tabular-nums sm:text-right">{seconds?.toFixed(1)} s</DescriptionDetails>
                <DescriptionTerm>Model calls</DescriptionTerm>
                <DescriptionDetails className="sm:text-right">
                  <Budget used={usage.model_turns} limit={limits.model_turns} />
                </DescriptionDetails>
                <DescriptionTerm>Data lookups</DescriptionTerm>
                <DescriptionDetails className="sm:text-right">
                  <Budget used={usage.tool_calls} limit={limits.tool_calls} />
                </DescriptionDetails>
                <DescriptionTerm>Fact-check passes</DescriptionTerm>
                <DescriptionDetails className="sm:text-right">
                  <Budget used={usage.verification_passes} limit={limits.verification_passes} />
                </DescriptionDetails>
                <DescriptionTerm>Tokens</DescriptionTerm>
                <DescriptionDetails className="tabular-nums sm:text-right">
                  {(usage.input_tokens + usage.output_tokens).toLocaleString()}
                </DescriptionDetails>
                <DescriptionTerm>Estimated cost</DescriptionTerm>
                <DescriptionDetails className="sm:text-right">
                  {usage.estimated_cost_usd == null ? (
                    <span className="text-zinc-500">Model rates not set</span>
                  ) : (
                    `$${usage.estimated_cost_usd.toFixed(4)}`
                  )}
                </DescriptionDetails>
                <DescriptionTerm>Mode</DescriptionTerm>
                <DescriptionDetails className="sm:text-right">{CONFIGURATIONS[result.configuration] ?? result.configuration}</DescriptionDetails>
                {result.openai_trace_id && (
                  <>
                    <DescriptionTerm>OpenAI trace</DescriptionTerm>
                    <DescriptionDetails className="break-all font-mono text-xs sm:text-right">
                      {result.openai_trace_id}
                    </DescriptionDetails>
                    <DescriptionTerm>OpenAI logs</DescriptionTerm>
                    <DescriptionDetails className="sm:text-right">
                      <a className="underline underline-offset-2" href="https://platform.openai.com/logs" target="_blank" rel="noreferrer">
                        Open logs
                      </a>
                    </DescriptionDetails>
                  </>
                )}
              </DescriptionList>
            ) : (
              <p className="text-sm text-zinc-500">Usage appears when the run finishes.</p>
            )}
          </Headless.TabPanel>
        </Headless.TabPanels>
      </Headless.TabGroup>
    </div>
  )
}

import { ChevronRightIcon } from '@heroicons/react/16/solid'
import clsx from 'clsx'
import { useState } from 'react'

export function CopyButton({ value, label = 'Copy', className }) {
  let [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async (event) => {
        event.stopPropagation()
        try {
          await navigator.clipboard.writeText(typeof value === 'string' ? value : JSON.stringify(value, null, 2))
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        } catch {
          // Clipboard access can be denied; nothing else to do.
        }
      }}
      className={clsx(
        'rounded-md px-1.5 py-0.5 text-xs font-medium text-zinc-500 hover:bg-zinc-950/5 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white',
        className
      )}
    >
      {copied ? 'Copied' : label}
    </button>
  )
}

// Strings that are themselves JSON (tool payloads, model text) are shown parsed.
function parseEmbedded(value) {
  if (typeof value !== 'string' || value.length < 2 || !/^[[{]/.test(value.trim())) return undefined
  try {
    return JSON.parse(value)
  } catch {
    return undefined
  }
}

function Scalar({ value }) {
  if (value === null) return <span className="text-zinc-400">null</span>
  if (typeof value === 'boolean') return <span className="text-violet-700 dark:text-violet-400">{String(value)}</span>
  if (typeof value === 'number') return <span className="text-blue-700 dark:text-blue-400">{value}</span>
  return <span className="break-words whitespace-pre-wrap text-emerald-800 dark:text-emerald-300">"{value}"</span>
}

function Node({ name, value, depth, openDepth }) {
  let embedded = parseEmbedded(value)
  let data = embedded ?? value
  let container = data !== null && typeof data === 'object'
  let [open, setOpen] = useState(depth < openDepth)
  let entries = container ? (Array.isArray(data) ? data.map((v, i) => [i, v]) : Object.entries(data)) : []
  let key = name !== undefined && (
    <span className={typeof name === 'number' ? 'text-zinc-400' : 'text-zinc-700 dark:text-zinc-300'}>
      {name}
      <span className="text-zinc-400">: </span>
    </span>
  )

  if (!container) {
    return (
      <div className="pl-4">
        {key}
        <Scalar value={value} />
      </div>
    )
  }
  let brackets = Array.isArray(data) ? ['[', ']'] : ['{', '}']
  let summary = Array.isArray(data) ? `${entries.length} items` : `${entries.length} keys`
  return (
    <div>
      <button type="button" onClick={() => setOpen(!open)} className="group flex items-start text-left">
        <ChevronRightIcon className={clsx('mt-0.5 size-4 shrink-0 text-zinc-400 transition-transform', open && 'rotate-90')} />
        <span>
          {key}
          {embedded !== undefined && <span className="mr-1 rounded bg-zinc-950/5 px-1 text-[10px] text-zinc-500 dark:bg-white/10">JSON string</span>}
          <span className="text-zinc-400">{brackets[0]}</span>
          {!open && <span className="text-zinc-400"> {summary} {brackets[1]}</span>}
        </span>
      </button>
      {open && (
        <>
          <div className="ml-2 border-l border-zinc-950/10 pl-1 dark:border-white/10">
            {entries.map(([k, v]) => (
              <Node key={k} name={k} value={v} depth={depth + 1} openDepth={openDepth} />
            ))}
          </div>
          <div className="pl-4 text-zinc-400">{brackets[1]}</div>
        </>
      )}
    </div>
  )
}

export function JsonView({ value, openDepth = 2, className }) {
  if (value === undefined) return <p className="text-sm text-zinc-500">No data recorded.</p>
  return (
    <div className={clsx('font-mono text-[12px]/5 text-zinc-800 dark:text-zinc-200', className)}>
      <Node value={value} depth={0} openDepth={openDepth} />
    </div>
  )
}

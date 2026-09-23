import { useId, useRef, useState } from 'react'
import { matchupColors } from './teams'

const W = 644
const H = 206
const L = 58
const R = 630
const T = 20
const B = 176

const periodName = (p) => (p <= 4 ? ['1st', '2nd', '3rd', '4th'][p - 1] : p === 5 ? 'OT' : `${p - 4}OT`)
const periodStart = (p) => (p <= 4 ? (p - 1) * 12 : 48 + (p - 5) * 5)
const periodLength = (p) => (p <= 4 ? 12 : 5)

function clockAt(minute, periods) {
  let p = 1
  while (p < periods && minute >= periodStart(p + 1)) p++
  let remaining = Math.max(0, periodStart(p) + periodLength(p) - minute)
  let seconds = Math.min(59, Math.round((remaining % 1) * 60))
  return `${p <= 4 ? `Q${p}` : periodName(p)} ${Math.floor(remaining)}:${String(seconds).padStart(2, '0')}`
}

// Margin line from the away team's perspective: above zero the away team leads.
export function GameFlowChart({ flow, window, onSelectWindow }) {
  let id = useId()
  let svgRef = useRef(null)
  let [hover, setHover] = useState(null)
  let { away, home } = matchupColors(flow.away_team_abbr, flow.home_team_abbr)
  let points = flow.points
  let length = flow.length_minutes
  let peak = Math.max(10, ...points.map((p) => Math.abs(p.margin)))
  let scale = Math.ceil(peak / 5) * 5
  let tick = scale >= 20 ? 10 * Math.floor(scale / 20) : 5 * Math.floor(scale / 10) || 5
  let x = (minute) => L + (minute / length) * (R - L)
  let y = (margin) => T + ((scale - margin) / (2 * scale)) * (B - T)

  let path = `M${x(0)},${y(0)}`
  for (let p of points.slice(1)) path += ` H${x(p.minute).toFixed(1)} V${y(p.margin).toFixed(1)}`
  let area = `${path} H${x(length)} V${y(0)} H${x(0)} Z`
  let last = points.at(-1)
  let describe = (v) => (v === 0 ? 'Tied' : v > 0 ? `${away.abbr} +${v}` : `${home.abbr} +${-v}`)
  let periods = Array.from({ length: flow.periods }, (_, i) => i + 1)
  let runColor = window?.team === home.abbr ? 'var(--h)' : 'var(--a)'

  function marginAt(minute) {
    let margin = 0
    for (let p of points) {
      if (p.minute > minute) break
      margin = p.margin
    }
    return margin
  }

  function onMove(event) {
    let svg = svgRef.current
    let point = svg.createSVGPoint()
    point.x = event.clientX
    point.y = event.clientY
    let p = point.matrixTransform(svg.getScreenCTM().inverse())
    let minute = Math.max(0, Math.min(length, ((p.x - L) / (R - L)) * length))
    let box = svg.getBoundingClientRect()
    setHover({
      minute,
      svgX: p.x,
      left: event.clientX - box.left,
      top: event.clientY - box.top,
      label: `${clockAt(minute, flow.periods)} · ${describe(marginAt(minute))}`,
    })
  }

  return (
    <div
      className="relative [--a:var(--away)] [--h:var(--home)] dark:[--a:var(--away-dark)] dark:[--h:var(--home-dark)]"
      style={{ '--away': away.color, '--away-dark': away.dark, '--home': home.color, '--home-dark': home.dark }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full overflow-visible text-[17px] sm:text-[10.5px]"
        role="img"
        aria-label={`Score margin over the game. Final: ${describe(last.margin)}.${window ? ` Shaded: ${window.label} run.` : ''}`}
      >
        <defs>
          <clipPath id={`${id}-above`}>
            <rect x="0" y="0" width={W} height={y(0)} />
          </clipPath>
          <clipPath id={`${id}-below`}>
            <rect x="0" y={y(0)} width={W} height={H} />
          </clipPath>
        </defs>

        {periods.slice(1).map((p) => (
          <line key={p} x1={x(periodStart(p))} x2={x(periodStart(p))} y1={T} y2={B} className="stroke-zinc-950/10 dark:stroke-white/10" strokeDasharray="3 4" />
        ))}

        {window && (
          <g>
            <rect
              x={x(window.start)}
              y={T}
              width={Math.max(2, x(window.end) - x(window.start))}
              height={B - T}
              rx="3"
              strokeDasharray="3 3"
              style={{ fill: `color-mix(in srgb, ${runColor} 11%, transparent)`, stroke: `color-mix(in srgb, ${runColor} 55%, transparent)` }}
            />
            <text x={(x(window.start) + x(window.end)) / 2} y={T - 6} textAnchor="middle" className="font-semibold" style={{ fill: runColor }}>
              {window.label}
            </text>
          </g>
        )}

        <path d={area} clipPath={`url(#${id}-above)`} style={{ fill: 'color-mix(in srgb, var(--a) 15%, transparent)' }} />
        <path d={area} clipPath={`url(#${id}-below)`} style={{ fill: 'color-mix(in srgb, var(--h) 15%, transparent)' }} />
        <line x1={L} x2={R} y1={y(0)} y2={y(0)} className="stroke-zinc-950/20 dark:stroke-white/20" />
        <path d={path} clipPath={`url(#${id}-above)`} fill="none" strokeWidth="2" strokeLinejoin="round" style={{ stroke: 'var(--a)' }} />
        <path d={path} clipPath={`url(#${id}-below)`} fill="none" strokeWidth="2" strokeLinejoin="round" style={{ stroke: 'var(--h)' }} />
        <circle cx={x(last.minute)} cy={y(last.margin)} r="3.5" style={{ fill: last.margin >= 0 ? 'var(--a)' : 'var(--h)' }} />

        <g className="fill-zinc-500 dark:fill-zinc-400">
          <text x={L - 8} y={y(tick) + 4} textAnchor="end">{away.abbr} +{tick}</text>
          <text x={L - 8} y={y(0) + 4} textAnchor="end">Tied</text>
          <text x={L - 8} y={y(-tick) + 4} textAnchor="end">{home.abbr} +{tick}</text>
          {periods.map((p) => (
            <text key={p} x={x(periodStart(p) + periodLength(p) / 2)} y={B + 20} textAnchor="middle">
              {periodName(p)}
            </text>
          ))}
        </g>

        {hover && <line x1={hover.svgX} x2={hover.svgX} y1={T} y2={B} className="stroke-zinc-950/40 dark:stroke-white/40" />}
        <rect
          x={L}
          y={T}
          width={R - L}
          height={B - T}
          fill="transparent"
          className="cursor-crosshair"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          onClick={() => {
            if (window && hover && hover.minute >= window.start && hover.minute <= window.end) onSelectWindow?.()
          }}
        />
      </svg>
      {hover && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-[130%] rounded-md bg-zinc-950 px-2 py-1 text-xs whitespace-nowrap text-white tabular-nums dark:bg-white dark:text-zinc-950"
          style={{ left: hover.left, top: hover.top }}
        >
          {hover.label}
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px] bg-(--a)" />
          {away.name} ahead
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px] bg-(--h)" />
          {home.name} ahead
        </span>
        {window && (
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2.5 rounded-[3px] border border-dashed" style={{ borderColor: runColor }} />
            Cited run
          </span>
        )}
      </div>
    </div>
  )
}

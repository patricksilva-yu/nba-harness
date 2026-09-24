// Readable views of MCP evidence packets, by packet type.

const pct = (v) => (v == null ? '–' : `${(v * 100).toFixed(1)}%`)
const num = (v, digits = 1) => (v == null ? '–' : Number(v).toFixed(digits).replace(/\.0$/, ''))
const makes = (v) => (typeof v === 'string' ? v.replace(/\.0\b/g, '') : '–')

function gameMinute(period, clock) {
  let [m, s] = String(clock).split(':').map(Number)
  let length = period <= 4 ? 12 : 5
  let start = period <= 4 ? (period - 1) * 12 : 48 + (period - 5) * 5
  return start + length - (m + s / 60)
}

const quarter = (p) => (p <= 4 ? `Q${p}` : p === 5 ? 'OT' : `${p - 4}OT`)

const ADVANCED_ROWS = [
  ['Offensive rating', 'offensive_rating', num],
  ['Defensive rating', 'defensive_rating', num],
  ['Net rating', 'net_rating', num],
  ['Effective FG%', 'efg_pct', pct],
  ['True shooting', 'ts_pct', pct],
  ['Turnover ratio', 'turnover_ratio', num],
  ['Offensive rebound %', 'oreb_pct', pct],
  ['Pace', 'pace', num],
]

function describeByType(packet) {
  let m = packet.metrics ?? {}
  switch (packet.type) {
    case 'game_snapshot':
      return { title: 'Final score', facts: [['Away', m.away_score], ['Home', m.home_score]] }
    case 'run_candidate': {
      let w = packet.window ?? m
      let delta = m.score_delta_for_beneficiary
      return {
        title: `Scoring run: ${m.beneficiary} ${delta > 0 ? '+' : ''}${delta}`,
        facts: [
          ['Window', `${quarter(w.period_start)} ${w.clock_start} → ${quarter(w.period_end)} ${w.clock_end}`],
          ['Score before', m.start_score],
          ['Score after', m.end_score],
          [`${m.beneficiary} margin`, `${num(m.start_margin_for_beneficiary, 0)} → ${num(m.end_margin_for_beneficiary, 0)}`],
        ],
        window: {
          start: gameMinute(w.period_start, w.clock_start),
          end: gameMinute(w.period_end, w.clock_end),
          team: m.beneficiary,
          label: `${m.beneficiary} +${delta}`,
        },
      }
    }
    case 'game_window': {
      let w = packet.window ?? {}
      let points = m.team_points ?? {}
      let teams = Object.keys(points)
      let [leader, trailer] = teams.length === 2 && points[teams[1]] > points[teams[0]] ? [teams[1], teams[0]] : teams
      let span = `${quarter(w.period_start)} ${w.clock_start} → ${quarter(w.period_end)} ${w.clock_end}`
      let stats = m.team_stats ?? {}
      return {
        title: `${span}: ${leader} ${points[leader]}–${points[trailer]}`,
        facts: [
          ['Score before', m.score_before],
          ['Score after', m.score_after],
          ...teams.map((t) => [`${t} shooting`, stats[t] ? `FG ${stats[t].fgm}-${stats[t].fga} · FT ${stats[t].ftm}-${stats[t].fta} · ${stats[t].tov} TO` : '–']),
        ],
        players: (m.players ?? []).filter((p) => p.pts > 0).slice(0, 6),
        plays: (packet.plays ?? []).filter((p) => p.scoring),
        window: {
          start: gameMinute(w.period_start, w.clock_start),
          end: gameMinute(w.period_end, w.clock_end),
          team: leader,
          label: `${leader} ${points[leader]}–${points[trailer]}`,
        },
      }
    }
    case 'period_summary': {
      let periods = m.periods ?? []
      let teams = periods[0] ? Object.keys(periods[0]).filter((k) => k.endsWith('_points')).map((k) => k.replace('_points', '')) : []
      let leads = Object.entries(m.largest_lead ?? {}).filter(([, lead]) => lead)
      return {
        title: 'Quarter by quarter',
        table: { teams, rows: periods.map((p) => [p.label, ...teams.map((t) => p[`${t}_points`])]) },
        facts: [
          ...leads.map(([team, lead]) => [`${team} largest lead`, `${lead.points} (${lead.period} ${lead.clock})`]),
          ['Lead changes / ties', `${m.lead_changes} / ${m.ties}`],
        ],
      }
    }
    case 'player_game_context':
      return {
        title: `${m.player_name}${m.team_abbr ? ` (${m.team_abbr})` : ''}`,
        facts: [
          ['Minutes', num(m.minutes)],
          ['Points', num(m.pts, 0)],
          ['Rebounds / assists', `${num(m.reb, 0)} / ${num(m.ast, 0)}`],
          ['Field goals', makes(m.fg)],
          ['3-pointers', makes(m.fg3)],
          ['Free throws', makes(m.ft)],
          ['Turnovers', num(m.tov, 0)],
          ['Plus/minus', m.plus_minus == null ? '–' : `${m.plus_minus > 0 ? '+' : ''}${num(m.plus_minus, 0)}`],
        ],
      }
    case 'advanced_context': {
      let teams = Object.keys(m).filter((k) => !k.includes('_minus_') && typeof m[k] === 'object')
      return {
        title: 'Team efficiency',
        table: { teams, rows: ADVANCED_ROWS.map(([label, key, format]) => [label, ...teams.map((t) => format(m[t]?.[key]))]) },
      }
    }
    case 'possession_segment_summary':
      return {
        title: 'Play-by-play event mix',
        facts: [['Shot attempts', m.shot_events], ['Turnovers', m.turnovers], ['Free-throw events', m.free_throw_events]],
      }
    case 'lineup_stints':
      return {
        title: 'Rotation data',
        facts: [['Stints', m.returned_stints], ['Team', m.team ?? 'Both'], ['Period', m.period ? quarter(m.period) : 'Whole game']],
      }
    default:
      return {
        title: packet.type?.replaceAll('_', ' ') ?? 'Evidence',
        facts: Object.entries(m).filter(([, v]) => v == null || typeof v !== 'object'),
      }
  }
}

export function describePacket(entry) {
  let packet = entry?.packet ?? entry ?? {}
  return {
    id: packet.packet_id,
    type: packet.type,
    summary: packet.claim_seed,
    confidence: packet.confidence,
    caveats: packet.caveats ?? [],
    source: packet.source?.detail ?? packet.source?.provider,
    inherited: Boolean(entry?.inherited_from),
    ...describeByType(packet),
  }
}

import assert from 'node:assert/strict'
import test from 'node:test'
import { describePacket } from './evidence.js'

const snapshot = (team_box) => ({ packet: {
  packet_id: 'snapshot_game', type: 'game_snapshot', confidence: 'high',
  source: { detail: 'nba_s3:liveData' },
  metrics: { away_score: 94, home_score: 117, ...(team_box ? { team_box } : {}) },
} })

test('a shooting and rebounding citation exposes the supporting box score', () => {
  const result = describePacket(snapshot([
    { team_abbr: 'TOR', pts: 94, fgm: 35, fga: 91, fg_pct: 35 / 91,
      fg3m: 10, fg3a: 38, fg3_pct: 10 / 38, reb: 34, oreb: 14, dreb: 20 },
    { team_abbr: 'MIN', pts: 117, fgm: 43, fga: 77, fg_pct: 43 / 77,
      fg3m: 15, fg3a: 31, fg3_pct: 15 / 31, reb: 49, oreb: 9, dreb: 40 },
  ]))
  assert.equal(result.title, 'Game box score')
  assert.deepEqual(result.table.teams, ['TOR', 'MIN'])
  const rows = Object.fromEntries(result.table.rows.map(([name, ...values]) => [name, values]))
  assert.deepEqual(rows['Field goals'], ['35/91', '43/77'])
  assert.deepEqual(rows['FG%'], ['38.5%', '55.8%'])
  assert.deepEqual(rows['Three-pointers'], ['10/38', '15/31'])
  assert.deepEqual(rows['3P%'], ['26.3%', '48.4%'])
  assert.deepEqual(rows['Rebounds'], ['34', '49'])
  assert.deepEqual(rows['Defensive rebounds'], ['20', '40'])
  assert.deepEqual(rows['Offensive rebounds'], ['14', '9'])
  assert.equal(result.source, 'nba_s3:liveData')
})

test('legacy score-only packets remain usable without inventing a box score', () => {
  const result = describePacket(snapshot())
  assert.equal(result.title, 'Final score')
  assert.deepEqual(result.facts, [['Away', 94], ['Home', 117]])
  assert.equal(result.table, undefined)
})

test('zero statistics stay zero while missing statistics stay unavailable', () => {
  const result = describePacket(snapshot([{ team_abbr: 'TOR', fgm: 0, fga: 0, fg_pct: 0, reb: 0 }]))
  const rows = Object.fromEntries(result.table.rows.map(([name, ...values]) => [name, values]))
  assert.deepEqual(rows['Field goals'], ['0/0'])
  assert.deepEqual(rows['FG%'], ['0.0%'])
  assert.deepEqual(rows['Rebounds'], ['0'])
  assert.deepEqual(rows['Three-pointers'], ['–'])
  assert.deepEqual(rows['Defensive rebounds'], ['–'])
})

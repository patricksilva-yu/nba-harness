// Team identity for scores and charts. `dark` keeps navy/black teams readable
// on dark backgrounds.
const TEAMS = {
  ATL: ['Hawks', '#C8102E', '#F0535F'],
  BOS: ['Celtics', '#007A33', '#3DB26A'],
  BKN: ['Nets', '#1F1F1F', '#C9C9C9'],
  CHA: ['Hornets', '#1D1160', '#00A3B4'],
  CHI: ['Bulls', '#CE1141', '#F2506F'],
  CLE: ['Cavaliers', '#860038', '#E0668C'],
  DAL: ['Mavericks', '#00538C', '#4F9BE0'],
  DEN: ['Nuggets', '#1D428A', '#6F9BD6'],
  DET: ['Pistons', '#C8102E', '#F0535F'],
  GSW: ['Warriors', '#1D428A', '#FFC72C'],
  HOU: ['Rockets', '#CE1141', '#F2506F'],
  IND: ['Pacers', '#002D62', '#FDBB30'],
  LAC: ['Clippers', '#C8102E', '#F0535F'],
  LAL: ['Lakers', '#552583', '#A07CD1'],
  MEM: ['Grizzlies', '#5D76A9', '#8FA5D4'],
  MIA: ['Heat', '#98002E', '#E25577'],
  MIL: ['Bucks', '#00471B', '#4CAF6E'],
  MIN: ['Timberwolves', '#236192', '#5C9BD1'],
  NOP: ['Pelicans', '#0C2340', '#C8A15A'],
  NYK: ['Knicks', '#006BB6', '#5E9DEB'],
  OKC: ['Thunder', '#007AC1', '#4FB0EC'],
  ORL: ['Magic', '#0077C0', '#4FA9E6'],
  PHI: ['76ers', '#006BB6', '#5E9DEB'],
  PHX: ['Suns', '#1D1160', '#E56020'],
  POR: ['Trail Blazers', '#E03A3E', '#F26A6D'],
  SAC: ['Kings', '#5A2D81', '#9C6FD0'],
  SAS: ['Spurs', '#63676A', '#C4CED4'],
  TOR: ['Raptors', '#CE1141', '#F2506F'],
  UTA: ['Jazz', '#002B5C', '#F9A01B'],
  WAS: ['Wizards', '#002B5C', '#E8475A'],
}

const NEUTRAL = ['', '#71717A', '#A1A1AA']

export function team(abbr) {
  let [name, color, dark] = TEAMS[abbr] ?? NEUTRAL
  return { abbr, name: name || abbr, color, dark }
}

function distance(a, b) {
  let rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  let [x, y] = [rgb(a), rgb(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
}

// Two teams in one chart must be told apart; the home side yields to neutral.
export function matchupColors(awayAbbr, homeAbbr) {
  let away = team(awayAbbr)
  let home = team(homeAbbr)
  if (distance(away.color, home.color) < 90 || distance(away.dark, home.dark) < 90) {
    home = { ...home, color: NEUTRAL[1], dark: NEUTRAL[2] }
  }
  return { away, home }
}

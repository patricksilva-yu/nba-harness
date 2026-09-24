// Full team names by conference, in the order the picker shows them.
export const CONFERENCES = [
  {
    name: 'Eastern Conference',
    teams: [
      ['ATL', 'Atlanta Hawks'], ['BOS', 'Boston Celtics'], ['BKN', 'Brooklyn Nets'], ['CHA', 'Charlotte Hornets'],
      ['CHI', 'Chicago Bulls'], ['CLE', 'Cleveland Cavaliers'], ['DET', 'Detroit Pistons'], ['IND', 'Indiana Pacers'],
      ['MIA', 'Miami Heat'], ['MIL', 'Milwaukee Bucks'], ['NYK', 'New York Knicks'], ['ORL', 'Orlando Magic'],
      ['PHI', 'Philadelphia 76ers'], ['TOR', 'Toronto Raptors'], ['WAS', 'Washington Wizards'],
    ],
  },
  {
    name: 'Western Conference',
    teams: [
      ['DAL', 'Dallas Mavericks'], ['DEN', 'Denver Nuggets'], ['GSW', 'Golden State Warriors'], ['HOU', 'Houston Rockets'],
      ['LAC', 'LA Clippers'], ['LAL', 'Los Angeles Lakers'], ['MEM', 'Memphis Grizzlies'], ['MIN', 'Minnesota Timberwolves'],
      ['NOP', 'New Orleans Pelicans'], ['OKC', 'Oklahoma City Thunder'], ['PHX', 'Phoenix Suns'],
      ['POR', 'Portland Trail Blazers'], ['SAC', 'Sacramento Kings'], ['SAS', 'San Antonio Spurs'], ['UTA', 'Utah Jazz'],
    ],
  },
]

const FULL_NAMES = Object.fromEntries(CONFERENCES.flatMap((conference) => conference.teams))

export const fullName = (abbr) => FULL_NAMES[abbr] ?? abbr

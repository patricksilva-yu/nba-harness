# Post-game pipeline

After a followed team's game, the pipeline loads the game's stats once they are
complete and runs the harness once to produce a shared **breakdown**. Fans open
it from their home page and ask follow-ups from there.

## One pass

`python -m api.nba_agent.pipeline` makes one pass over today's and yesterday's
games (US Eastern; late games finish after midnight) and exits:

1. **Find finals.** Refresh the season's results from the league game log and
   queue every final involving a team at least one user follows. Games nobody
   follows are never loaded.
2. **Load and check.** Load the box scores and play-by-play, then accept the game
   only when both teams' box-score points equal the final, both teams have player
   rows, advanced stats exist, and the last play-by-play score equals the final.
   Otherwise the game waits for a later pass.
3. **Analyze.** Run the harness with "What decided this game?" in the
   `investigation` configuration. Only a `supported` result becomes the
   breakdown. The run has no owner and is shared by every fan.

Each game has one row in `game_pipeline`: `pending → loaded → analyzed`, or
`failed`. Every step checks and updates that row, so passes can repeat, overlap
with missed ones and resume after errors without double work. Loading retries
every 15 minutes for about four hours (the NBA can publish stats well after the
final); an unsupported analysis retries once more, because each run costs model
tokens. `last_error` says why a game is waiting or failed.

`created_at`, `loaded_at` and `analyzed_at` record when the final was first
seen, when its stats were complete and when the breakdown was ready. Query them
during the season to measure how long the NBA takes to publish complete stats.

### Options

| Option | Use |
|---|---|
| `--date 2026-06-13` | Process this date instead of today and yesterday (repeatable). Replays ignore the game window. |
| `--no-sync` | Use results already stored instead of fetching the league game log. |
| `--max-analyses N` | Harness runs allowed in this pass (default 5). |
| `--max-games N` | Games processed in this pass (default 10). |

A replay of a past date is the way to test changes against real games:

```bash
python -m api.nba_agent.pipeline --date 2026-06-13 --no-sync --max-analyses 1
```

## Schedule

`stats.nba.com` does not answer requests from cloud providers: tested from a
GitHub Actions runner on 2026-09-24, all four endpoints the pipeline needs timed
out after 30 s, while the same calls from a home connection took 0.2 s. The
NBA's `cdn.nba.com` live data returned Access Denied to every client that day,
including a browser (possibly because of the offseason; recheck in October).
The pipeline therefore runs on a machine with a home connection.

On a Mac, launchd runs it every 15 minutes:

```bash
python scripts/pipeline_schedule.py install     # start
python scripts/pipeline_schedule.py uninstall   # stop
```

Output goes to `~/Library/Logs/nba-harness-pipeline.log`. The pipeline itself
skips runs outside the game window (7 pm to 2 am Eastern, from noon on
weekends), so those runs cost nothing. launchd does not run jobs while the Mac
sleeps; the first run after waking catches up. Any always-on machine with cron
works the same way.

To schedule it from GitHub Actions instead, with run history and failure emails,
use a self-hosted runner registered to a **separate private repository** that
holds the workflow and secrets and checks out this repository read-only. GitHub
advises against self-hosted runners on public repositories, because anyone can
open a pull request that runs code on them. Run only one of the two schedules.

## Serving

`GET /api/games/{game_id}/breakdown` returns the breakdown shaped like any
answer in a conversation, or 404 until one exists. Any signed-in user can
follow it up: only runs the pipeline recorded as breakdowns are open this way.
A follow-up starts the user's own conversation, seeded with the breakdown's
verified evidence, so fans never see each other's questions. Opening that
conversation shows the breakdown above the user's first question.

## Cost

One breakdown for 2026 Finals Game 5 used 8 model turns, 6 tool calls, about
71k input and 2k output tokens. Breakdowns are shared, so the model cost grows
with the number of followed games, not with the number of fans. Set the
`NBA_HARNESS_*_USD_PER_MILLION` rates to record each run's cost, and
`--max-analyses` bounds a pass. Supabase's free tier and launchd cost nothing.

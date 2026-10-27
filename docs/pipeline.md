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

The goal is to run the pipeline on GitHub-hosted Actions in this repository
instead. That depends on `cdn.nba.com` answering from GitHub's runners during the
season, since `stats.nba.com` never does. The `NBA CDN probe` workflow
(`.github/workflows/nba-cdn-probe.yml`) checks this daily and keeps the raw
responses of successful calls as an artifact to build a CDN loader against. If
the CDN stays closed to cloud runners into the regular season, the fallback is a
commercial data provider. Self-hosted runners are not an option for this public
repository: GitHub advises against them, because anyone can open a pull request
that runs code on them.

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

## S3 overnight collection

The S3 loader is selected with `NBA_DATA_SOURCE=s3` (default remains `stats`).
It discovers completed games from `NBA/staticData/scheduleLeagueV2.json` and
atomically saves each game's team/player box scores and play-by-play. It checks
feed game IDs, final status, player/team score agreement, period coverage and a
matching Game End score before changing stored data. Retries replace per-game
rows without duplicates; a failed transaction preserves the previous bundle.
Player-minute validation allows up to one second of rounding per roster row.
Play-by-play storage keys follow the published array order, not `actionNumber`:
corrections receive new IDs even when they belong earlier in the timeline.
Original action numbers remain in the captured raw response. The schedule
refresh retains fully imported games and updates results-only rows.
It covers the season currently published by the NBA, not arbitrary historical
seasons. Previously stored results remain available for game resolution.

S3 bundles intentionally have no fabricated official advanced-stat rows. The
existing advanced-context tool supplies labeled box-score estimates when those
rows are missing; official pace, ratings, possessions and PIE remain unavailable.
The pipeline and cache accept validated S3 bundles without official advanced
rows. Official imports still require their advanced rows. Rotations are limited
to clearly qualified substitution context. The API/MCP process should also set
`NBA_DATA_SOURCE=s3` so uncached questions do not contact blocked stats endpoints.
No PostgreSQL schema changes are required for this loader.

`.github/workflows/nba-nightly.yml` runs at 10:30 pm and 1:00 am Eastern
(`America/Toronto`), once it is on the default branch. The timezone-aware
schedules follow daylight saving time. The first pass collects early finals;
the 1 am pass catches later finals and retries incomplete data. Games that end
after the second pass are picked up by the next run's seven-day catch-up. Each run discovers finals
from the last seven Eastern dates, records all final results, and loads details
only for teams fans follow. Previously queued games remain eligible for retry.
The workflow serializes runs and caps each pass at 100 games. Failed discovery
or a game waiting for retry gives a failing run and a JSON summary, so a green
run does not hide an unsuccessful pull. Source requests retry three times with
bounded timeouts. A failed game's next pipeline attempt is on the next run;
manual dispatch can retry sooner after the 15-minute retry delay.

Required repository secret: `POSTGRES_CONNECTION_STRING`, pointing to the same
migrated database as the app. Optional repository variable: `NBA_POSTGRES_SCHEMA`.
Do not place credentials in workflow files. The workflow never migrates the
application database. GitHub scheduled jobs can be delayed and public-repository
schedules can be disabled after inactivity; check Actions when a daily update is
missing. GitHub/Supabase free-tier limits still apply.

Scheduled collection uses `--max-analyses 0`: no model calls or model charges.
Games appear in the home page with their final scores and can be asked about;
a shared AI breakdown is not generated until analysis is explicitly enabled.
Manual collection permits at most five paid breakdowns. That requires an
`OPENAI_API_KEY` repository secret and an explicit `NBA_OPENAI_MODEL` variable.

To run locally with the configured application database:

```bash
source .venv/bin/activate
NBA_DATA_SOURCE=s3 python -m api.nba_agent.pipeline --overnight --max-games 100 --max-analyses 0
```

A manual workflow defaults to **smoke only**, which imports an actual overtime
game twice into a disposable PostgreSQL service, exercises analysis evidence,
and makes no model calls. Choose `smoke_only=false` to collect into the app's
database. `scripts/check_nba_s3.py` refuses non-local/non-test database targets.
Run it locally only with the explicit disposable database configuration from
`docs/postgresql-development.md`; migrations must be applied to that disposable
database first. The access probe and raw-sample artifacts are diagnostic only;
the nightly collector writes directly to PostgreSQL.

### October 26 validation

Live tests passed from GitHub against disposable PostgreSQL, including the
pipeline, favorites home query, actual MCP calls and duplicate-free replay.
A stats-only GitHub run also connected to the restored application database.
Six completed Toronto/New York games from the seven-day catch-up window were
loaded and the pending queue was cleared. The full local regression suite with
the explicit disposable PostgreSQL URL passed: 225 tests. No model calls were
made; shared AI breakdowns remain disabled on the scheduled collector.

[End-to-end GitHub smoke test](https://github.com/patricksilva-yu/nba-harness/actions/runs/40413566737)
and [app database collection test](https://github.com/patricksilva-yu/nba-harness/actions/runs/40413817408).

## Browsing collected games

NBA home cards distinguish saved final scores from available box scores. When
there is no shared breakdown, selecting a game opens its saved overview: team
comparison, scoring leaders and the scoring timeline when play-by-play exists.
`GET /api/games/{game_id}/overview` requires sign-in and only reads the datastore;
it never starts ingestion or an AI run. Results-only games show the final score
and an explanation that detailed stats have not been collected yet. The same
view is available for NBA games selected from the recent-finals sidebar.

Questions remain an explicit action through the suggested questions or composer.
Those use the existing verified analysis harness and can incur model costs.
Existing shared breakdowns still open directly. No migration is required.

See [real NBA question and follow-up verification](nba-flow-verification.md) for
the live-model browser checks, discovered fixes and remaining human acceptance
coverage.

"""Post-game pipeline: load followed teams' finals once their stats are complete,
then run the harness once per game to produce a shared breakdown.

Each run is one pass over today's and yesterday's games (US Eastern) and exits,
so a scheduler can call it repeatedly; per-game state makes every step safe to
repeat. Outside the evening game window a scheduled run exits at once. Replay a
past date to test against real games:

    python -m api.nba_agent.pipeline --date 2026-06-13
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from api.nba_agent.db import get_storage
from api.nba_agent.harness import run_harness
from api.nba_agent.storage.pipeline import GamePipelineRepository
from api.nba_agent.sync_results import sync_results
from api.nba_agent.tools import ensure_game_cached, season_for_date

BREAKDOWN_QUESTION = "What decided this game?"
RETRY_DELAY = timedelta(minutes=15)
# Stats can trail the final by hours; analysis failures cost money, so they retry less.
MAX_LOAD_ATTEMPTS = 16
MAX_ANALYSIS_ATTEMPTS = 2


EASTERN = ZoneInfo("America/New_York")
# Eastern hours when finals land: evenings, plus afternoons on weekends. Hours
# before 2 am belong to the previous night's window.
WEEKDAY_START_HOUR, WEEKEND_START_HOUR, END_HOUR = 19, 12, 2


def in_game_window(now: datetime) -> bool:
    local = now.astimezone(EASTERN)
    if local.hour < END_HOUR:
        return True
    return local.hour >= (WEEKEND_START_HOUR if local.weekday() >= 5 else WEEKDAY_START_HOUR)


def eastern_dates(today: date | None = None) -> list[str]:
    """Today and yesterday on the US East Coast, where late games finish after midnight."""
    today = today or datetime.now(EASTERN).date()
    return [today.isoformat(), (today - timedelta(days=1)).isoformat()]


def load(repository: GamePipelineRepository, game: dict) -> bool:
    game_id = game["game_id"]
    try:
        if repository.missing_stats(game_id):
            ensure_game_cached(game_id, season_type=game["season_type"], force_refresh=True)
        missing = repository.missing_stats(game_id)
    except Exception as exc:
        missing = f"load failed: {type(exc).__name__}"
    if missing:
        repository.retry_later(game_id, missing, RETRY_DELAY, MAX_LOAD_ATTEMPTS)
        return False
    repository.mark_loaded(game_id)
    return True


async def analyze(repository: GamePipelineRepository, game: dict) -> bool:
    game_id = game["game_id"]
    try:
        result = await run_harness(BREAKDOWN_QUESTION, game_id=game_id, season_type=game["season_type"])
    except Exception as exc:
        repository.retry_later(game_id, f"analysis failed: {type(exc).__name__}", RETRY_DELAY, MAX_ANALYSIS_ATTEMPTS)
        return False
    if result["stop_reason"] != "supported":
        repository.retry_later(game_id, f"analysis stopped: {result['stop_reason']}", RETRY_DELAY, MAX_ANALYSIS_ATTEMPTS)
        return False
    repository.mark_analyzed(game_id, result["analysis_run_id"])
    return True


async def run_once(dates: list[str], *, sync: bool = True, max_games: int = 10, max_analyses: int = 5) -> dict:
    storage = get_storage()
    storage.initialize()
    repository = GamePipelineRepository(storage)
    summary = {"dates": dates, "sync_errors": [], "loaded": [], "analyzed": [], "waiting": []}

    if sync:
        for season in sorted({season_for_date(day) for day in dates}):
            try:
                sync_results([season])
            except Exception as exc:
                summary["sync_errors"].append(f"{season}: {type(exc).__name__}")
    repository.enqueue(repository.followed_finals(dates))

    analyses = 0
    for game in repository.due(max_games):
        if game["status"] == "pending":
            if not load(repository, game):
                summary["waiting"].append(game["game_id"])
                continue
            summary["loaded"].append(game["game_id"])
        if analyses >= max_analyses:
            continue
        analyses += 1
        (summary["analyzed"] if await analyze(repository, game) else summary["waiting"]).append(game["game_id"])
    return summary


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", action="append", help="Game date (YYYY-MM-DD) to process instead of today and yesterday; repeatable.")
    parser.add_argument("--no-sync", action="store_true", help="Use stored results instead of fetching the league game log.")
    parser.add_argument("--max-games", type=int, default=10)
    parser.add_argument("--max-analyses", type=int, default=5, help="Harness runs allowed in this pass (each costs model tokens).")
    args = parser.parse_args()
    if not args.date and not in_game_window(datetime.now(EASTERN)):
        print(json.dumps({"skipped": "outside the game window"}))
        return 0
    summary = asyncio.run(run_once(args.date or eastern_dates(), sync=not args.no_sync,
                                   max_games=args.max_games, max_analyses=args.max_analyses))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Record every completed game's final score for one or more seasons.

Question answering already refreshes the current season's results when it
resolves a game. Use this to backfill past seasons or refresh on a schedule:

    python -m api.nba_agent.sync_results --season 2025-26 --season 2024-25
"""

from __future__ import annotations

import argparse

from api.nba_agent.db import DEFAULT_DB
from api.nba_agent.official_ingest import current_nba_season, fetch_recent_completed_games

SEASON_TYPES = ("Regular Season", "Playoffs")


def sync_results(seasons: list[str], season_types: tuple[str, ...] = SEASON_TYPES, timeout: int = 30) -> list[dict]:
    synced = []
    for season in seasons:
        for season_type in season_types:
            games = fetch_recent_completed_games(season, season_type, limit=10_000, timeout=timeout, db_path=DEFAULT_DB)
            synced.append({"season": season, "season_type": season_type, "games": len(games)})
    return synced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", action="append", help="Season such as 2025-26; repeatable. Defaults to the current season.")
    parser.add_argument("--season-type", action="append", choices=SEASON_TYPES)
    args = parser.parse_args()
    for row in sync_results(args.season or [current_nba_season()], tuple(args.season_type or SEASON_TYPES)):
        print(f"{row['season']} {row['season_type']}: {row['games']} games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

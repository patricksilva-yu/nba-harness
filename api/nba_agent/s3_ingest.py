"""Read public NBA S3 schedule, box scores and play-by-play without stats.nba.com."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from api.nba_agent.db import DEFAULT_DB, get_storage
from api.nba_agent.official_ingest import clock_to_pctimestring, season_for_game
from api.nba_agent.storage.nba_live import NBALiveRepository, SOURCE

BASE = "https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA"
WARNINGS = [
    "Official advanced ratings, pace, possessions and PIE are unavailable from this source. "
    "Advanced context uses labeled box-score estimates when official rows are absent.",
    "Official rotations are unavailable; substitution events do not establish five-player lineups.",
]


def data_source():
    import os
    source = os.getenv("NBA_DATA_SOURCE", "stats").lower()
    if source not in {"stats", "s3"}:
        raise ValueError("NBA_DATA_SOURCE must be stats or s3")
    return source


def validate_game_id(game_id):
    if not re.fullmatch(r"00[1245]\d{7}", str(game_id)):
        raise ValueError("Expected a ten-digit NBA game ID")


def fetch_json(path, timeout=20):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}/{path}", timeout=timeout) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(0.5 * 2 ** attempt)


def game_record(game, game_date, source):
    gid = str(game["gameId"])
    validate_game_id(gid)
    season, season_type = season_for_game(gid, None, "Regular Season")
    home, away = game["homeTeam"], game["awayTeam"]
    result = {"game_id": gid, "season_id": gid[2] + season[:4], "game_date": game_date,
              "season_type": season_type, "home_score": int(home["score"]), "away_score": int(away["score"]),
              "source": source}
    for side, team in (("home", home), ("away", away)):
        result.update({f"{side}_team_id": str(team["teamId"]), f"{side}_team_abbr": team["teamTricode"],
                       f"{side}_team_name": f"{team.get('teamCity', '')} {team['teamName']}".strip()})
    return result


def schedule_results(payload, season=None, season_type=None):
    schedule = payload["leagueSchedule"]
    if season and schedule["seasonYear"] != season:
        raise ValueError("S3 schedule does not cover the requested season")
    games = []
    for day in schedule["gameDates"]:
        game_date = datetime.strptime(day["gameDate"], "%m/%d/%Y %H:%M:%S").date().isoformat()
        for game in day["games"]:
            if game["gameStatus"] != 3 or str(game["gameId"])[:3] not in {"001", "002", "004", "005"}:
                continue
            record = game_record(game, game_date, "nba_s3:results")
            if not season_type or record["season_type"] == season_type:
                record["season"] = season_for_game(record["game_id"], None, "Regular Season")[0]
                record["label"] = f"{record['away_team_abbr']} {record['away_score']}, {record['home_team_abbr']} {record['home_score']}"
                games.append(record)
    return sorted(games, key=lambda g: (g["game_date"], g["game_id"]), reverse=True)


def sync_s3_results(season=None, season_type=None, db_path=DEFAULT_DB, timeout=20):
    payload = fetch_json("staticData/scheduleLeagueV2.json", timeout)
    games = schedule_results(payload, season, season_type)
    storage = get_storage(db_path)
    storage.initialize()
    NBALiveRepository(storage).save_results(games, payload)
    return games


STAT_KEYS = ("fieldGoalsMade", "fieldGoalsAttempted", "fieldGoalsPercentage", "threePointersMade",
             "threePointersAttempted", "threePointersPercentage", "freeThrowsMade", "freeThrowsAttempted",
             "freeThrowsPercentage", "reboundsOffensive", "reboundsDefensive", "reboundsTotal", "assists",
             "steals", "blocks", "turnovers", "foulsPersonal", "points", "plusMinusPoints")


def stat_values(stats, team=False, margin=None):
    values = []
    for key in STAT_KEYS:
        if team and key == "turnovers":
            value = stats["turnoversTotal"]
        elif team and key == "reboundsTotal":
            value = stats["reboundsPersonal"]
        elif team and key == "plusMinusPoints":
            value = margin
        else:
            value = stats[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Missing or invalid box-score stat: {key}")
        values.append(value)
    return values


def minutes(value):
    match = re.fullmatch(r"PT(?:(\d+)M)?([\d.]+)S", str(value))
    if not match:
        raise ValueError("Invalid live-data minutes")
    return int(match[1] or 0) + float(match[2]) / 60


def event_type(action):
    kind = action["actionType"]
    if kind in {"2pt", "3pt"}:
        return 1 if action.get("shotResult") == "Made" else 2
    return {"freethrow": 3, "rebound": 4, "turnover": 5, "foul": 6, "violation": 7,
            "substitution": 8, "timeout": 9, "jumpball": 10,
            "period": 12 if action.get("subType") == "start" else 13}.get(kind)


def parse_bundle(game_id, box, pbp):
    validate_game_id(game_id)
    game = box["game"]
    if game["gameId"] != game_id or pbp["game"]["gameId"] != game_id or game["gameStatus"] != 3:
        raise ValueError("Both feeds must identify the requested completed game")
    local_date = datetime.fromisoformat(game["gameTimeUTC"].replace("Z", "+00:00")).astimezone(
        ZoneInfo("America/New_York")).date().isoformat()
    record = game_record(game, local_date, SOURCE)
    if record["home_score"] == record["away_score"]:
        raise ValueError("Final NBA game cannot be tied")
    teams, players, events = [], [], []
    for side, other in (("home", "away"), ("away", "home")):
        team = game[f"{side}Team"]
        score = record[f"{side}_score"]
        margin = score - record[f"{other}_score"]
        stats = team["statistics"]
        if stats["points"] != score:
            raise ValueError("Team box score differs from the final")
        teams.append([game_id, side, str(team["teamId"]), team["teamTricode"],
                      *stat_values(stats, team=True, margin=margin), SOURCE])
        total = 0
        total_minutes = 0.0
        for player in team["players"]:
            ps = player["statistics"]
            duration = minutes(ps["minutes"])
            # DNP rows retain names and zero statistics, not fabricated minutes.
            values = stat_values(ps)
            total += ps["points"]
            total_minutes += duration
            players.append([game_id, str(player["personId"]), player["name"], team["teamTricode"],
                            duration, *values, SOURCE])
        if abs(total_minutes - minutes(stats["minutes"])) > len(team["players"]) / 60 + 0.001:
            raise ValueError("Player minutes do not match team total")
        if not team["players"] or total != score:
            raise ValueError("Player points do not match team total")
    actions = pbp["game"]["actions"]
    if not actions:
        raise ValueError("Missing play-by-play")
    last = actions[-1]
    if (last["actionType"], last.get("subType")) != ("game", "end"):
        raise ValueError("Play-by-play has not reached Game End")
    if (int(last["scoreHome"]), int(last["scoreAway"])) != (record["home_score"], record["away_score"]):
        raise ValueError("Play-by-play does not match final score")
    periods = {int(a["period"]) for a in actions}
    if periods != set(range(1, int(game["period"]) + 1)):
        raise ValueError("Play-by-play is missing a period")
    ids = set()
    # The published array is chronological. Corrected actions can carry a new,
    # higher actionNumber while belonging earlier in the game. Store a sequence
    # key for existing SQL timelines; original action IDs remain in the raw feed.
    for sequence, action in enumerate(actions, start=1):
        event = int(action["actionNumber"])
        if event in ids:
            raise ValueError("Duplicate play-by-play action")
        ids.add(event)
        team_id = str(action["teamId"]) if action.get("teamId") else None
        description = action.get("description")
        home = team_id == record["home_team_id"]
        away = team_id == record["away_team_id"]
        sh, sa = int(action["scoreHome"]), int(action["scoreAway"])
        events.append([game_id, sequence, event_type(action), None, int(action["period"]),
                       clock_to_pctimestring(action["clock"]), description if home else None,
                       description if not home and not away else None, description if away else None,
                       f"{sa} - {sh}", sa, sh,
                       str(action["personId"]) if action.get("personId") else None,
                       action.get("playerName"), team_id, action.get("teamTricode"), SOURCE])
    return record, teams, players, events


def import_s3_game_bundle(game_id, db_path=DEFAULT_DB, timeout=20, **_):
    validate_game_id(game_id)
    box = fetch_json(f"liveData/boxscore/boxscore_{game_id}.json", timeout)
    pbp = fetch_json(f"liveData/playbyplay/playbyplay_{game_id}.json", timeout)
    record, teams, players, events = parse_bundle(game_id, box, pbp)
    storage = get_storage(db_path)
    storage.initialize()
    written = NBALiveRepository(storage).save_bundle(record, teams, players, events, box, pbp)
    return {"game_id": game_id, "source": SOURCE, "written": written,
            "team_rows": len(teams), "player_rows": len(players), "pbp_rows": len(events), "warnings": WARNINGS}


def main():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id")
    args = parser.parse_args()
    try:
        result = import_s3_game_bundle(args.game_id) if args.game_id else {"results": len(sync_s3_results())}
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # Upstream/driver exceptions may include connection details.
        print(json.dumps({"error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

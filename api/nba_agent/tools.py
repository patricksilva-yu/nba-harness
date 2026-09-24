#!/usr/bin/env python3
"""Tool-like JSON functions for the NBA analyst cache and evidence layer."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from api.nba_agent.db import DEFAULT_DB, get_storage
from api.nba_agent.official_ingest import (
    fetch_recent_completed_games,
    import_official_game_bundle,
)
from api.nba_agent.storage import StorageConnection, StorageError
from api.nba_agent.storage.repositories import EvidenceRepository


ROOT = Path(__file__).resolve().parents[2]
GAME_RESOLUTION_SEASON_TYPES = ("Playoffs", "Regular Season")


def decode_storage_json(value: Any) -> Any:
    """Normalize JSON text from DuckDB and decoded JSONB from PostgreSQL."""
    return json.loads(value) if isinstance(value, str) else value


def packet_id(*parts: object) -> str:
    return "_".join(str(part).replace(":", "").replace(" ", "-").lower() for part in parts)


def persist_evidence_packets(
    game_id: str,
    packets: list[dict[str, Any]],
    db_path: Path = DEFAULT_DB,
) -> bool:
    if not packets:
        return True
    try:
        EvidenceRepository(get_storage(db_path)).save_many(game_id, packets)
        return True
    except StorageError:
        return False


def with_persisted_packets(
    game_id: str,
    response: dict[str, Any],
    db_path: Path = DEFAULT_DB,
    persist: bool = True,
) -> dict[str, Any]:
    if persist:
        persist_evidence_packets(game_id, response.get("evidence_packets", []), db_path)
    return response


def find_recent_completed_games(
    season: str | None = None,
    season_type: str = "Playoffs",
    limit: int = 10,
    timeout: int = 20,
) -> dict[str, Any]:
    games = fetch_recent_completed_games(
        season=season,
        season_type=season_type,
        limit=limit,
        timeout=timeout,
        db_path=DEFAULT_DB,
    )
    return {
        "summary": {
            "resolution_status": "available",
            "season": season,
            "season_type": season_type,
            "count": len(games),
            "source": "nba_api:LeagueGameLog",
        },
        "games": games,
        "warnings": [],
    }


def resolution_season_type_order(season_type: str | None) -> list[str]:
    if not season_type or season_type.lower() == "auto":
        return list(GAME_RESOLUTION_SEASON_TYPES)
    requested = season_type
    ordered = [requested]
    ordered.extend(item for item in GAME_RESOLUTION_SEASON_TYPES if item != requested)
    return ordered


def find_recent_completed_games_for_resolution(
    season: str | None = None,
    season_type: str | None = "Auto",
    limit: int = 20,
    timeout: int = 20,
) -> dict[str, Any]:
    games_by_id: dict[str, dict[str, Any]] = {}
    source_status: list[dict[str, Any]] = []
    for type_to_search in resolution_season_type_order(season_type):
        try:
            response = find_recent_completed_games(
                season=season,
                season_type=type_to_search,
                limit=limit,
                timeout=timeout,
            )
            games = response.get("games", [])
            source_status.append(
                {
                    "season_type": type_to_search,
                    "status": "ok",
                    "count": len(games),
                }
            )
            for game in games:
                games_by_id.setdefault(game["game_id"], game)
        except Exception as exc:
            source_status.append(
                {
                    "season_type": type_to_search,
                    "status": "error",
                    # The exception type only: upstream messages can carry request detail.
                    "error": type(exc).__name__,
                }
            )
    games = sorted(games_by_id.values(), key=lambda item: (item["game_date"], item["game_id"]), reverse=True)
    return {
        "summary": {
            "resolution_status": "available",
            "requested_season_type": season_type,
            "searched_season_types": [item["season_type"] for item in source_status],
            "count": len(games),
            "source": "nba_api:LeagueGameLog",
        },
        "games": games[:limit],
        "source_status": source_status,
        "warnings": [
            f"Could not search {item['season_type']}: {item['error']}"
            for item in source_status
            if item["status"] == "error"
        ],
    }


TEAM_ALIASES = {
    "atl": {"atl", "hawks", "atlanta"},
    "bos": {"bos", "celtics", "boston"},
    "bkn": {"bkn", "nets", "brooklyn"},
    "cha": {"cha", "hornets", "charlotte"},
    "chi": {"chi", "bulls", "chicago"},
    "cle": {"cle", "cavs", "cavaliers", "cleveland"},
    "dal": {"dal", "mavs", "mavericks", "dallas"},
    "den": {"den", "nuggets", "denver"},
    "det": {"det", "pistons", "detroit"},
    "gsw": {"gsw", "warriors", "golden state"},
    "hou": {"hou", "rockets", "houston"},
    "ind": {"ind", "pacers", "indiana"},
    "lac": {"lac", "clippers", "la clippers"},
    "lal": {"lal", "lakers", "la lakers"},
    "mem": {"mem", "grizzlies", "memphis"},
    "mia": {"mia", "heat", "miami"},
    "mil": {"mil", "bucks", "milwaukee"},
    "min": {"min", "wolves", "timberwolves", "minnesota"},
    "nop": {"nop", "pelicans", "new orleans"},
    "nyk": {"nyk", "knicks", "new york"},
    "okc": {"okc", "thunder", "oklahoma city"},
    "orl": {"orl", "magic", "orlando"},
    "phi": {"phi", "sixers", "76ers", "philadelphia"},
    "phx": {"phx", "suns", "phoenix"},
    "por": {"por", "blazers", "trail blazers", "portland"},
    "sac": {"sac", "kings", "sacramento"},
    "sas": {"sas", "spurs", "san antonio"},
    "tor": {"tor", "raptors", "toronto"},
    "uta": {"uta", "jazz", "utah"},
    "was": {"was", "wizards", "washington"},
}


# Abbreviations that are also everyday words ("it was close", "36 min") count
# only when typed in capitals, the way a team abbreviation is written.
CAPITALS_ONLY_ALIASES = {"was", "min", "den", "mil", "sac", "por"}


def matching_team_abbrs(query: str) -> set[str]:
    """Teams named in a question, matched as whole words so "show" is not Houston."""
    normalized = query.lower()
    matches: set[str] = set()
    for abbr, aliases in TEAM_ALIASES.items():
        for alias in aliases:
            capitals = alias in CAPITALS_ONLY_ALIASES
            pattern = rf"\b{re.escape(alias.upper() if capitals else alias)}\b"
            if re.search(pattern, query if capitals else normalized):
                matches.add(abbr.upper())
                break
    return matches


MONTHS = {name: number for number, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for name in names}
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))


def resolved_date(year: int | None, month: int, day: int, today: date) -> date | None:
    """A written date; without a year, the most recent such date not in the future."""
    if year is not None and year < 100:
        year += 2000
    try:
        if year is not None:
            return date(year, month, day)
        candidate = date(today.year, month, day)
        return candidate if candidate <= today else date(today.year - 1, month, day)
    except ValueError:
        return None


def requested_game_date(query: str, today: date | None = None) -> str | None:
    text = query.lower()
    today = today or date.today()
    explicit = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if explicit:
        return explicit.group(1)
    written = (
        # "April 12, 2026", "Apr 12 2026", "April 12th", "April 12"
        re.search(rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", text),
        # "12 April 2026", "12th of April"
        re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_PATTERN})\b(?:,?\s+(\d{{4}}))?", text),
    )
    if written[0]:
        month, day, year = written[0].groups()
        found = resolved_date(int(year) if year else None, MONTHS[month], int(day), today)
        if found:
            return str(found)
    if written[1]:
        day, month, year = written[1].groups()
        found = resolved_date(int(year) if year else None, MONTHS[month], int(day), today)
        if found:
            return str(found)
    # US numeric dates: "4/12/2026", "4/12/26", or "on 4/12". A bare "5/12" is
    # more often a shooting split ("5/12 from three") than a date.
    numeric = (re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b", text)
               or re.search(r"\bon\s+(\d{1,2})/(\d{1,2})()(?![/\d])", text))
    if numeric:
        month, day, year = numeric.groups()
        found = resolved_date(int(year) if year else None, int(month), int(day), today) if 1 <= int(month) <= 12 else None
        if found:
            return str(found)
    if "last night" in text or "yesterday" in text:
        return str(today - timedelta(days=1))
    return None


def season_for_date(value: str) -> str:
    """NBA season containing a date: seasons start in October."""
    day = date.fromisoformat(value)
    start_year = day.year if day.month >= 10 else day.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def requests_latest_game(query: str) -> bool:
    """'Last game', 'latest', 'most recent outing': pick the newest match instead of asking."""
    text = query.lower()
    return bool(
        re.search(r"\b(?:latest|most recent)\b", text)
        or re.search(r"\blast(?:\s+\S+){0,2}?\s+(?:game|match|outing)\b", text)
    )


def requested_playoff_game_number(query: str) -> int | None:
    match = re.search(r"\bgame\s+([1-7])\b", query.lower())
    if not match:
        return None
    return int(match.group(1))


# Checked in order: "conference finals" before "finals"; "semifinals" never matches "finals".
PLAYOFF_ROUND_PATTERNS = (
    (3, r"\b(?:conference|conf|east(?:ern)?|west(?:ern)?)(?: conference)? finals\b|\b(?:ecf|wcf)\b"),
    (2, r"\bsemi-?finals\b|\bsemis\b|\b(?:second|2nd) round\b"),
    (4, r"\bfinals\b"),
    (1, r"\b(?:first|1st|opening) round\b"),
)


def requested_playoff_round(query: str) -> int | None:
    text = query.lower()
    for playoff_round, pattern in PLAYOFF_ROUND_PATTERNS:
        if re.search(pattern, text):
            return playoff_round
    return None


PLAYOFF_ROUND_NAMES = {1: "First Round", 2: "Conference Semifinals", 3: "Conference Finals", 4: "NBA Finals"}


def playoff_position(game_id: str) -> tuple[int, int] | None:
    """(round, game number) from an NBA playoff game id: 004 YY 00 round series game."""
    match = re.fullmatch(r"004\d{2}00(\d)\d(\d)", str(game_id))
    return (int(match.group(1)), int(match.group(2))) if match else None


def number_series_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach playoff round and game-in-series, preferring the game id's own encoding.

    Games whose ids do not follow the playoff pattern are numbered by date
    within their matchup; they have no known round.
    """
    by_matchup: dict[frozenset, list[dict[str, Any]]] = {}
    for game in games:
        by_matchup.setdefault(frozenset((game["home_team_abbr"], game["away_team_abbr"])), []).append(game)
    order = {}
    for matchup_games in by_matchup.values():
        for index, game in enumerate(sorted(matchup_games, key=lambda g: (g["game_date"], g["game_id"]))):
            order[game["game_id"]] = index + 1
    numbered = []
    for game in games:
        position = playoff_position(game["game_id"])
        playoff_round, number = position if position else (None, order[game["game_id"]])
        numbered.append({**game, "playoff_round": playoff_round, "series_game_number": number})
    return numbered


def same_matchup(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return {a["home_team_abbr"], a["away_team_abbr"]} == {b["home_team_abbr"], b["away_team_abbr"]}


def compact_game(game: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_id": game["game_id"],
        "game_date": game["game_date"],
        "label": game["label"],
        "home_team_abbr": game["home_team_abbr"],
        "away_team_abbr": game["away_team_abbr"],
        "home_score": game["home_score"],
        "away_score": game["away_score"],
        "match_score": game.get("match_score"),
        "series_game_number": game.get("series_game_number"),
        "season_type": game.get("season_type"),
    }


def unplayed_series_game(
    query: str,
    series_games: list[dict[str, Any]],
    requested_game_number: int,
    matched_teams: set[str],
    recent: dict[str, Any],
) -> dict[str, Any] | None:
    """A numbered game beyond the series' length: say how the series went instead of guessing."""
    latest = max(series_games, key=lambda g: (g["game_date"], g["game_id"]))
    series = sorted((g for g in series_games if same_matchup(g, latest) and g.get("playoff_round") == latest.get("playoff_round")),
                    key=lambda g: (g["game_date"], g["game_id"]))
    played = max(g["series_game_number"] for g in series)
    if requested_game_number <= played:
        return None
    wins: dict[str, int] = {latest["home_team_abbr"]: 0, latest["away_team_abbr"]: 0}
    for game in series:
        winner = game["home_team_abbr"] if game["home_score"] > game["away_score"] else game["away_team_abbr"]
        wins[winner] += 1
    leader = max(wins, key=wins.get)
    return {
        "summary": {
            "resolution_status": "game_not_played",
            "query": query,
            "matched_teams": sorted(matched_teams),
            "requested_game_number": requested_game_number,
            "series": {
                "round": latest.get("playoff_round"),
                "round_name": PLAYOFF_ROUND_NAMES.get(latest.get("playoff_round")),
                "games_played": played,
                "wins": wins,
                "winner": leader if wins[leader] == 4 else None,
                "last_game": compact_game(series[-1]),
            },
            "searched_season_types": recent.get("summary", {}).get("searched_season_types", []),
        },
        "candidates": [compact_game(game) for game in reversed(series)],
        "source_status": recent.get("source_status", []),
        "warnings": recent.get("warnings", []) + [f"Game {requested_game_number} of this series was not played."],
    }


def resolve_game_reference(
    query: str,
    season: str | None = None,
    season_type: str = "Auto",
    limit: int = 20,
    timeout: int = 20,
) -> dict[str, Any]:
    requested_date = requested_game_date(query)
    # A dated game belongs to the season containing that date, not the current one.
    if requested_date and season is None:
        season = season_for_date(requested_date)
    requested_year_match = re.search(r"\b(?:19|20)\d{2}\b", query)
    requested_year = int(requested_year_match.group()) if requested_year_match else None
    requested_game_number = requested_playoff_game_number(query)
    # A numbered playoff game in a calendar year belongs to the season that
    # started the previous fall. Do not let a current-season lookup win by date.
    if requested_year and requested_game_number and (season is None or season == str(requested_year)):
        season = f"{requested_year - 1}-{str(requested_year)[-2:]}"
    # Resolution needs a deeper source window than the display limit. Otherwise
    # an older playoff game can be missed after later rounds add more games.
    # A dated question can name any game in its season, so search all of it.
    source_limit = 10_000 if requested_date else max(limit, 120)
    recent = find_recent_completed_games_for_resolution(
        season=season,
        season_type=season_type,
        limit=source_limit,
        timeout=timeout,
    )
    games = recent.get("games", [])
    matched_teams = matching_team_abbrs(query)
    requested_round = requested_playoff_round(query)
    latest = not requested_date and requests_latest_game(query)
    preference = "exact_date_match" if requested_date else "latest_game" if latest else "disambiguate_repeated_matchups"

    candidates = []
    for game in games:
        teams = {game["home_team_abbr"], game["away_team_abbr"]}
        score = len(matched_teams & teams)
        if not matched_teams:
            score = 1
        if len(matched_teams) >= 2 and score < len(matched_teams):
            continue
        if score > 0:
            candidates.append({**game, "match_score": score})

    if requested_date:
        candidates = [candidate for candidate in candidates if str(candidate["game_date"])[:10] == requested_date]
    elif requested_year:
        candidates = [candidate for candidate in candidates if str(candidate["game_date"])[:4] == str(requested_year)]

    if (requested_game_number or requested_round) and matched_teams:
        series_candidates = number_series_games([
            candidate
            for candidate in candidates
            if str(candidate.get("season_type", "")).lower() == "playoffs"
            and matched_teams.issubset({candidate["home_team_abbr"], candidate["away_team_abbr"]})
        ])
        # "Game 5" alone means game 5 of a series, never the team's fifth playoff game.
        # Without a named round, the most recent matching series is selected below.
        matches = [
            candidate
            for candidate in series_candidates
            if (not requested_game_number or candidate["series_game_number"] == requested_game_number)
            and (not requested_round or candidate["playoff_round"] == requested_round)
        ]
        if matches:
            candidates = matches
            preference = "playoff_series_game_match"
        elif series_candidates and requested_game_number:
            not_played = unplayed_series_game(query, series_candidates, requested_game_number, matched_teams, recent)
            if not_played:
                return not_played
            candidates = series_candidates

    if not candidates:
        return {
            "summary": {
                "resolution_status": "not_found",
                "query": query,
                "matched_teams": sorted(matched_teams),
                "requested_date": requested_date,
                "requested_game_number": requested_game_number,
                "requested_season_type": season_type,
                "searched_season_types": recent.get("summary", {}).get("searched_season_types", []),
            },
            # The source window can be a whole season for dated questions; return only the display limit.
            "recent_games": games[:limit],
            "source_status": recent.get("source_status", []),
            "warnings": recent.get("warnings", []) + ["No recent completed game matched the query."],
        }

    candidates = sorted(candidates, key=lambda game: (game["match_score"], game["game_date"], game["game_id"]), reverse=True)
    selected = candidates[0]

    same_score_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("match_score") == selected.get("match_score")
    ]
    repeated_matchup_candidates = [
        candidate
        for candidate in same_score_candidates
        if same_matchup(candidate, selected)
    ]
    # Candidates are newest first, so a request for the latest game is already resolved.
    if not requested_date and not latest and matched_teams and len(repeated_matchup_candidates) > 1:
        return {
            "summary": {
                "resolution_status": "ambiguous",
                "query": query,
                "matched_teams": sorted(matched_teams),
                "requested_date": requested_date,
                "requested_game_number": requested_game_number,
                "requested_season_type": season_type,
                "searched_season_types": recent.get("summary", {}).get("searched_season_types", []),
                "confidence": "low",
            },
            "candidates": [compact_game(candidate) for candidate in repeated_matchup_candidates[:5]],
            "source_status": recent.get("source_status", []),
            "warnings": recent.get("warnings", []) + [
                "Multiple completed games matched the same teams. Provide a date or game_id."
            ],
        }

    return {
        "summary": {
            "resolution_status": "resolved",
            "query": query,
            "preference": preference,
            "matched_teams": sorted(matched_teams),
            "requested_date": requested_date,
            "requested_game_number": requested_game_number,
            "requested_playoff_round": requested_round,
            "game_id": selected["game_id"],
            "label": selected["label"],
            "game_date": selected["game_date"],
            "series_game_number": selected.get("series_game_number"),
            "season_type": selected.get("season_type"),
            "requested_season_type": season_type,
            "searched_season_types": recent.get("summary", {}).get("searched_season_types", []),
            "confidence": "medium" if matched_teams else "low",
        },
        "game": compact_game(selected),
        "candidates": [compact_game(candidate) for candidate in candidates[:3]],
        "source_status": recent.get("source_status", []),
        "warnings": recent.get("warnings", []) if matched_teams else recent.get("warnings", []) + ["No team was specified; selected the latest completed game."],
    }


def get_cached_games_status(
    db_path: Path = DEFAULT_DB,
    limit: int = 20,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    advanced_table_exists = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = 'box_scores_advanced_team'
        """
    ).fetchone()[0] > 0
    advanced_count_sql = (
        "(SELECT COUNT(*) FROM box_scores_advanced_team bat WHERE bat.game_id = g.game_id)"
        if advanced_table_exists
        else "0"
    )
    rows = con.execute(
        f"""
        SELECT
            g.game_id,
            g.game_date,
            g.away_team_abbr || ' ' || g.away_score || ', ' || g.home_team_abbr || ' ' || g.home_score AS label,
            g.source,
            (SELECT COUNT(*) FROM box_scores_team bst WHERE bst.game_id = g.game_id) AS team_rows,
            {advanced_count_sql} AS advanced_rows,
            (SELECT COUNT(*) FROM box_scores_player bsp WHERE bsp.game_id = g.game_id) AS player_rows,
            (SELECT COUNT(*) FROM play_by_play_events pbp WHERE pbp.game_id = g.game_id) AS pbp_rows,
            (SELECT COUNT(*) FROM evidence_packets ep WHERE ep.game_id = g.game_id) AS evidence_rows
        FROM games g
        -- Results-only rows (every game's final score) are not cached games.
        WHERE EXISTS (SELECT 1 FROM box_scores_team bst WHERE bst.game_id = g.game_id)
        ORDER BY g.game_date DESC NULLS LAST, g.game_id DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    games = [dict(zip(cols, row)) for row in rows]
    for game in games:
        game["complete"] = (
            game["team_rows"] >= 2
            and game["advanced_rows"] >= 2
            and game["player_rows"] > 0
            and game["pbp_rows"] > 0
        )
        game["game_date"] = str(game["game_date"]) if game["game_date"] is not None else None
    return {
        "summary": {
            "database": str(db_path),
            "cached_game_count": len(games),
            "advanced_table_exists": advanced_table_exists,
        },
        "games": games,
        "warnings": [],
    }


def ensure_game_cached(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not force_refresh:
        try:
            con = get_storage(db_path).open()
            counts = con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_name = 'box_scores_advanced_team'
                """
            ).fetchone()[0]
            advanced_table_exists = counts > 0
            counts = con.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM games WHERE game_id = ?) AS game_rows,
                    (SELECT COUNT(*) FROM box_scores_team WHERE game_id = ?) AS team_rows,
                    (SELECT COUNT(*) FROM box_scores_player WHERE game_id = ?) AS player_rows,
                    (SELECT COUNT(*) FROM play_by_play_events WHERE game_id = ?) AS pbp_rows
                """,
                [game_id, game_id, game_id, game_id],
            ).fetchone()
            advanced_rows = 0
            if advanced_table_exists:
                advanced_rows = con.execute(
                    "SELECT COUNT(*) FROM box_scores_advanced_team WHERE game_id = ?",
                    [game_id],
                ).fetchone()[0]
            con.close()
            game_rows, team_rows, player_rows, pbp_rows = counts
            has_required_cache = game_rows >= 1 and team_rows >= 2 and player_rows > 0 and pbp_rows > 0 and advanced_rows >= 2
            if has_required_cache:
                return {
                    "summary": {
                        "game_id": game_id,
                        "cache_status": "already_cached",
                        "game_rows": game_rows,
                        "team_rows": team_rows,
                        "player_rows": player_rows,
                        "pbp_rows": pbp_rows,
                        "advanced_rows": advanced_rows,
                    },
                    "ingested": False,
                    "warnings": [],
                }
        except StorageError:
            pass

    ingest_result = import_official_game_bundle(
        game_id=game_id,
        db_path=db_path,
        season=season,
        season_type=season_type,
        timeout=timeout,
    )
    return {
        "summary": {
            "game_id": game_id,
            "cache_status": "refreshed" if force_refresh else "cached_from_official",
            "source": "nba_api",
            "ingest_summary": ingest_result.get("summary", ingest_result) if isinstance(ingest_result, dict) else None,
        },
        "ingested": True,
        "warnings": [],
    }


def pct(numerator: float | None, denominator: float | None) -> float | None:
    if denominator in (None, 0):
        return None
    if numerator is None:
        return None
    return round(float(numerator) / float(denominator), 4)


def diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(float(a) - float(b), 4)


def get_game_snapshot(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    game = con.execute("SELECT * FROM games WHERE game_id = ?", [game_id]).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    cols = [d[0] for d in con.description]
    game_row = dict(zip(cols, game))
    source_provider = "nba_official" if str(game_row.get("source", "")).startswith("nba_api:") else "local_fixture"
    teams = con.execute(
        """
        SELECT team_side, team_abbr, fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
               ftm, fta, oreb, dreb, reb, ast, stl, blk, tov, pf, pts
        FROM box_scores_team
        WHERE game_id = ?
        ORDER BY team_side
        """,
        [game_id],
    ).fetchall()
    team_cols = [d[0] for d in con.description]
    team_rows = [dict(zip(team_cols, row)) for row in teams]
    winner_abbr = (
        game_row["away_team_abbr"]
        if game_row["away_score"] > game_row["home_score"]
        else game_row["home_team_abbr"]
    )
    loser_abbr = (
        game_row["home_team_abbr"]
        if winner_abbr == game_row["away_team_abbr"]
        else game_row["away_team_abbr"]
    )
    winner_score = max(game_row["away_score"], game_row["home_score"])
    loser_score = min(game_row["away_score"], game_row["home_score"])
    packet = {
        "packet_id": packet_id("snapshot", game_id),
        "type": "game_snapshot",
        "claim_seed": (
            f"{winner_abbr} defeated {loser_abbr} "
            f"{winner_score}-{loser_score}."
        ),
        "source": {"provider": source_provider, "detail": game_row.get("source")},
        "evidence_level": "core",
        "confidence": "high",
        "metrics": {
            "away_score": game_row["away_score"],
            "home_score": game_row["home_score"],
            "team_box": team_rows,
        },
    }
    con.close()
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "label": (
                f"{game_row['away_team_abbr']} {game_row['away_score']}, "
                f"{game_row['home_team_abbr']} {game_row['home_score']}"
            ),
            "date": str(game_row["game_date"]),
            "season_type": game_row["season_type"],
            "confidence": "high",
        },
        "team_box": team_rows,
        "evidence_packets": [packet],
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packet["packet_id"],
                "description": "Show the game and team box rows behind this snapshot.",
            }
        ],
        "warnings": [],
    }, db_path, persist=persist)


def get_box_score(
    game_id: str,
    level: str = "team",
    detail: bool = False,
    db_path: Path = DEFAULT_DB,
) -> dict[str, Any]:
    level = level.lower()
    con = get_storage(db_path).open()
    game = con.execute("SELECT game_id FROM games WHERE game_id = ?", [game_id]).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    if level == "team":
        rows = con.execute(
            """
            SELECT *
            FROM box_scores_team
            WHERE game_id = ?
            ORDER BY team_side
            """,
            [game_id],
        ).fetchall()
    elif level == "player":
        order_sql = "ORDER BY pts DESC NULLS LAST, plus_minus DESC NULLS LAST"
        limit_sql = "" if detail else "LIMIT 10"
        rows = con.execute(
            f"""
            SELECT *
            FROM box_scores_player
            WHERE game_id = ?
            {order_sql}
            {limit_sql}
            """,
            [game_id],
        ).fetchall()
    else:
        con.close()
        return {
            "summary": {
                "resolution_status": "invalid_level",
                "game_id": game_id,
                "level": level,
            },
            "warnings": ["level must be 'team' or 'player'."],
        }
    cols = [d[0] for d in con.description]
    con.close()
    rows_as_dicts = [dict(zip(cols, row)) for row in rows]
    return {
        "summary": {
            "game_id": game_id,
            "level": level,
            "detail": detail,
            "row_count": len(rows_as_dicts),
            "confidence": "high" if rows_as_dicts else "low",
        },
        "box_score": rows_as_dicts,
        "available_expansions": [] if detail else [
            {
                "tool": "game_context.get_box_score",
                "description": f"Request detail=true for the full {level} box score.",
            }
        ],
        "warnings": [] if rows_as_dicts else [f"No {level} box-score rows are cached for this game."],
    }


def clock_to_elapsed_seconds(period: int | None, clock: str | None) -> float | None:
    if period is None or not clock or ":" not in clock:
        return None
    minutes, seconds = clock.split(":", 1)
    try:
        remaining = int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return ((int(period) - 1) * 720) + (720 - remaining)


def infer_lineup_stints_from_substitutions(
    game_id: str,
    db_path: Path = DEFAULT_DB,
) -> int:
    con = get_storage(db_path).open(read_only=False)
    rows = con.execute(
        """
        SELECT eventnum, period, pctimestring, homedescription, visitordescription,
               player1_id, player1_name, player1_team_id, player1_team_abbreviation
        FROM play_by_play_events
        WHERE game_id = ? AND eventmsgtype = 8
        ORDER BY period, eventnum
        """,
        [game_id],
    ).fetchall()
    cols = [d[0] for d in con.description]
    substitutions = [dict(zip(cols, row)) for row in rows]
    if not substitutions:
        con.close()
        return 0
    con.execute("DELETE FROM lineup_stints WHERE game_id = ? AND source = ?", [game_id, "pbp_substitution_inferred_v1"])
    inferred_rows = []
    for sub in substitutions:
        description = sub.get("homedescription") or sub.get("visitordescription") or ""
        match = re.search(r"SUB:\s*(.*?)\s+FOR\s+(.*)", description, flags=re.IGNORECASE)
        incoming_name = match.group(1).strip() if match else None
        outgoing_name = sub.get("player1_name") or (match.group(2).strip() if match else None)
        team_abbr = sub.get("player1_team_abbreviation")
        elapsed = clock_to_elapsed_seconds(sub.get("period"), sub.get("pctimestring"))
        for role, player_name in (("in", incoming_name), ("out", outgoing_name)):
            if not player_name:
                continue
            stint_id = packet_id("lineup-inferred", game_id, sub["eventnum"], role, player_name)
            inferred_rows.append(
                [
                    stint_id,
                    game_id,
                    team_abbr,
                    sub.get("player1_team_id"),
                    sub.get("player1_id") if role == "out" else None,
                    player_name,
                    sub.get("period"),
                    sub.get("pctimestring") if role == "in" else None,
                    sub.get("pctimestring") if role == "out" else None,
                    sub.get("eventnum") if role == "in" else None,
                    sub.get("eventnum") if role == "out" else None,
                    elapsed if role == "in" else None,
                    elapsed if role == "out" else None,
                    None,
                    None,
                    None,
                    "pbp_substitution_inferred_v1",
                    "low",
                    "Substitution-derived rotation event, not an official five-man lineup stint.",
                ]
            )
    if inferred_rows:
        con.executemany(
            """
            INSERT INTO lineup_stints (
                stint_id, game_id, team_abbr, team_id, player_id, player_name,
                period, start_clock, end_clock, start_eventnum, end_eventnum,
                start_elapsed_seconds, end_elapsed_seconds, duration_seconds,
                player_pts, plus_minus, source, confidence, caveat
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (stint_id) DO UPDATE SET
                game_id = EXCLUDED.game_id,
                team_abbr = EXCLUDED.team_abbr,
                team_id = EXCLUDED.team_id,
                player_id = EXCLUDED.player_id,
                player_name = EXCLUDED.player_name,
                period = EXCLUDED.period,
                start_clock = EXCLUDED.start_clock,
                end_clock = EXCLUDED.end_clock,
                start_eventnum = EXCLUDED.start_eventnum,
                end_eventnum = EXCLUDED.end_eventnum,
                start_elapsed_seconds = EXCLUDED.start_elapsed_seconds,
                end_elapsed_seconds = EXCLUDED.end_elapsed_seconds,
                duration_seconds = EXCLUDED.duration_seconds,
                player_pts = EXCLUDED.player_pts,
                plus_minus = EXCLUDED.plus_minus,
                source = EXCLUDED.source,
                confidence = EXCLUDED.confidence,
                caveat = EXCLUDED.caveat
            """,
            inferred_rows,
        )
    con.close()
    return len(inferred_rows)


def get_lineup_stints(
    game_id: str,
    team: str | None = None,
    period: int | None = None,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    game = con.execute("SELECT game_id FROM games WHERE game_id = ?", [game_id]).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    filters = ["game_id = ?"]
    params: list[Any] = [game_id]
    if team:
        filters.append("upper(team_abbr) = upper(?)")
        params.append(team)
    if period:
        filters.append("period = ?")
        params.append(period)
    where_sql = " AND ".join(filters)
    count = con.execute(f"SELECT COUNT(*) FROM lineup_stints WHERE {where_sql}", params).fetchone()[0]
    con.close()
    if count == 0:
        infer_lineup_stints_from_substitutions(game_id, db_path)
    con = get_storage(db_path).open()
    rows = con.execute(
        f"""
        SELECT stint_id, team_abbr, player_id, player_name, period, start_clock,
               end_clock, start_eventnum, end_eventnum, duration_seconds,
               player_pts, plus_minus, source, confidence, caveat
        FROM lineup_stints
        WHERE {where_sql}
        ORDER BY COALESCE(start_elapsed_seconds, end_elapsed_seconds, 999999), team_abbr, player_name
        LIMIT 30
        """,
        params,
    ).fetchall()
    cols = [d[0] for d in con.description]
    source_counts = con.execute(
        """
        SELECT source, COUNT(*)
        FROM lineup_stints
        WHERE game_id = ?
        GROUP BY source
        ORDER BY source
        """,
        [game_id],
    ).fetchall()
    con.close()
    stints = [dict(zip(cols, row)) for row in rows]
    source_provider = "nba_official" if any(stint["source"] == "nba_api:GameRotation" for stint in stints) else "local_inference"
    confidence = "high" if source_provider == "nba_official" else "low"
    packet = {
        "packet_id": packet_id("lineups", game_id, team or "all", period or "all"),
        "type": "lineup_stints",
        "claim_seed": "Rotation stint context is available for the requested game scope.",
        "metrics": {
            "returned_stints": len(stints),
            "team": team,
            "period": period,
            "source_counts": {source: count for source, count in source_counts},
        },
        "source": {
            "provider": source_provider,
            "detail": "nba_api:GameRotation" if source_provider == "nba_official" else "play_by_play_events substitutions",
        },
        "evidence_level": "rotation_context" if source_provider == "nba_official" else "inferred_rotation_context",
        "confidence": confidence,
        "caveats": [] if source_provider == "nba_official" else [
            "Fallback rows are substitution-derived rotation events, not validated five-man lineup stints."
        ],
    }
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "team": team,
            "period": period,
            "stint_count": len(stints),
            "lineup_model": "official_game_rotation" if source_provider == "nba_official" else "pbp_substitution_inferred_v1",
            "confidence": confidence,
        },
        "stints": stints,
        "evidence_packets": [packet],
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packet["packet_id"],
                "description": "Show rotation source and stint rows behind this packet.",
            }
        ],
        "warnings": packet["caveats"],
    }, db_path, persist=persist)


def scoring_events(con: StorageConnection, game_id: str) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT eventnum, period, pctimestring, homedescription, visitordescription,
               score_away, score_home
        FROM play_by_play_events
        WHERE game_id = ?
          AND score_away IS NOT NULL
          AND score_home IS NOT NULL
        ORDER BY period, eventnum
        """,
        [game_id],
    ).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, row)) for row in rows]


def game_elapsed_minutes(period: int, clock: str | None) -> float | None:
    """Minutes since tip-off; regulation quarters are 12 minutes, overtimes 5."""
    if not clock or ":" not in clock:
        return None
    minutes, seconds = clock.split(":", 1)
    length = 12 if period <= 4 else 5
    start = (period - 1) * 12 if period <= 4 else 48 + (period - 5) * 5
    return round(start + length - (int(minutes) + float(seconds) / 60), 3)


def get_game_flow(game_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Score margin at every scoring change, for display beside an answer.

    This is page context, not agent evidence: claims still cite MCP packets.
    """
    con = get_storage(db_path).open()
    try:
        game = con.execute(
            "SELECT home_team_abbr, away_team_abbr, home_score, away_score FROM games WHERE game_id = ?",
            [game_id],
        ).fetchone()
        if not game:
            return {"game_id": game_id, "status": "not_found", "points": []}
        events = scoring_events(con, game_id)
    finally:
        con.close()
    home_abbr, away_abbr, home_score, away_score = game
    points = [{"period": 1, "clock": "12:00", "minute": 0.0, "away_score": 0, "home_score": 0, "margin": 0}]
    for event in events:
        minute = game_elapsed_minutes(int(event["period"]), event["pctimestring"])
        if minute is None:
            continue
        away, home = int(event["score_away"]), int(event["score_home"])
        if (away, home) == (points[-1]["away_score"], points[-1]["home_score"]):
            continue
        points.append({"period": int(event["period"]), "clock": event["pctimestring"], "minute": minute,
                       "away_score": away, "home_score": home, "margin": away - home})
    periods = max([p["period"] for p in points] + [4])
    return {
        "game_id": game_id, "status": "ok" if len(points) > 1 else "no_play_by_play",
        "away_team_abbr": away_abbr, "home_team_abbr": home_abbr,
        "away_score": away_score, "home_score": home_score,
        "periods": periods, "length_minutes": 48 + max(0, periods - 4) * 5,
        "margin_perspective": "away", "points": points,
    }


def find_decisive_runs(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    max_events: int = 16,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    game = con.execute(
        "SELECT home_team_abbr, away_team_abbr, home_score, away_score FROM games WHERE game_id = ?",
        [game_id],
    ).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    home_abbr, away_abbr, home_score, away_score = game
    winning_team = away_abbr if away_score > home_score else home_abbr
    events = scoring_events(con, game_id)
    pbp_source = con.execute(
        "SELECT source FROM play_by_play_events WHERE game_id = ? AND source IS NOT NULL LIMIT 1",
        [game_id],
    ).fetchone()
    source_detail = pbp_source[0] if pbp_source else "old/nba.sqlite:play_by_play"
    source_provider = "nba_official" if str(source_detail).startswith("nba_api:") else "local_fixture"
    candidates: list[dict[str, Any]] = []
    for start_idx in range(len(events)):
        start = events[start_idx]
        start_margin_away = start["score_away"] - start["score_home"]
        for end_idx in range(start_idx + 3, min(len(events), start_idx + max_events)):
            end = events[end_idx]
            away_delta = end["score_away"] - start["score_away"]
            home_delta = end["score_home"] - start["score_home"]
            score_delta = away_delta - home_delta
            abs_delta = abs(score_delta)
            if abs_delta < 7:
                continue
            end_margin_away = end["score_away"] - end["score_home"]
            beneficiary = away_abbr if score_delta > 0 else home_abbr
            start_margin_for_beneficiary = start_margin_away if beneficiary == away_abbr else -start_margin_away
            end_margin_for_beneficiary = end_margin_away if beneficiary == away_abbr else -end_margin_away
            lead_flip_bonus = 3 if start_margin_for_beneficiary <= 0 < end_margin_for_beneficiary else 0
            lead_extension_bonus = 2 if start_margin_for_beneficiary > 0 and end_margin_for_beneficiary > start_margin_for_beneficiary else 0
            winner_bonus = 8 if beneficiary == winning_team else 0
            late_bonus = max(0, start["period"] - 2) * 2
            clutch_bonus = 4 if start["period"] >= 4 and end_margin_for_beneficiary <= 10 else 0
            opening_penalty = -5 if start["period"] == 1 and start["score_away"] == 0 and start["score_home"] == 0 else 0
            rank_score = (
                abs_delta
                + winner_bonus
                + lead_flip_bonus
                + lead_extension_bonus
                + late_bonus
                + clutch_bonus
                + opening_penalty
            )
            candidates.append(
                {
                    "rank_score": rank_score,
                    "beneficiary": beneficiary,
                    "winning_team": winning_team,
                    "period_start": start["period"],
                    "clock_start": start["pctimestring"],
                    "period_end": end["period"],
                    "clock_end": end["pctimestring"],
                    "start_eventnum": start["eventnum"],
                    "end_eventnum": end["eventnum"],
                    "away_delta": away_delta,
                    "home_delta": home_delta,
                    "score_delta_for_beneficiary": abs_delta,
                    "start_margin_for_beneficiary": start_margin_for_beneficiary,
                    "end_margin_for_beneficiary": end_margin_for_beneficiary,
                    "rank_factors": {
                        "winner_bonus": winner_bonus,
                        "lead_flip_bonus": lead_flip_bonus,
                        "lead_extension_bonus": lead_extension_bonus,
                        "late_bonus": late_bonus,
                        "clutch_bonus": clutch_bonus,
                        "opening_penalty": opening_penalty,
                    },
                    "start_score": f"{away_abbr} {start['score_away']}, {home_abbr} {start['score_home']}",
                    "end_score": f"{away_abbr} {end['score_away']}, {home_abbr} {end['score_home']}",
                }
            )
    candidates = sorted(candidates, key=lambda item: item["rank_score"], reverse=True)[:3]
    packets = []
    for idx, candidate in enumerate(candidates, start=1):
        pid = packet_id("run", game_id, idx, candidate["start_eventnum"], candidate["end_eventnum"])
        compact_metrics = {
            "beneficiary": candidate["beneficiary"],
            "period_start": candidate["period_start"],
            "clock_start": candidate["clock_start"],
            "period_end": candidate["period_end"],
            "clock_end": candidate["clock_end"],
            "start_eventnum": candidate["start_eventnum"],
            "end_eventnum": candidate["end_eventnum"],
            "score_delta_for_beneficiary": candidate["score_delta_for_beneficiary"],
            "start_margin_for_beneficiary": candidate["start_margin_for_beneficiary"],
            "end_margin_for_beneficiary": candidate["end_margin_for_beneficiary"],
            "start_score": candidate["start_score"],
            "end_score": candidate["end_score"],
            "rank_score": candidate["rank_score"],
        }
        packets.append(
            {
                "packet_id": pid,
                "type": "run_candidate",
                "rank": idx,
                "claim_seed": (
                    f"{candidate['beneficiary']} had a +{candidate['score_delta_for_beneficiary']} "
                    f"scoring window from Q{candidate['period_start']} {candidate['clock_start']} "
                    f"to Q{candidate['period_end']} {candidate['clock_end']}."
                ),
                "window": {
                    "period_start": candidate["period_start"],
                    "clock_start": candidate["clock_start"],
                    "period_end": candidate["period_end"],
                    "clock_end": candidate["clock_end"],
                    "start_eventnum": candidate["start_eventnum"],
                    "end_eventnum": candidate["end_eventnum"],
                },
                "metrics": compact_metrics,
                "source": {"provider": source_provider, "detail": source_detail},
                "evidence_level": "core_inferred",
                "confidence": "medium",
                "caveats": ["Run detection is deterministic v1 scoring-window logic, not a final basketball conclusion."],
            }
        )
    con.close()
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "candidate_count": len(packets),
            "method": "outcome_aware_scoring_window_v2",
            "winning_team": winning_team,
            "confidence": "medium",
        },
        "evidence_packets": packets,
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packet["packet_id"],
                "description": "Show play-by-play events inside this scoring window.",
            }
            for packet in packets
        ],
        "warnings": ["Candidate ranking is a heuristic that prefers winning-team and late-game context."],
    }, db_path, persist=persist)


def get_possession_summary(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    rows = con.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE eventmsgtype IN (1, 2, 3, 5)) AS terminal_like_events,
            COUNT(*) FILTER (WHERE eventmsgtype = 5) AS turnovers,
            COUNT(*) FILTER (WHERE eventmsgtype = 3) AS free_throw_events,
            COUNT(*) FILTER (WHERE eventmsgtype IN (1, 2)) AS shot_events
        FROM play_by_play_events
        WHERE game_id = ?
        """,
        [game_id],
    ).fetchone()
    pbp_source = con.execute(
        "SELECT source FROM play_by_play_events WHERE game_id = ? AND source IS NOT NULL LIMIT 1",
        [game_id],
    ).fetchone()
    con.close()
    terminal_like, turnovers, free_throw_events, shot_events = rows
    source_detail = pbp_source[0] if pbp_source else "old/nba.sqlite:play_by_play"
    source_provider = "nba_official" if str(source_detail).startswith("nba_api:") else "local_fixture"
    packet = {
        "packet_id": packet_id("possession-summary", game_id),
        "type": "possession_segment_summary",
        "claim_seed": "Play-by-play event mix gives a first-pass possession-segment context.",
        "metrics": {
            "terminal_like_events": terminal_like,
            "turnovers": turnovers,
            "free_throw_events": free_throw_events,
            "shot_events": shot_events,
        },
        "source": {"provider": source_provider, "detail": source_detail},
        "evidence_level": "core_inferred",
        "confidence": "medium",
        "caveats": ["This is not a perfect possession model."],
    }
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "possession_model": "pbp_inferred_v1",
            "unit_name": "possession_segment",
            "confidence": "medium",
        },
        "evidence_packets": [packet],
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packet["packet_id"],
                "description": "Show source event counts used by the first-pass possession summary.",
            }
        ],
        "warnings": ["Possession segmentation is intentionally approximate in v1."],
    }, db_path, persist=persist)


def get_advanced_game_context(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    game = con.execute(
        "SELECT away_team_abbr, home_team_abbr FROM games WHERE game_id = ?",
        [game_id],
    ).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    advanced_table_exists = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = 'box_scores_advanced_team'
        """
    ).fetchone()[0] > 0
    if advanced_table_exists:
        advanced_rows = con.execute(
            """
            SELECT team_abbr, offensive_rating, defensive_rating, net_rating,
                   assist_pct, assist_to_turnover, assist_ratio, oreb_pct, dreb_pct,
                   reb_pct, estimated_team_tov_pct, turnover_ratio, efg_pct, ts_pct,
                   pace, possessions, pie, source
            FROM box_scores_advanced_team
            WHERE game_id = ?
            ORDER BY team_abbr
            """,
            [game_id],
        ).fetchall()
        advanced_cols = [d[0] for d in con.description]
        if len(advanced_rows) == 2:
            con.close()
            away_abbr, home_abbr = game
            advanced_by_team = {row["team_abbr"]: row for row in [dict(zip(advanced_cols, r)) for r in advanced_rows]}
            away_metrics = advanced_by_team[away_abbr]
            home_metrics = advanced_by_team[home_abbr]
            metric_edges = {
                "offensive_rating": diff(away_metrics["offensive_rating"], home_metrics["offensive_rating"]),
                "defensive_rating": diff(away_metrics["defensive_rating"], home_metrics["defensive_rating"]),
                "net_rating": diff(away_metrics["net_rating"], home_metrics["net_rating"]),
                "efg_pct": diff(away_metrics["efg_pct"], home_metrics["efg_pct"]),
                "ts_pct": diff(away_metrics["ts_pct"], home_metrics["ts_pct"]),
                "turnover_ratio": diff(away_metrics["turnover_ratio"], home_metrics["turnover_ratio"]),
                "pie": diff(away_metrics["pie"], home_metrics["pie"]),
            }
            leader = away_abbr if (metric_edges["net_rating"] or 0) > 0 else home_abbr
            packet = {
                "packet_id": packet_id("adv", game_id, "official-team-advanced"),
                "type": "advanced_context",
                "claim_seed": (
                    f"Official NBA advanced context favors {leader} by net rating, "
                    "shot quality, and possession efficiency indicators."
                ),
                "metrics": {
                    away_abbr: away_metrics,
                    home_abbr: home_metrics,
                    f"{away_abbr}_minus_{home_abbr}": metric_edges,
                },
                "source": {
                    "provider": "nba_official",
                    "detail": "nba_api:BoxScoreAdvancedV3",
                },
                "evidence_level": "official_advanced",
                "confidence": "high",
                "caveats": [],
            }
            return with_persisted_packets(game_id, {
                "summary": {
                    "game_id": game_id,
                    "advanced_context_source": "nba_official",
                    "headline": f"{leader} had the stronger official advanced profile.",
                    "confidence": "high",
                },
                "team_metrics": packet["metrics"],
                "evidence_packets": [packet],
                "available_expansions": [
                    {
                        "tool": "evidence.rehydrate_evidence_packet",
                        "packet_id": packet["packet_id"],
                        "description": "Show official NBA BoxScoreAdvancedV3 team metrics.",
                    }
                ],
                "warnings": [],
            }, db_path, persist=persist)
    rows = con.execute(
        """
        SELECT team_side, team_abbr, fgm, fga, fg3m, fg3a, ftm, fta,
               oreb, dreb, reb, ast, stl, blk, tov, pts
        FROM box_scores_team
        WHERE game_id = ?
        ORDER BY team_side
        """,
        [game_id],
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    teams = {row["team_side"]: row for row in [dict(zip(cols, r)) for r in rows]}
    if "away" not in teams or "home" not in teams:
        return {"summary": {"resolution_status": "missing_box_score", "game_id": game_id}}

    away = teams["away"]
    home = teams["home"]

    def metrics(team: dict[str, Any], opp: dict[str, Any]) -> dict[str, Any]:
        fga = team["fga"]
        fgm = team["fgm"]
        fg3m = team["fg3m"]
        fta = team["fta"]
        tov = team["tov"]
        oreb = team["oreb"]
        opp_dreb = opp["dreb"]
        # This is the common estimated possession formula. It is a fallback proxy,
        # not official NBA Four Factors output.
        estimated_possessions = float(fga) + 0.44 * float(fta) - float(oreb) + float(tov)
        return {
            "efg_pct": pct(float(fgm) + 0.5 * float(fg3m), fga),
            "three_point_rate": pct(team["fg3a"], fga),
            "free_throw_rate": pct(fta, fga),
            "tov_per_est_possession": pct(tov, estimated_possessions),
            "oreb_pct": pct(oreb, float(oreb) + float(opp_dreb)),
            "ast_to_tov": pct(team["ast"], tov),
            "estimated_possessions": round(estimated_possessions, 2),
            "points_per_est_possession": pct(team["pts"], estimated_possessions),
        }

    away_metrics = metrics(away, home)
    home_metrics = metrics(home, away)
    metric_edges = {
        "efg_pct": diff(away_metrics["efg_pct"], home_metrics["efg_pct"]),
        "three_point_rate": diff(away_metrics["three_point_rate"], home_metrics["three_point_rate"]),
        "free_throw_rate": diff(away_metrics["free_throw_rate"], home_metrics["free_throw_rate"]),
        "tov_per_est_possession": diff(away_metrics["tov_per_est_possession"], home_metrics["tov_per_est_possession"]),
        "oreb_pct": diff(away_metrics["oreb_pct"], home_metrics["oreb_pct"]),
        "points_per_est_possession": diff(
            away_metrics["points_per_est_possession"],
            home_metrics["points_per_est_possession"],
        ),
    }
    away_abbr = away["team_abbr"]
    home_abbr = home["team_abbr"]
    packets = [
        {
            "packet_id": packet_id("adv", game_id, "fallback-four-factors"),
            "type": "advanced_context",
            "claim_seed": (
                f"Fallback box-score advanced context favors {away_abbr} through "
                f"efficiency, turnover margin, and three-point shooting."
            ),
            "metrics": {
                away_abbr: away_metrics,
                home_abbr: home_metrics,
                f"{away_abbr}_minus_{home_abbr}": metric_edges,
            },
            "source": {
                "provider": "local_fallback",
                "detail": "box_scores_team formulas; official NBA advanced endpoints not wired yet",
            },
            "evidence_level": "fallback_advanced",
            "confidence": "medium",
            "caveats": [
                "These are local fallback estimates, not official NBA advanced endpoint values.",
                "Official NBA advanced endpoints should replace these values when available.",
            ],
        }
    ]
    summary_edge = metric_edges["points_per_est_possession"]
    leader = away_abbr if summary_edge is not None and summary_edge > 0 else home_abbr
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "advanced_context_source": "local_fallback",
            "headline": (
                f"{leader} had the stronger fallback advanced profile; "
                "official NBA advanced rows are not cached for this game."
            ),
            "confidence": "medium",
        },
        "team_metrics": {
            away_abbr: away_metrics,
            home_abbr: home_metrics,
            f"{away_abbr}_minus_{home_abbr}": metric_edges,
        },
        "evidence_packets": packets,
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packets[0]["packet_id"],
                "description": "Show local fallback advanced metrics and caveats.",
            }
        ],
        "warnings": [
            "Fallback advanced stats are computed from local team box score until official NBA advanced rows are cached."
        ],
    }, db_path, persist=persist)


def get_player_game_context(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    con = get_storage(db_path).open()
    game = con.execute(
        "SELECT away_team_abbr, home_team_abbr FROM games WHERE game_id = ?",
        [game_id],
    ).fetchone()
    if not game:
        con.close()
        return {"summary": {"resolution_status": "not_found", "game_id": game_id}}
    rows = con.execute(
        """
        SELECT player_id, player_name, team_abbr, minutes, pts, reb, ast, stl, blk,
               tov, fgm, fga, fg3m, fg3a, ftm, fta, plus_minus, source
        FROM box_scores_player
        WHERE game_id = ?
        ORDER BY pts DESC NULLS LAST, plus_minus DESC NULLS LAST
        LIMIT 10
        """,
        [game_id],
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    player_rows = [dict(zip(cols, row)) for row in rows]
    if not player_rows:
        return {
            "summary": {
                "game_id": game_id,
                "resolution_status": "player_box_unavailable",
                "confidence": "low",
            },
            "evidence_packets": [],
            "available_expansions": [],
            "warnings": [
                "No player box-score rows are available in the local cache.",
                "Next data step is official NBA player box-score ingestion for this game.",
            ],
        }

    def compact_player(player: dict[str, Any]) -> dict[str, Any]:
        return {
            "player_name": player["player_name"],
            "team_abbr": player["team_abbr"],
            "minutes": player["minutes"],
            "pts": player["pts"],
            "reb": player["reb"],
            "ast": player["ast"],
            "stl": player["stl"],
            "blk": player["blk"],
            "tov": player["tov"],
            "fg": f"{player['fgm']}-{player['fga']}",
            "fg3": f"{player['fg3m']}-{player['fg3a']}",
            "ft": f"{player['ftm']}-{player['fta']}",
            "plus_minus": player["plus_minus"],
        }

    compact_players = [compact_player(player) for player in player_rows]
    packets = []
    for idx, player in enumerate(player_rows[:5], start=1):
        pid = packet_id("player", game_id, idx, player["player_id"])
        compact = compact_player(player)
        packets.append(
            {
                "packet_id": pid,
                "type": "player_game_context",
                "rank": idx,
                "claim_seed": (
                    f"{player['player_name']} led available local player context with "
                    f"{player['pts']} points, {player['reb']} rebounds, and {player['ast']} assists."
                ),
                "metrics": compact,
                "source": {
                    "provider": "nba_official" if str(player["source"]).startswith("nba_api:") else "local_seed",
                    "detail": player["source"],
                },
                "evidence_level": "core",
                "confidence": "high" if str(player["source"]).startswith("nba_api:") else "medium",
                "caveats": [] if str(player["source"]).startswith("nba_api:") else ["Player names may require enrichment when sourced from seed logs."],
            }
        )
    return with_persisted_packets(game_id, {
        "summary": {
            "game_id": game_id,
            "player_count": len(player_rows),
            "headline": "Top player box-score context is available.",
            "confidence": "medium",
        },
        "players": compact_players,
        "evidence_packets": packets,
        "available_expansions": [
            {
                "tool": "evidence.rehydrate_evidence_packet",
                "packet_id": packet["packet_id"],
                "description": "Show player box-score context packet.",
            }
            for packet in packets
        ],
        "warnings": [],
    }, db_path, persist=persist)


def period_label(period: int) -> str:
    return f"Q{period}" if period <= 4 else ("OT" if period == 5 else f"{period - 4}OT")


def period_length(period: int) -> int:
    return 12 if period <= 4 else 5


def game_events(con: StorageConnection, game_id: str) -> dict[str, Any] | None:
    """Every play-by-play event with its game minute, running score and points scored.

    Shared by periods, time windows and scoring-run details so all three agree.
    """
    game = con.execute(
        "SELECT home_team_abbr, away_team_abbr FROM games WHERE game_id = ?", [game_id]
    ).fetchone()
    if not game:
        return None
    home_abbr, away_abbr = game
    rows = con.execute(
        """
        SELECT eventnum, eventmsgtype, period, pctimestring, homedescription, visitordescription,
               score_away, score_home, player1_name, player1_team_abbreviation, source
        FROM play_by_play_events
        WHERE game_id = ?
        ORDER BY period, eventnum
        """,
        [game_id],
    ).fetchall()
    events = []
    away, home = 0, 0
    source = None
    for eventnum, kind, period, clock, home_text, away_text, score_away, score_home, player, player_team, row_source in rows:
        source = source or row_source
        minute = game_elapsed_minutes(int(period), clock) if period else None
        points = 0
        if score_away is not None and score_home is not None:
            points = (int(score_away) - away) + (int(score_home) - home)
            away, home = int(score_away), int(score_home)
        text = home_text or away_text
        team = home_abbr if home_text else away_abbr if away_text else player_team
        events.append({
            "eventnum": eventnum, "kind": kind, "period": int(period) if period else None, "clock": clock,
            "minute": minute, "description": text, "team": team, "player": player,
            "points": points, "away_score": away, "home_score": home,
        })
    return {"away": away_abbr, "home": home_abbr, "events": events,
            "source_detail": source or "old/nba.sqlite:play_by_play"}


def summarize_events(game: dict[str, Any], selected: list[dict[str, Any]], before: dict[str, Any] | None) -> dict[str, Any]:
    """Plays, team totals and per-player lines for a contiguous slice of events."""
    away, home = game["away"], game["home"]
    start = (before or {}).get("away_score", 0), (before or {}).get("home_score", 0)
    end = (selected[-1]["away_score"], selected[-1]["home_score"]) if selected else start
    blank = lambda: {"pts": 0, "fgm": 0, "fga": 0, "fg3m": 0, "fg3a": 0, "ftm": 0, "fta": 0, "reb": 0, "tov": 0}
    teams = {away: blank(), home: blank()}
    players: dict[tuple[str, str], dict[str, Any]] = {}
    plays = []
    for event in selected:
        if not event["description"]:
            continue
        text = event["description"]
        three = "3PT" in text
        lines = [teams.get(event["team"])]
        if event["player"] and event["kind"] in (1, 2, 3, 4, 5):
            key = (event["player"], event["team"])
            players.setdefault(key, {"player": event["player"], "team": event["team"], **blank()})
            lines.append(players[key])
        for line in filter(None, lines):
            if event["kind"] in (1, 2):
                line["fga"] += 1
                line["fg3a"] += three
                line["fgm"] += event["kind"] == 1
                line["fg3m"] += three and event["kind"] == 1
            elif event["kind"] == 3:
                line["fta"] += 1
                line["ftm"] += event["points"] > 0
            elif event["kind"] == 4:
                line["reb"] += 1
            elif event["kind"] == 5:
                line["tov"] += 1
            line["pts"] += event["points"]
        plays.append({
            "eventnum": event["eventnum"], "period": event["period"], "clock": event["clock"], "team": event["team"],
            "player": event["player"], "description": text, "points": event["points"],
            "score": f"{away} {event['away_score']}, {home} {event['home_score']}" if event["points"] else None,
            "scoring": event["points"] > 0,
        })
    return {
        "score_before": f"{away} {start[0]}, {home} {start[1]}",
        "score_after": f"{away} {end[0]}, {home} {end[1]}",
        "team_points": {away: end[0] - start[0], home: end[1] - start[1]},
        "team_stats": teams,
        "players": sorted((p for p in players.values() if any(p[k] for k in blank())),
                          key=lambda p: (-p["pts"], -p["fgm"], p["player"])),
        "plays": plays,
    }


def run_window_plays(con: StorageConnection, game_id: str, start_event: int, end_event: int) -> dict[str, Any]:
    """Plays and per-player totals inside a scoring-run window, by event number."""
    game = game_events(con, game_id)
    if game is None:
        return summarize_events({"away": "AWAY", "home": "HOME"}, [], None)
    events = game["events"]
    selected = [e for e in events if start_event <= e["eventnum"] <= end_event]
    before = next((e for e in reversed(events) if e["eventnum"] < start_event), None)
    return summarize_events(game, selected, before)


PLAY_LIMIT = 120


def get_game_window(
    game_id: str,
    period: int,
    from_clock: str | None = None,
    to_clock: str = "0:00",
    end_period: int | None = None,
    db_path: Path = DEFAULT_DB,
    persist: bool = False,
) -> dict[str, Any]:
    """What happened in one stretch of game time: score change, team and player lines, and plays."""
    end_period = end_period or period
    from_clock = from_clock or f"{period_length(period)}:00"
    start = game_elapsed_minutes(period, from_clock)
    end = game_elapsed_minutes(end_period, to_clock)
    if start is None or end is None or end < start:
        return {"summary": {"game_id": game_id, "resolution_status": "invalid_window"}, "evidence_packets": []}
    con = get_storage(db_path).open()
    try:
        game = game_events(con, game_id)
    finally:
        con.close()
    if game is None:
        return {"summary": {"game_id": game_id, "resolution_status": "not_found"}, "evidence_packets": []}
    events = [e for e in game["events"] if e["minute"] is not None]
    # Events exactly at the start clock (e.g. free throws after a foul) belong to the window.
    selected = [e for e in events if start <= e["minute"] <= end]
    before = next((e for e in reversed(events) if e["minute"] < start), None)
    summary = summarize_events(game, selected, before)
    away, home = game["away"], game["home"]
    label = f"{period_label(period)} {from_clock} to {period_label(end_period)} {to_clock}"
    points = summary["team_points"]
    leader, trailer = (away, home) if points[away] >= points[home] else (home, away)
    plays = summary.pop("plays")
    caveats = [] if selected else ["No play-by-play events fall inside this window."]
    if len(plays) > PLAY_LIMIT:
        plays = [play for play in plays if play["scoring"] or "Turnover" in play["description"]]
        caveats.append("Long window: only scoring plays and turnovers are listed; totals include every event.")
    source_detail = game["source_detail"]
    packet = {
        "packet_id": packet_id("window", game_id, period_label(period), from_clock, period_label(end_period), to_clock),
        "type": "game_window",
        "claim_seed": (
            f"From {label}, {leader} outscored {trailer} {points[leader]}-{points[trailer]} "
            f"({summary['score_before']} to {summary['score_after']})."
        ),
        "window": {"period_start": period, "clock_start": from_clock, "period_end": end_period, "clock_end": to_clock},
        "metrics": summary,
        "plays": plays,
        "source": {"provider": "nba_official" if str(source_detail).startswith("nba_api:") else "local_fixture",
                   "detail": source_detail},
        "evidence_level": "core",
        "confidence": "high" if selected else "low",
        "caveats": caveats,
    }
    return with_persisted_packets(game_id, {
        "summary": {"game_id": game_id, "window": label, "event_count": len(selected), "play_count": len(plays)},
        "evidence_packets": [packet],
    }, db_path, persist=persist)


def get_period_summary(game_id: str, db_path: Path = DEFAULT_DB, persist: bool = False) -> dict[str, Any]:
    """Quarter-by-quarter scoring, the margin at each break, largest leads and lead changes."""
    con = get_storage(db_path).open()
    try:
        game = game_events(con, game_id)
    finally:
        con.close()
    if game is None:
        return {"summary": {"game_id": game_id, "resolution_status": "not_found"}, "evidence_packets": []}
    away, home = game["away"], game["home"]
    scored = [e for e in game["events"] if e["period"] and e["points"]]
    periods, previous = [], (0, 0)
    for period in sorted({e["period"] for e in game["events"] if e["period"]}):
        last = [e for e in scored if e["period"] <= period]
        score = (last[-1]["away_score"], last[-1]["home_score"]) if last else previous
        periods.append({
            "period": period, "label": period_label(period),
            f"{away}_points": score[0] - previous[0], f"{home}_points": score[1] - previous[1],
            "score_at_end": f"{away} {score[0]}, {home} {score[1]}",
            "leader_at_end": away if score[0] > score[1] else home if score[1] > score[0] else "tied",
            "margin_at_end": abs(score[0] - score[1]),
        })
        previous = score
    largest = {away: None, home: None}
    lead_changes = ties = 0
    leader = None
    for e in scored:
        margin = e["away_score"] - e["home_score"]
        current = away if margin > 0 else home if margin < 0 else None
        if current is None and leader is not None:
            ties += 1
        if current and leader and current != leader:
            lead_changes += 1
        if current:
            leader = current
            if largest[current] is None or abs(margin) > largest[current]["points"]:
                largest[current] = {"points": abs(margin), "period": period_label(e["period"]), "clock": e["clock"],
                                    "score": f"{away} {e['away_score']}, {home} {e['home_score']}"}
        # A tie keeps the previous leader, so a lead retaken after a tie is not a change.
    lead_text = "; ".join(
        f"{team} led by as many as {lead['points']} ({lead['period']} {lead['clock']})"
        for team, lead in largest.items() if lead
    )
    source_detail = game["source_detail"]
    packet = {
        "packet_id": packet_id("periods", game_id),
        "type": "period_summary",
        "claim_seed": f"Final {periods[-1]['score_at_end'] if periods else ''}. {lead_text}. "
                      f"{lead_changes} lead changes, {ties} ties.".strip(),
        "metrics": {"periods": periods, "largest_lead": largest, "lead_changes": lead_changes, "ties": ties},
        "source": {"provider": "nba_official" if str(source_detail).startswith("nba_api:") else "local_fixture",
                   "detail": source_detail},
        "evidence_level": "core",
        "confidence": "high" if scored else "low",
        "caveats": [] if scored else ["No scored play-by-play events are stored for this game."],
    }
    return with_persisted_packets(game_id, {
        "summary": {"game_id": game_id, "periods": len(periods)},
        "evidence_packets": [packet],
    }, db_path, persist=persist)


RESULT_COLUMNS = "game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score"


def result_rows(con: StorageConnection, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
    rows = con.execute(sql, parameters).fetchall()
    games = []
    for game_id, game_date, home, away, home_score, away_score in rows:
        winner = home if home_score > away_score else away
        games.append({"game_id": str(game_id), "date": str(game_date)[:10], "home": home, "away": away,
                      "score": f"{away} {away_score}, {home} {home_score}", "winner": winner})
    return games


def series_context(con: StorageConnection, game: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    """Series state through this game, counted from every stored result of the matchup."""
    position = playoff_position(game["game_id"])
    if position:
        # Playoff ids encode the series: 004 YY 00 round series game.
        games = result_rows(con, f"SELECT {RESULT_COLUMNS} FROM games WHERE game_id LIKE ? AND game_date <= ? "
                                 "ORDER BY game_date, game_id", [game["game_id"][:9] + "%", game["game_date"]])
        numbers = [playoff_position(g["game_id"])[1] for g in games]
    else:
        games = result_rows(con, f"SELECT {RESULT_COLUMNS} FROM games WHERE season_id = ? AND season_type = ? "
                                 "AND ((home_team_abbr = ? AND away_team_abbr = ?) OR (home_team_abbr = ? AND away_team_abbr = ?)) "
                                 "AND game_date <= ? ORDER BY game_date, game_id",
                            [game["season_id"], game["season_type"], game["home_team_abbr"], game["away_team_abbr"],
                             game["away_team_abbr"], game["home_team_abbr"], game["game_date"]])
        numbers = list(range(1, len(games) + 1))
    teams = (game["away_team_abbr"], game["home_team_abbr"])
    wins = {team: 0 for team in teams}
    for g in games[:-1]:
        wins[g["winner"]] += 1
    before = dict(wins)
    this = games[-1]
    wins[this["winner"]] += 1
    winner = this["winner"]
    loser = next(team for team in teams if team != winner)
    number = numbers[-1]
    complete = numbers == list(range(1, len(numbers) + 1))
    if wins[winner] == 4:
        outcome = "clinched_series"
    elif wins[winner] == wins[loser]:
        outcome = "forced_game_7" if wins[winner] == 3 else "tied_series"
    elif wins[winner] > wins[loser]:
        outcome = "took_series_lead" if before[winner] <= before[loser] else "extended_series_lead"
    else:
        outcome = "cut_series_deficit"
    round_name = PLAYOFF_ROUND_NAMES.get(position[0]) if position else None
    stage = f"Game {number}" + (f" of the {round_name}" if round_name else " of the playoff series")
    series_text = f"{winner} {wins[winner]}-{wins[loser]}" if wins[winner] >= wins[loser] else f"{loser} {wins[loser]}-{wins[winner]}"
    seed = {
        "clinched_series": f"{winner} won {stage} to win the series 4-{wins[loser]} over {loser}.",
        "forced_game_7": f"{winner} won {stage} to even the series 3-3 and force Game 7.",
        "tied_series": f"{winner} won {stage} to tie the series {wins[winner]}-{wins[loser]}.",
    }.get(outcome, f"{winner} won {stage}; the series stands {series_text}.")
    if outcome == "clinched_series" and position and position[0] == 4:
        seed = f"{winner} won {stage} to clinch the NBA championship, 4-{wins[loser]} over {loser}."
    metrics = {
        "season_type": game["season_type"], "round": position[0] if position else None, "round_name": round_name,
        "game_in_series": number, "series_before": before, "series_after": wins, "game_winner": winner,
        "outcome": outcome, "elimination_game": max(before.values()) == 3, "series_winner": winner if wins[winner] == 4 else None,
        "games": [{"game_in_series": n, **g} for n, g in zip(numbers, games)],
    }
    caveats = [] if complete else ["Earlier games of this series are missing from stored results; the series record may be incomplete."]
    return metrics, seed, caveats


def team_form(con: StorageConnection, game: dict[str, Any], team: str) -> dict[str, Any]:
    games = result_rows(con, f"SELECT {RESULT_COLUMNS} FROM games WHERE season_id = ? AND season_type = ? "
                             "AND (home_team_abbr = ? OR away_team_abbr = ?) AND game_date <= ? ORDER BY game_date, game_id",
                        [game["season_id"], game["season_type"], team, team, game["game_date"]])
    results = ["W" if g["winner"] == team else "L" for g in games]
    streak = 0
    for result in reversed(results):
        if result != results[-1]:
            break
        streak += 1
    last_10 = results[-10:]
    return {"record": f"{results.count('W')}-{results.count('L')}", "games_counted": len(results),
            "last_10": f"{last_10.count('W')}-{last_10.count('L')}",
            "streak": f"{results[-1]}{streak}" if results else None}


def get_stakes_context(game_id: str, db_path: Path = DEFAULT_DB, persist: bool = False) -> dict[str, Any]:
    """What the game meant: playoff series state, or each team's record and recent form."""
    con = get_storage(db_path).open()
    try:
        row = con.execute(
            "SELECT game_id, season_id, game_date, season_type, home_team_abbr, away_team_abbr, source FROM games WHERE game_id = ?",
            [game_id],
        ).fetchone()
        if row is None:
            return {"summary": {"game_id": game_id, "resolution_status": "not_found"}, "evidence_packets": []}
        game = dict(zip(("game_id", "season_id", "game_date", "season_type", "home_team_abbr", "away_team_abbr", "source"), row))
        if str(game["season_type"]).lower() == "playoffs":
            metrics, seed, caveats = series_context(con, game)
            packet_type = "series_context"
        else:
            teams = (game["away_team_abbr"], game["home_team_abbr"])
            forms = {team: team_form(con, game, team) for team in teams}
            metrics = {"season_type": game["season_type"], "through_date": str(game["game_date"])[:10], "teams": forms}
            seed = "After this game: " + "; ".join(
                f"{team} {form['record']} ({form['last_10']} in last 10, streak {form['streak']})" for team, form in forms.items()
            ) + "."
            caveats = ["Records count stored results for this season; they are complete once the season's results are synced."]
            packet_type = "team_form"
    finally:
        con.close()
    packet = {
        "packet_id": packet_id("stakes", game_id),
        "type": packet_type,
        "claim_seed": seed,
        "metrics": metrics,
        "source": {"provider": "nba_official", "detail": "nba_api:LeagueGameLog results"},
        "evidence_level": "core",
        "confidence": "medium" if caveats and packet_type == "series_context" else "high",
        "caveats": caveats,
    }
    return with_persisted_packets(game_id, {
        "summary": {"game_id": game_id, "type": packet_type},
        "evidence_packets": [packet],
    }, db_path, persist=persist)


def rehydrate_evidence_packet(packet_id_value: str, game_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    """Return a stored packet; a scoring-run packet also returns the plays inside its window."""
    con = get_storage(db_path).open()
    try:
        stored_packet = con.execute(
            """
            SELECT packet_id, packet_type, claim_seed, source_provider, source_detail,
                   evidence_level, confidence, payload_json
            FROM evidence_packets
            WHERE packet_id = ? AND game_id = ?
            """,
            [packet_id_value, game_id],
        ).fetchone()
        stored = None
        if stored_packet:
            cols = [d[0] for d in con.description]
            stored = dict(zip(cols, stored_packet))
            stored["payload"] = decode_storage_json(stored.pop("payload_json"))
        if packet_id_value.startswith("run_"):
            window = (stored or {}).get("payload", {}).get("window") or {}
            parts = packet_id_value.split("_")
            start_event = int(window.get("start_eventnum", parts[-2]))
            end_event = int(window.get("end_eventnum", parts[-1]))
            window = run_window_plays(con, game_id, start_event, end_event)
            plays = window.pop("plays")
            response = {
                "summary": {
                    "packet_id": packet_id_value,
                    "game_id": game_id,
                    "play_count": len(plays),
                    "scoring_play_count": sum(play["scoring"] for play in plays),
                    "source": "play_by_play_events",
                },
                "window_totals": window,
                "plays": plays,
            }
            if stored:
                response["packet"] = stored
            return response
        if stored:
            return {
                "summary": {"packet_id": packet_id_value, "game_id": game_id, "source": "evidence_packets"},
                "packet": stored,
            }
        if packet_id_value.startswith("snapshot_"):
            return {"summary": {"packet_id": packet_id_value, "game_id": game_id}, "snapshot": get_game_snapshot(game_id, db_path)}
        return {
            "summary": {
                "packet_id": packet_id_value,
                "game_id": game_id,
                "resolution_status": "not_found_or_not_yet_persisted",
            }
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tool", choices=["recent-games", "resolve-game", "ensure-cache", "snapshot", "advanced", "players", "runs", "possessions", "lineups", "rehydrate"])
    parser.add_argument("--game-id", default="0042200404")
    parser.add_argument("--query", default="")
    parser.add_argument("--packet-id")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--season")
    parser.add_argument("--season-type", default="Playoffs")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    if args.tool == "recent-games":
        result = find_recent_completed_games(args.season, args.season_type, args.limit, args.timeout)
    elif args.tool == "resolve-game":
        if not args.query:
            raise SystemExit("--query is required for resolve-game")
        result = resolve_game_reference(args.query, args.season, args.season_type, args.limit, args.timeout)
    elif args.tool == "ensure-cache":
        result = ensure_game_cached(args.game_id, args.db, args.season, args.season_type, args.timeout, args.force_refresh)
    elif args.tool == "snapshot":
        result = get_game_snapshot(args.game_id, args.db)
    elif args.tool == "advanced":
        result = get_advanced_game_context(args.game_id, args.db)
    elif args.tool == "players":
        result = get_player_game_context(args.game_id, args.db)
    elif args.tool == "runs":
        result = find_decisive_runs(args.game_id, args.db)
    elif args.tool == "possessions":
        result = get_possession_summary(args.game_id, args.db)
    elif args.tool == "lineups":
        result = get_lineup_stints(args.game_id, db_path=args.db)
    else:
        if not args.packet_id:
            raise SystemExit("--packet-id is required for rehydrate")
        result = rehydrate_evidence_packet(args.packet_id, args.game_id, args.db)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

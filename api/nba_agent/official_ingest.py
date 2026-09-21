#!/usr/bin/env python3
"""On-demand official NBA ingestion helpers."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
from nba_api.stats.endpoints import boxscoreadvancedv3, boxscoretraditionalv3, gamerotation, leaguegamelog, playbyplayv3

from api.nba_agent.db import DEFAULT_DB, create_schema

ROOT = Path(__file__).resolve().parents[2]


def persist_raw_response(
    con: duckdb.DuckDBPyConnection,
    *,
    endpoint: str,
    game_id: str | None,
    request: dict[str, Any],
    response: Any,
) -> str:
    response_id = f"nba_api_{endpoint}_{game_id or 'global'}_{uuid.uuid4().hex}"
    if hasattr(response, "get_dict"):
        payload = response.get_dict()
    else:
        payload = response
    con.execute(
        """
        INSERT INTO raw_responses (
            response_id, provider, endpoint, game_id, request_json, response_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            response_id,
            "nba_api",
            endpoint,
            str(game_id) if game_id else None,
            json.dumps(request, default=str),
            json.dumps(payload, default=str),
        ],
    )
    return response_id


def current_nba_season(today: date | None = None) -> str:
    today = today or date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def minutes_to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if ":" not in text:
        try:
            return float(text)
        except ValueError:
            return None
    minutes, seconds = text.split(":", 1)
    return round(float(minutes) + float(seconds) / 60.0, 2)


def rotation_time_to_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    # GameRotation commonly reports tenths of seconds.
    return numeric / 10.0 if numeric > 7200 else numeric


def elapsed_to_period_clock(elapsed_seconds: float | None) -> tuple[int | None, str | None]:
    if elapsed_seconds is None:
        return None, None
    period = int(elapsed_seconds // 720) + 1
    seconds_into_period = elapsed_seconds - ((period - 1) * 720)
    remaining = max(0, int(round(720 - seconds_into_period)))
    return period, f"{remaining // 60}:{remaining % 60:02d}"


def fetch_official_player_box(game_id: str, timeout: int = 20) -> list[dict[str, Any]]:
    response = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout)
    player_frame = response.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for record in player_frame.to_dict(orient="records"):
        comment = record.get("comment")
        played = not comment
        rows.append(
            {
                "game_id": str(record.get("gameId")),
                "player_id": str(record.get("personId")),
                "player_name": f"{record.get('firstName', '')} {record.get('familyName', '')}".strip(),
                "team_abbr": record.get("teamTricode"),
                "matchup": None,
                "minutes": minutes_to_float(record.get("minutes")) if played else 0.0,
                "fgm": record.get("fieldGoalsMade") if played else 0,
                "fga": record.get("fieldGoalsAttempted") if played else 0,
                "fg_pct": record.get("fieldGoalsPercentage") if played else 0,
                "fg3m": record.get("threePointersMade") if played else 0,
                "fg3a": record.get("threePointersAttempted") if played else 0,
                "fg3_pct": record.get("threePointersPercentage") if played else 0,
                "ftm": record.get("freeThrowsMade") if played else 0,
                "fta": record.get("freeThrowsAttempted") if played else 0,
                "ft_pct": record.get("freeThrowsPercentage") if played else 0,
                "oreb": record.get("reboundsOffensive") if played else 0,
                "dreb": record.get("reboundsDefensive") if played else 0,
                "reb": record.get("reboundsTotal") if played else 0,
                "ast": record.get("assists") if played else 0,
                "stl": record.get("steals") if played else 0,
                "blk": record.get("blocks") if played else 0,
                "tov": record.get("turnovers") if played else 0,
                "pf": record.get("foulsPersonal") if played else 0,
                "pts": record.get("points") if played else 0,
                "plus_minus": record.get("plusMinusPoints") if played else None,
                "source": "nba_api:BoxScoreTraditionalV3",
            }
        )
    return rows


def fetch_recent_completed_games(
    season: str | None = None,
    season_type: str = "Playoffs",
    limit: int = 10,
    timeout: int = 20,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    season = season or current_nba_season()
    response = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        timeout=timeout,
    )
    if db_path is not None:
        con = duckdb.connect(str(db_path))
        create_schema(con)
        persist_raw_response(
            con,
            endpoint="LeagueGameLog",
            game_id=None,
            request={"season": season, "season_type": season_type, "limit": limit, "timeout": timeout},
            response=response,
        )
        con.close()
    frame = response.get_data_frames()[0]
    games: list[dict[str, Any]] = []
    for game_id, game_frame in frame.groupby("GAME_ID", sort=False):
        if len(game_frame) != 2:
            continue
        rows = game_frame.to_dict(orient="records")
        home = next((row for row in rows if "vs." in row["MATCHUP"]), None)
        away = next((row for row in rows if "@" in row["MATCHUP"]), None)
        if not home or not away:
            continue
        games.append(
            {
                "game_id": str(game_id),
                "game_date": str(home["GAME_DATE"]),
                "season": season,
                "season_type": season_type,
                "home_team_abbr": home["TEAM_ABBREVIATION"],
                "home_team_name": home["TEAM_NAME"],
                "home_score": int(home["PTS"]),
                "away_team_abbr": away["TEAM_ABBREVIATION"],
                "away_team_name": away["TEAM_NAME"],
                "away_score": int(away["PTS"]),
                "label": (
                    f"{away['TEAM_ABBREVIATION']} {int(away['PTS'])}, "
                    f"{home['TEAM_ABBREVIATION']} {int(home['PTS'])}"
                ),
            }
        )
    games = sorted(games, key=lambda item: (item["game_date"], item["game_id"]), reverse=True)
    return games[:limit]


def _fetch_league_log_game(
    game_id: str,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
) -> tuple[dict[str, Any], dict[str, Any], Any, str]:
    season = season or current_nba_season()
    response = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star=season_type,
        timeout=timeout,
    )
    frame = response.get_data_frames()[0]
    game_frame = frame[frame["GAME_ID"].astype(str) == str(game_id)]
    if len(game_frame) != 2:
        raise ValueError(f"Could not resolve exactly two team rows for {game_id} in {season} {season_type}")
    rows = game_frame.to_dict(orient="records")
    home = next((row for row in rows if "vs." in row["MATCHUP"]), None)
    away = next((row for row in rows if "@" in row["MATCHUP"]), None)
    if not home or not away:
        raise ValueError(f"Could not determine home/away rows for {game_id}")
    return home, away, response, season


def fetch_official_team_box(game_id: str, timeout: int = 20) -> list[dict[str, Any]]:
    team_frame = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout).get_data_frames()[2]
    return team_frame.to_dict(orient="records")


def fetch_official_advanced_team_box(game_id: str, timeout: int = 20) -> list[dict[str, Any]]:
    team_frame = boxscoreadvancedv3.BoxScoreAdvancedV3(game_id=game_id, timeout=timeout).get_data_frames()[1]
    return team_frame.to_dict(orient="records")


def import_official_advanced_team_box(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    timeout: int = 20,
) -> dict[str, Any]:
    response = boxscoreadvancedv3.BoxScoreAdvancedV3(game_id=game_id, timeout=timeout)
    rows = response.get_data_frames()[1].to_dict(orient="records")
    con = duckdb.connect(str(db_path))
    create_schema(con)
    team_abbr_by_id = {
        str(row[0]): row[1]
        for row in con.execute(
            """
            SELECT home_team_id, home_team_abbr FROM games WHERE game_id = ?
            UNION ALL
            SELECT away_team_id, away_team_abbr FROM games WHERE game_id = ?
            """,
            [game_id, game_id],
        ).fetchall()
    }
    raw_response_id = persist_raw_response(
        con,
        endpoint="BoxScoreAdvancedV3",
        game_id=game_id,
        request={"game_id": game_id, "timeout": timeout},
        response=response,
    )
    con.execute("DELETE FROM box_scores_advanced_team WHERE game_id = ?", [game_id])
    con.executemany(
        """
        INSERT INTO box_scores_advanced_team (
            game_id, team_id, team_abbr, minutes, offensive_rating, defensive_rating,
            net_rating, assist_pct, assist_to_turnover, assist_ratio, oreb_pct,
            dreb_pct, reb_pct, estimated_team_tov_pct, turnover_ratio, efg_pct,
            ts_pct, usage_pct, estimated_usage_pct, pace, possessions, pie, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            [
                str(row["gameId"]),
                str(row["teamId"]),
                row["teamTricode"],
                minutes_to_float(row.get("minutes")),
                row.get("offensiveRating"),
                row.get("defensiveRating"),
                row.get("netRating"),
                row.get("assistPercentage"),
                row.get("assistToTurnover"),
                row.get("assistRatio"),
                row.get("offensiveReboundPercentage"),
                row.get("defensiveReboundPercentage"),
                row.get("reboundPercentage"),
                row.get("estimatedTeamTurnoverPercentage"),
                row.get("turnoverRatio"),
                row.get("effectiveFieldGoalPercentage"),
                row.get("trueShootingPercentage"),
                row.get("usagePercentage"),
                row.get("estimatedUsagePercentage"),
                row.get("pace"),
                row.get("possessions"),
                row.get("PIE"),
                "nba_api:BoxScoreAdvancedV3",
            ]
            for row in rows
        ],
    )
    count = con.execute(
        "SELECT COUNT(*) FROM box_scores_advanced_team WHERE game_id = ?",
        [game_id],
    ).fetchone()[0]
    con.close()
    return {
        "game_id": str(game_id),
        "source": "nba_api:BoxScoreAdvancedV3",
        "raw_response_id": raw_response_id,
        "team_rows_imported": count,
    }


def import_official_game_and_team_box(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
) -> dict[str, Any]:
    home, away, league_response, resolved_season = _fetch_league_log_game(game_id, season, season_type, timeout)
    team_response = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout)
    team_rows = team_response.get_data_frames()[2].to_dict(orient="records")
    by_team_id = {str(row["teamId"]): row for row in team_rows}
    con = duckdb.connect(str(db_path))
    create_schema(con)
    raw_response_id = persist_raw_response(
        con,
        endpoint="BoxScoreTraditionalV3",
        game_id=game_id,
        request={"game_id": game_id, "timeout": timeout, "frame": "team"},
        response=team_response,
    )
    league_raw_response_id = persist_raw_response(
        con,
        endpoint="LeagueGameLog",
        game_id=game_id,
        request={"season": resolved_season, "season_type": season_type, "timeout": timeout},
        response=league_response,
    )
    con.execute("DELETE FROM games WHERE game_id = ?", [game_id])
    con.execute("DELETE FROM box_scores_team WHERE game_id = ?", [game_id])
    con.execute(
        """
        INSERT INTO games (
            game_id, season_id, game_date, season_type,
            home_team_id, home_team_abbr, home_team_name,
            away_team_id, away_team_abbr, away_team_name,
            home_score, away_score, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(game_id),
            str(home["SEASON_ID"]),
            home["GAME_DATE"],
            season_type,
            str(home["TEAM_ID"]),
            home["TEAM_ABBREVIATION"],
            home["TEAM_NAME"],
            str(away["TEAM_ID"]),
            away["TEAM_ABBREVIATION"],
            away["TEAM_NAME"],
            int(home["PTS"]),
            int(away["PTS"]),
            "nba_api:LeagueGameLog",
        ],
    )
    for side, league_row in (("home", home), ("away", away)):
        team = by_team_id[str(league_row["TEAM_ID"])]
        con.execute(
            """
            INSERT INTO box_scores_team
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(game_id),
                side,
                str(team["teamId"]),
                team["teamTricode"],
                team["fieldGoalsMade"],
                team["fieldGoalsAttempted"],
                team["fieldGoalsPercentage"],
                team["threePointersMade"],
                team["threePointersAttempted"],
                team["threePointersPercentage"],
                team["freeThrowsMade"],
                team["freeThrowsAttempted"],
                team["freeThrowsPercentage"],
                team["reboundsOffensive"],
                team["reboundsDefensive"],
                team["reboundsTotal"],
                team["assists"],
                team["steals"],
                team["blocks"],
                team["turnovers"],
                team["foulsPersonal"],
                team["points"],
                team["plusMinusPoints"],
                "nba_api:BoxScoreTraditionalV3",
            ],
        )
    con.close()
    return {
        "game_id": str(game_id),
        "source": "nba_api:LeagueGameLog + BoxScoreTraditionalV3",
        "raw_response_id": raw_response_id,
        "league_raw_response_id": league_raw_response_id,
        "game": {
            "label": f"{away['TEAM_ABBREVIATION']} {int(away['PTS'])}, {home['TEAM_ABBREVIATION']} {int(home['PTS'])}",
            "game_date": str(home["GAME_DATE"]),
            "season_type": season_type,
        },
        "team_rows_imported": 2,
    }


def import_official_player_box(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    timeout: int = 20,
) -> dict[str, Any]:
    response = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout)
    player_frame = response.get_data_frames()[0]
    rows: list[dict[str, Any]] = []
    for record in player_frame.to_dict(orient="records"):
        comment = record.get("comment")
        played = not comment
        rows.append(
            {
                "game_id": str(record.get("gameId")),
                "player_id": str(record.get("personId")),
                "player_name": f"{record.get('firstName', '')} {record.get('familyName', '')}".strip(),
                "team_abbr": record.get("teamTricode"),
                "matchup": None,
                "minutes": minutes_to_float(record.get("minutes")) if played else 0.0,
                "fgm": record.get("fieldGoalsMade") if played else 0,
                "fga": record.get("fieldGoalsAttempted") if played else 0,
                "fg_pct": record.get("fieldGoalsPercentage") if played else 0,
                "fg3m": record.get("threePointersMade") if played else 0,
                "fg3a": record.get("threePointersAttempted") if played else 0,
                "fg3_pct": record.get("threePointersPercentage") if played else 0,
                "ftm": record.get("freeThrowsMade") if played else 0,
                "fta": record.get("freeThrowsAttempted") if played else 0,
                "ft_pct": record.get("freeThrowsPercentage") if played else 0,
                "oreb": record.get("reboundsOffensive") if played else 0,
                "dreb": record.get("reboundsDefensive") if played else 0,
                "reb": record.get("reboundsTotal") if played else 0,
                "ast": record.get("assists") if played else 0,
                "stl": record.get("steals") if played else 0,
                "blk": record.get("blocks") if played else 0,
                "tov": record.get("turnovers") if played else 0,
                "pf": record.get("foulsPersonal") if played else 0,
                "pts": record.get("points") if played else 0,
                "plus_minus": record.get("plusMinusPoints") if played else None,
                "source": "nba_api:BoxScoreTraditionalV3",
            }
        )
    con = duckdb.connect(str(db_path))
    create_schema(con)
    raw_response_id = persist_raw_response(
        con,
        endpoint="BoxScoreTraditionalV3",
        game_id=game_id,
        request={"game_id": game_id, "timeout": timeout, "frame": "player"},
        response=response,
    )
    con.execute("DELETE FROM box_scores_player WHERE game_id = ?", [game_id])
    con.executemany(
        """
        INSERT INTO box_scores_player (
            game_id, player_id, player_name, team_abbr, matchup, minutes,
            fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
            oreb, dreb, reb, ast, stl, blk, tov, pf, pts, plus_minus, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            [
                row["game_id"],
                row["player_id"],
                row["player_name"],
                row["team_abbr"],
                row["matchup"],
                row["minutes"],
                row["fgm"],
                row["fga"],
                row["fg_pct"],
                row["fg3m"],
                row["fg3a"],
                row["fg3_pct"],
                row["ftm"],
                row["fta"],
                row["ft_pct"],
                row["oreb"],
                row["dreb"],
                row["reb"],
                row["ast"],
                row["stl"],
                row["blk"],
                row["tov"],
                row["pf"],
                row["pts"],
                row["plus_minus"],
                row["source"],
            ]
            for row in rows
        ],
    )
    count = con.execute(
        "SELECT COUNT(*) FROM box_scores_player WHERE game_id = ?",
        [game_id],
    ).fetchone()[0]
    top_players = con.execute(
        """
        SELECT player_name, team_abbr, pts, reb, ast, plus_minus
        FROM box_scores_player
        WHERE game_id = ? AND minutes > 0
        ORDER BY pts DESC, plus_minus DESC NULLS LAST
        LIMIT 5
        """,
        [game_id],
    ).fetchall()
    con.close()
    return {
        "game_id": game_id,
        "source": "nba_api:BoxScoreTraditionalV3",
        "raw_response_id": raw_response_id,
        "rows_imported": count,
        "top_players": [
            {
                "player_name": row[0],
                "team_abbr": row[1],
                "pts": row[2],
                "reb": row[3],
                "ast": row[4],
                "plus_minus": row[5],
            }
            for row in top_players
        ],
    }


def clock_to_pctimestring(clock: str | None) -> str | None:
    if not clock or not str(clock).startswith("PT"):
        return clock
    text = str(clock).removeprefix("PT").removesuffix("S")
    minutes = "0"
    seconds = "00.00"
    if "M" in text:
        minutes, text = text.split("M", 1)
    if text:
        seconds = text
    whole_seconds = int(float(seconds))
    return f"{int(minutes)}:{whole_seconds:02d}"


def action_type_to_eventmsgtype(action_type: str | None) -> int | None:
    mapping = {
        "Made Shot": 1,
        "Missed Shot": 2,
        "Free Throw": 3,
        "Rebound": 4,
        "Turnover": 5,
        "Foul": 6,
        "Violation": 7,
        "Substitution": 8,
        "Timeout": 9,
        "Jump Ball": 10,
    }
    return mapping.get(str(action_type)) if action_type is not None else None


def parse_score_values(score_away: Any, score_home: Any) -> tuple[int | None, int | None, str | None]:
    if score_away in (None, "") or score_home in (None, ""):
        return None, None, None
    away = int(score_away)
    home = int(score_home)
    return away, home, f"{away} - {home}"


def import_official_play_by_play(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    timeout: int = 20,
) -> dict[str, Any]:
    response = playbyplayv3.PlayByPlayV3(game_id=game_id, timeout=timeout)
    frame = response.get_data_frames()[0]
    con = duckdb.connect(str(db_path))
    create_schema(con)
    raw_response_id = persist_raw_response(
        con,
        endpoint="PlayByPlayV3",
        game_id=game_id,
        request={"game_id": game_id, "timeout": timeout},
        response=response,
    )
    game = con.execute(
        "SELECT home_team_id, away_team_id FROM games WHERE game_id = ?",
        [game_id],
    ).fetchone()
    home_team_id, away_team_id = game if game else (None, None)
    con.execute("DELETE FROM play_by_play_events WHERE game_id = ?", [game_id])
    rows = []
    for record in frame.to_dict(orient="records"):
        team_id = str(record.get("teamId")) if record.get("teamId") not in (None, 0, "") else None
        score_away, score_home, score = parse_score_values(record.get("scoreAway"), record.get("scoreHome"))
        description = record.get("description")
        home_desc = description if team_id and home_team_id and team_id == str(home_team_id) else None
        away_desc = description if team_id and away_team_id and team_id == str(away_team_id) else None
        neutral_desc = description if not home_desc and not away_desc else None
        rows.append(
            [
                str(record.get("gameId")),
                int(record.get("actionId")),
                action_type_to_eventmsgtype(record.get("actionType")),
                int(record.get("actionNumber")) if record.get("actionNumber") not in (None, "") else None,
                int(record.get("period")),
                clock_to_pctimestring(record.get("clock")),
                home_desc,
                neutral_desc,
                away_desc,
                score,
                score_away,
                score_home,
                None,
                str(record.get("personId")) if record.get("personId") not in (None, 0, "") else None,
                record.get("playerName") or None,
                team_id,
                record.get("teamTricode") or None,
                None,
                None,
                None,
                None,
                "nba_api:PlayByPlayV3",
            ]
        )
    con.executemany(
        """
        INSERT INTO play_by_play_events (
            game_id, eventnum, eventmsgtype, eventmsgactiontype, period,
            pctimestring, homedescription, neutraldescription, visitordescription,
            score, score_away, score_home, scoremargin, player1_id, player1_name,
            player1_team_id, player1_team_abbreviation, player2_id, player2_name,
            player2_team_id, player2_team_abbreviation, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    count = con.execute(
        "SELECT COUNT(*) FROM play_by_play_events WHERE game_id = ?",
        [game_id],
    ).fetchone()[0]
    con.close()
    return {
        "game_id": str(game_id),
        "source": "nba_api:PlayByPlayV3",
        "raw_response_id": raw_response_id,
        "rows_imported": count,
    }


def import_official_game_rotation(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    timeout: int = 20,
) -> dict[str, Any]:
    response = gamerotation.GameRotation(game_id=game_id, timeout=timeout)
    frames = response.get_data_frames()
    con = duckdb.connect(str(db_path))
    create_schema(con)
    team_abbr_by_id = {
        str(row[0]): row[1]
        for row in con.execute(
            """
            SELECT home_team_id, home_team_abbr FROM games WHERE game_id = ?
            UNION ALL
            SELECT away_team_id, away_team_abbr FROM games WHERE game_id = ?
            """,
            [game_id, game_id],
        ).fetchall()
    }
    raw_response_id = persist_raw_response(
        con,
        endpoint="GameRotation",
        game_id=game_id,
        request={"game_id": game_id, "timeout": timeout},
        response=response,
    )
    con.execute("DELETE FROM lineup_stints WHERE game_id = ? AND source = ?", [game_id, "nba_api:GameRotation"])
    rows = []
    for frame in frames:
        for record in frame.to_dict(orient="records"):
            start_elapsed = rotation_time_to_seconds(record.get("IN_TIME_REAL"))
            end_elapsed = rotation_time_to_seconds(record.get("OUT_TIME_REAL"))
            period, start_clock = elapsed_to_period_clock(start_elapsed)
            _, end_clock = elapsed_to_period_clock(end_elapsed)
            player_name = f"{record.get('PLAYER_FIRST', '')} {record.get('PLAYER_LAST', '')}".strip()
            stint_id = f"rotation_{game_id}_{record.get('PERSON_ID')}_{record.get('IN_TIME_REAL')}_{record.get('OUT_TIME_REAL')}"
            rows.append(
                [
                    stint_id,
                    str(record.get("GAME_ID")),
                    team_abbr_by_id.get(str(record.get("TEAM_ID")), record.get("TEAM_NAME")),
                    str(record.get("TEAM_ID")),
                    str(record.get("PERSON_ID")),
                    player_name,
                    period,
                    start_clock,
                    end_clock,
                    None,
                    None,
                    start_elapsed,
                    end_elapsed,
                    round(end_elapsed - start_elapsed, 2) if start_elapsed is not None and end_elapsed is not None else None,
                    record.get("PLAYER_PTS"),
                    record.get("PT_DIFF"),
                    "nba_api:GameRotation",
                    "high",
                    None,
                ]
            )
    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO lineup_stints (
                stint_id, game_id, team_abbr, team_id, player_id, player_name,
                period, start_clock, end_clock, start_eventnum, end_eventnum,
                start_elapsed_seconds, end_elapsed_seconds, duration_seconds,
                player_pts, plus_minus, source, confidence, caveat
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    count = con.execute(
        "SELECT COUNT(*) FROM lineup_stints WHERE game_id = ? AND source = ?",
        [game_id, "nba_api:GameRotation"],
    ).fetchone()[0]
    con.close()
    return {
        "game_id": str(game_id),
        "source": "nba_api:GameRotation",
        "raw_response_id": raw_response_id,
        "rows_imported": count,
    }


def import_official_game_bundle(
    game_id: str,
    db_path: Path = DEFAULT_DB,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
) -> dict[str, Any]:
    game_result = import_official_game_and_team_box(game_id, db_path, season, season_type, timeout)
    advanced_result = import_official_advanced_team_box(game_id, db_path, timeout)
    player_result = import_official_player_box(game_id, db_path, timeout)
    pbp_result = import_official_play_by_play(game_id, db_path, timeout)
    try:
        rotation_result = import_official_game_rotation(game_id, db_path, timeout)
        rotation_warning = None
    except Exception as exc:
        rotation_result = None
        rotation_warning = str(exc)
    return {
        "game_id": str(game_id),
        "source": "nba_api",
        "game": game_result,
        "advanced": advanced_result,
        "players": player_result,
        "play_by_play": pbp_result,
        "rotation": rotation_result,
        "warnings": [rotation_warning] if rotation_warning else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["recent-games", "game-bundle", "game-team-box", "advanced-team-box", "player-box", "play-by-play", "game-rotation"])
    parser.add_argument("--game-id", default="0042200404")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--season")
    parser.add_argument("--season-type", default="Playoffs")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    if args.command == "recent-games":
        result = {"games": fetch_recent_completed_games(args.season, args.season_type, args.limit, args.timeout)}
    elif args.command == "game-bundle":
        result = import_official_game_bundle(args.game_id, args.db, args.season, args.season_type, args.timeout)
    elif args.command == "game-team-box":
        result = import_official_game_and_team_box(args.game_id, args.db, args.season, args.season_type, args.timeout)
    elif args.command == "advanced-team-box":
        result = import_official_advanced_team_box(args.game_id, args.db, args.timeout)
    elif args.command == "player-box":
        result = import_official_player_box(args.game_id, args.db, args.timeout)
    elif args.command == "play-by-play":
        result = import_official_play_by_play(args.game_id, args.db, args.timeout)
    elif args.command == "game-rotation":
        result = import_official_game_rotation(args.game_id, args.db, args.timeout)
    else:
        raise SystemExit(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Import the legacy 2023 fixture from old local files into the DuckDB cache."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from api.nba_agent.db import DEFAULT_DB, create_schema, get_storage
from api.nba_agent.storage import StorageConnection


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = ROOT / "old" / "nba.sqlite"
DEFAULT_PLAYER_LOG = ROOT / "old" / "player_game_log.csv"
DEFAULT_GAME_ID = "0042200404"


GAME_COLUMNS = [
    "season_id",
    "team_id_home",
    "team_abbreviation_home",
    "team_name_home",
    "game_id",
    "game_date",
    "matchup_home",
    "wl_home",
    "min",
    "fgm_home",
    "fga_home",
    "fg_pct_home",
    "fg3m_home",
    "fg3a_home",
    "fg3_pct_home",
    "ftm_home",
    "fta_home",
    "ft_pct_home",
    "oreb_home",
    "dreb_home",
    "reb_home",
    "ast_home",
    "stl_home",
    "blk_home",
    "tov_home",
    "pf_home",
    "pts_home",
    "plus_minus_home",
    "video_available_home",
    "team_id_away",
    "team_abbreviation_away",
    "team_name_away",
    "matchup_away",
    "wl_away",
    "fgm_away",
    "fga_away",
    "fg_pct_away",
    "fg3m_away",
    "fg3a_away",
    "fg3_pct_away",
    "ftm_away",
    "fta_away",
    "ft_pct_away",
    "oreb_away",
    "dreb_away",
    "reb_away",
    "ast_away",
    "stl_away",
    "blk_away",
    "tov_away",
    "pf_away",
    "pts_away",
    "plus_minus_away",
    "video_available_away",
    "season_type",
]

PBP_COLUMNS = [
    "game_id",
    "eventnum",
    "eventmsgtype",
    "eventmsgactiontype",
    "period",
    "wctimestring",
    "pctimestring",
    "homedescription",
    "neutraldescription",
    "visitordescription",
    "score",
    "scoremargin",
    "person1type",
    "player1_id",
    "player1_name",
    "player1_team_id",
    "player1_team_city",
    "player1_team_nickname",
    "player1_team_abbreviation",
    "person2type",
    "player2_id",
    "player2_name",
    "player2_team_id",
    "player2_team_city",
    "player2_team_nickname",
    "player2_team_abbreviation",
    "person3type",
    "player3_id",
    "player3_name",
    "player3_team_id",
    "player3_team_city",
    "player3_team_nickname",
    "player3_team_abbreviation",
    "video_available_flag",
]


def parse_score(score: str | None) -> tuple[int | None, int | None]:
    if not score or " - " not in score:
        return None, None
    away, home = score.split(" - ", 1)
    return int(away), int(home)


def create_legacy_seed_schema(con: StorageConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS seed_player_game_logs AS
        SELECT * FROM read_csv_auto(?, header = true, ignore_errors = true)
        LIMIT 0
        """,
        [str(DEFAULT_PLAYER_LOG)],
    )


def import_game(sqlite_path: Path, con: StorageConnection, game_id: str) -> None:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    game = src.execute("SELECT * FROM game WHERE game_id = ?", [game_id]).fetchone()
    if not game:
        raise SystemExit(f"Game {game_id} not found in {sqlite_path}")

    con.execute("DELETE FROM games WHERE game_id = ?", [game_id])
    con.execute("DELETE FROM box_scores_team WHERE game_id = ?", [game_id])
    con.execute("DELETE FROM box_scores_player WHERE game_id = ?", [game_id])
    con.execute("DELETE FROM play_by_play_events WHERE game_id = ?", [game_id])
    con.execute("DELETE FROM evidence_packets WHERE game_id = ?", [game_id])

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
            game["game_id"],
            game["season_id"],
            game["game_date"],
            game["season_type"],
            game["team_id_home"],
            game["team_abbreviation_home"],
            game["team_name_home"],
            game["team_id_away"],
            game["team_abbreviation_away"],
            game["team_name_away"],
            int(game["pts_home"]),
            int(game["pts_away"]),
            "old/nba.sqlite:game",
        ],
    )

    for side in ("home", "away"):
        con.execute(
            """
            INSERT INTO box_scores_team
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                game_id,
                side,
                game[f"team_id_{side}"],
                game[f"team_abbreviation_{side}"],
                game[f"fgm_{side}"],
                game[f"fga_{side}"],
                game[f"fg_pct_{side}"],
                game[f"fg3m_{side}"],
                game[f"fg3a_{side}"],
                game[f"fg3_pct_{side}"],
                game[f"ftm_{side}"],
                game[f"fta_{side}"],
                game[f"ft_pct_{side}"],
                game[f"oreb_{side}"],
                game[f"dreb_{side}"],
                game[f"reb_{side}"],
                game[f"ast_{side}"],
                game[f"stl_{side}"],
                game[f"blk_{side}"],
                game[f"tov_{side}"],
                game[f"pf_{side}"],
                game[f"pts_{side}"],
                game[f"plus_minus_{side}"],
                "old/nba.sqlite:game",
            ],
        )

    pbp_rows = src.execute(
        "SELECT * FROM play_by_play WHERE game_id = ? ORDER BY period, eventnum",
        [game_id],
    ).fetchall()
    if not pbp_rows:
        raise SystemExit(f"Game {game_id} has no play_by_play rows in {sqlite_path}")

    events = []
    for row in pbp_rows:
        score_away, score_home = parse_score(row["score"])
        events.append(
            [
                row["game_id"],
                row["eventnum"],
                row["eventmsgtype"],
                row["eventmsgactiontype"],
                row["period"],
                row["pctimestring"],
                row["homedescription"],
                row["neutraldescription"],
                row["visitordescription"],
                row["score"],
                score_away,
                score_home,
                row["scoremargin"],
                row["player1_id"],
                row["player1_name"],
                row["player1_team_id"],
                row["player1_team_abbreviation"],
                row["player2_id"],
                row["player2_name"],
                row["player2_team_id"],
                row["player2_team_abbreviation"],
                "old/nba.sqlite:play_by_play",
            ]
        )
    con.executemany(
        """
        INSERT INTO play_by_play_events
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        events,
    )
    src.close()


def import_seed_player_logs(con: StorageConnection, csv_path: Path) -> int:
    con.execute("DELETE FROM seed_player_game_logs")
    con.execute(
        "INSERT INTO seed_player_game_logs SELECT * FROM read_csv_auto(?, header = true, ignore_errors = true)",
        [str(csv_path)],
    )
    return con.execute("SELECT COUNT(*) FROM seed_player_game_logs").fetchone()[0]


def import_player_box_from_seed(con: StorageConnection, game_id: str) -> int:
    con.execute("DELETE FROM box_scores_player WHERE game_id = ?", [game_id])
    con.execute(
        """
        INSERT INTO box_scores_player
        SELECT
            CAST(Game_ID AS TEXT) AS game_id,
            CAST(Player_ID AS TEXT) AS player_id,
            CAST(Player_ID AS TEXT) AS player_name,
            split_part(MATCHUP, ' ', 1) AS team_abbr,
            MATCHUP AS matchup,
            TRY_CAST(MIN AS DOUBLE) AS minutes,
            TRY_CAST(FGM AS DOUBLE) AS fgm,
            TRY_CAST(FGA AS DOUBLE) AS fga,
            TRY_CAST(FG_PCT AS DOUBLE) AS fg_pct,
            TRY_CAST(FG3M AS DOUBLE) AS fg3m,
            TRY_CAST(FG3A AS DOUBLE) AS fg3a,
            TRY_CAST(FG3_PCT AS DOUBLE) AS fg3_pct,
            TRY_CAST(FTM AS DOUBLE) AS ftm,
            TRY_CAST(FTA AS DOUBLE) AS fta,
            TRY_CAST(FT_PCT AS DOUBLE) AS ft_pct,
            TRY_CAST(OREB AS DOUBLE) AS oreb,
            TRY_CAST(DREB AS DOUBLE) AS dreb,
            TRY_CAST(REB AS DOUBLE) AS reb,
            TRY_CAST(AST AS DOUBLE) AS ast,
            TRY_CAST(STL AS DOUBLE) AS stl,
            TRY_CAST(BLK AS DOUBLE) AS blk,
            TRY_CAST(TOV AS DOUBLE) AS tov,
            TRY_CAST(PF AS DOUBLE) AS pf,
            TRY_CAST(PTS AS DOUBLE) AS pts,
            TRY_CAST(PLUS_MINUS AS DOUBLE) AS plus_minus,
            'old/player_game_log.csv' AS source
        FROM seed_player_game_logs
        WHERE CAST(Game_ID AS TEXT) = ?
        """,
        [game_id],
    )
    return con.execute(
        "SELECT COUNT(*) FROM box_scores_player WHERE game_id = ?",
        [game_id],
    ).fetchone()[0]


def write_eval_fixture(game_id: str) -> None:
    fixture_dir = ROOT / "eval" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture = {
        "game_id": game_id,
        "fixture_name": "2023 Finals Game 4, Nuggets at Heat",
        "hard_facts": {
            "date": "2023-06-09",
            "home_team": "MIA",
            "away_team": "DEN",
            "final_score": {"DEN": 108, "MIA": 95},
        },
        "must_mention": [
            {
                "topic": "Denver won on the road to take a 3-1 Finals lead",
                "evidence": "Official game record and final score.",
            },
            {
                "topic": "Aaron Gordon had an outlier scoring game",
                "evidence": "Widely covered recap theme; validate with player box once player box ingestion is added.",
            },
            {
                "topic": "Denver created separation after halftime",
                "evidence": "Play-by-play and quarter scoring should identify the decisive window.",
            },
        ],
        "acceptable_angles": [
            "Denver's secondary scoring changed the game while Jokic remained the stabilizer.",
            "Miami could not sustain enough offense to answer Denver's second-half separation.",
            "The decisive story should combine advanced/team context with a concrete PBP window.",
        ],
        "forbidden_claims": [
            "Miami won the game.",
            "Denver lost the fourth quarter collapse-style.",
            "Use exact official lineup plus-minus unless official rotation or validated lineup data is available.",
        ],
    }
    (fixture_dir / f"{game_id}.json").write_text(json.dumps(fixture, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--player-log", type=Path, default=DEFAULT_PLAYER_LOG)
    parser.add_argument("--game-id", default=DEFAULT_GAME_ID)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = get_storage(args.db).open(read_only=False)
    create_schema(con)
    create_legacy_seed_schema(con)
    import_game(args.sqlite, con, args.game_id)
    player_rows = import_seed_player_logs(con, args.player_log)
    player_box_rows = import_player_box_from_seed(con, args.game_id)
    write_eval_fixture(args.game_id)

    counts = {
        "db": str(args.db),
        "game_id": args.game_id,
        "games": con.execute("SELECT COUNT(*) FROM games").fetchone()[0],
        "play_by_play_events": con.execute("SELECT COUNT(*) FROM play_by_play_events").fetchone()[0],
        "seed_player_game_logs": player_rows,
        "box_scores_player": player_box_rows,
    }
    print(json.dumps(counts, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

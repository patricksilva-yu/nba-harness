"""Atomic persistence of validated NBA live-data bundles through storage adapters."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

from api.nba_agent.storage.base import StorageBackend

SOURCE = "nba_s3:liveData"


@contextmanager
def transaction(storage: StorageBackend):
    con = storage.open(read_only=False)
    # PostgreSQL scopes already start a transaction; DuckDB defaults to autocommit.
    if storage.backend == "duckdb":
        con.execute("BEGIN TRANSACTION")
    try:
        yield con
        if storage.backend == "duckdb":
            con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def capture(con, endpoint, payload, game_id=None):
    con.execute(
        """INSERT INTO raw_responses
           (response_id, provider, endpoint, game_id, request_json, response_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [f"nba_s3_{uuid.uuid4().hex}", "nba_s3", endpoint, game_id,
         json.dumps({"game_id": game_id}), json.dumps(payload)],
    )


def insert_rows(con, table, columns, rows):
    # Table and column names are internal constants, never upstream input.
    if rows:
        con.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            rows,
        )


GAME_COLUMNS = (
    "game_id", "season_id", "game_date", "season_type", "home_team_id", "home_team_abbr",
    "home_team_name", "away_team_id", "away_team_abbr", "away_team_name", "home_score", "away_score", "source",
)


class NBALiveRepository:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def recent_results(self, season, season_type, limit):
        con = self.storage.open()
        try:
            rows = con.execute(
                """SELECT game_id, game_date, season_id, season_type,
                          home_team_id, home_team_abbr, home_team_name,
                          away_team_id, away_team_abbr, away_team_name, home_score, away_score
                   FROM games WHERE season_id LIKE ? AND season_type = ?
                     AND home_score IS NOT NULL AND away_score IS NOT NULL
                   ORDER BY game_date DESC, game_id DESC LIMIT ?""",
                [f"%{season[:4]}", season_type, limit],
            ).fetchall()
            columns = [d[0] for d in con.description]
            games = [dict(zip(columns, row)) for row in rows]
            for game in games:
                game["game_date"] = str(game["game_date"])[:10]
                game["season"] = season
                game["label"] = f"{game['away_team_abbr']} {game['away_score']}, {game['home_team_abbr']} {game['home_score']}"
            return games
        finally:
            con.close()

    def save_results(self, games, payload):
        with transaction(self.storage) as con:
            capture(con, "scheduleLeagueV2", payload)
            for game in games:
                # Never downgrade fully imported official or S3 bundles to results-only.
                con.execute(
                    """INSERT INTO games (game_id, season_id, game_date, season_type,
                           home_team_id, home_team_abbr, home_team_name,
                           away_team_id, away_team_abbr, away_team_name, home_score, away_score, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (game_id) DO UPDATE SET
                           game_date = EXCLUDED.game_date, home_score = EXCLUDED.home_score,
                           away_score = EXCLUDED.away_score
                       WHERE games.source = 'nba_s3:results'""",
                    [game[col] for col in GAME_COLUMNS],
                )

    def save_bundle(self, game, team_rows, player_rows, event_rows, box, pbp):
        with transaction(self.storage) as con:
            # Serialize overlapping imports of the same game in PostgreSQL.
            if self.storage.backend == "postgres":
                con.execute("SELECT pg_advisory_xact_lock(?)", [int(game["game_id"])])
            existing = con.execute("SELECT source FROM games WHERE game_id = ?", [game["game_id"]]).fetchone()
            # Preserve a richer official import rather than replace it with basic live data.
            if existing and existing[0] == "nba_api:LeagueGameLog":
                # An official importer can have stopped after writing just team rows.
                # Preserve only a complete official bundle, not a stranded partial import.
                complete = con.execute(
                    """SELECT
                       (SELECT COUNT(*) FROM box_scores_team WHERE game_id = ?),
                       (SELECT COUNT(DISTINCT team_abbr) FROM box_scores_player WHERE game_id = ?),
                       (SELECT COUNT(*) FROM box_scores_advanced_team WHERE game_id = ?),
                       (SELECT score_home FROM play_by_play_events WHERE game_id = ?
                        ORDER BY period DESC, eventnum DESC LIMIT 1),
                       (SELECT score_away FROM play_by_play_events WHERE game_id = ?
                        ORDER BY period DESC, eventnum DESC LIMIT 1)""",
                    [game["game_id"]] * 5,
                ).fetchone()
                if complete == (2, 2, 2, game["home_score"], game["away_score"]):
                    return False
            capture(con, "liveData/boxscore", box, game["game_id"])
            capture(con, "liveData/playbyplay", pbp, game["game_id"])
            for table in ("box_scores_team", "box_scores_player", "play_by_play_events"):
                con.execute(f"DELETE FROM {table} WHERE game_id = ?", [game["game_id"]])
            con.execute(
                """INSERT INTO games (game_id, season_id, game_date, season_type,
                       home_team_id, home_team_abbr, home_team_name,
                       away_team_id, away_team_abbr, away_team_name, home_score, away_score, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (game_id) DO UPDATE SET
                       season_id = EXCLUDED.season_id, game_date = EXCLUDED.game_date,
                       season_type = EXCLUDED.season_type,
                       home_team_id = EXCLUDED.home_team_id, home_team_abbr = EXCLUDED.home_team_abbr,
                       home_team_name = EXCLUDED.home_team_name,
                       away_team_id = EXCLUDED.away_team_id, away_team_abbr = EXCLUDED.away_team_abbr,
                       away_team_name = EXCLUDED.away_team_name,
                       home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score,
                       source = EXCLUDED.source""",
                [game[col] for col in GAME_COLUMNS],
            )
            insert_rows(con, "box_scores_team", TEAM_COLUMNS, team_rows)
            insert_rows(con, "box_scores_player", PLAYER_COLUMNS, player_rows)
            insert_rows(con, "play_by_play_events", EVENT_COLUMNS, event_rows)
        return True


STAT_COLUMNS = ("fgm", "fga", "fg_pct", "fg3m", "fg3a", "fg3_pct", "ftm", "fta", "ft_pct",
                "oreb", "dreb", "reb", "ast", "stl", "blk", "tov", "pf", "pts", "plus_minus")
TEAM_COLUMNS = ("game_id", "team_side", "team_id", "team_abbr", *STAT_COLUMNS, "source")
PLAYER_COLUMNS = ("game_id", "player_id", "player_name", "team_abbr", "minutes", *STAT_COLUMNS, "source")
EVENT_COLUMNS = ("game_id", "eventnum", "eventmsgtype", "eventmsgactiontype", "period", "pctimestring",
                 "homedescription", "neutraldescription", "visitordescription", "score", "score_away", "score_home",
                 "player1_id", "player1_name", "player1_team_id", "player1_team_abbreviation", "source")

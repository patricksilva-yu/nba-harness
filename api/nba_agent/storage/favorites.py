"""Account-scoped favorite team persistence through the storage boundary."""

from __future__ import annotations

from api.nba_agent.storage.base import StorageBackend


class FavoriteTeamsRepository:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def list(self, user_id: str) -> list[str]:
        connection = self.storage.open()
        try:
            rows = connection.execute(
                "SELECT team_abbr FROM favorite_teams WHERE user_id = ? ORDER BY created_at, team_abbr",
                [user_id],
            ).fetchall()
            return [row[0] for row in rows]
        finally:
            connection.close()

    def add(self, user_id: str, team_abbr: str) -> None:
        # Writes prepare a local DuckDB file; reads stay read-only so parallel requests don't conflict.
        self.storage.initialize()
        connection = self.storage.open(read_only=False)
        try:
            connection.execute(
                "INSERT INTO favorite_teams (user_id, team_abbr) VALUES (?, ?) ON CONFLICT DO NOTHING",
                [user_id, team_abbr],
            )
        finally:
            connection.close()

    def remove(self, user_id: str, team_abbr: str) -> None:
        connection = self.storage.open(read_only=False)
        try:
            connection.execute(
                "DELETE FROM favorite_teams WHERE user_id = ? AND team_abbr = ?",
                [user_id, team_abbr],
            )
        finally:
            connection.close()

    def recent_games(self, user_id: str, per_team: int = 3) -> list[dict]:
        """Each favorite team's latest finals, newest first; `team_abbr` names the followed team."""
        connection = self.storage.open()
        try:
            rows = connection.execute(
                """SELECT team_abbr, game_id, game_date, season_type, away_team_abbr, away_score,
                          home_team_abbr, home_score
                   FROM (SELECT f.team_abbr, g.*, ROW_NUMBER() OVER (
                             PARTITION BY f.team_abbr ORDER BY g.game_date DESC, g.game_id DESC) AS n
                         FROM favorite_teams AS f
                         JOIN games AS g ON f.team_abbr IN (g.away_team_abbr, g.home_team_abbr)
                         WHERE f.user_id = ? AND g.away_score IS NOT NULL AND g.home_score IS NOT NULL) AS ranked
                   WHERE n <= ?
                   ORDER BY game_date DESC, game_id DESC, team_abbr""",
                [user_id, per_team],
            ).fetchall()
            return [{
                "team_abbr": row[0], "game_id": row[1],
                "game_date": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
                "season_type": row[3], "away_team_abbr": row[4], "away_score": row[5],
                "home_team_abbr": row[6], "home_score": row[7],
            } for row in rows]
        finally:
            connection.close()

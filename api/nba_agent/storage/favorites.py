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

    def recent_games(self, user_id: str, limit: int = 12) -> list[dict]:
        connection = self.storage.open()
        try:
            rows = connection.execute(
                """SELECT game_id, game_date, season_type, away_team_abbr, away_score,
                          home_team_abbr, home_score
                   FROM games WHERE away_score IS NOT NULL AND home_score IS NOT NULL
                     AND (away_team_abbr IN (SELECT team_abbr FROM favorite_teams WHERE user_id = ?)
                       OR home_team_abbr IN (SELECT team_abbr FROM favorite_teams WHERE user_id = ?))
                   ORDER BY game_date DESC, game_id DESC LIMIT ?""",
                [user_id, user_id, limit],
            ).fetchall()
            return [{
                "game_id": row[0], "game_date": row[1].isoformat() if hasattr(row[1], "isoformat") else row[1],
                "season_type": row[2], "away_team_abbr": row[3], "away_score": row[4],
                "home_team_abbr": row[5], "home_score": row[6],
            } for row in rows]
        finally:
            connection.close()

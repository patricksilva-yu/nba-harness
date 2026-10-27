"""Read saved NBA game details without ingestion or model calls."""

from datetime import timezone

from api.nba_agent.storage.base import StorageBackend


class GameOverviewRepository:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def get(self, game_id: str) -> dict | None:
        con = self.storage.open()
        try:
            row = con.execute(
                """SELECT game_id, game_date, season_type, away_team_abbr, away_score,
                          home_team_abbr, home_score FROM games WHERE game_id = ?""", [game_id]
            ).fetchone()
            if row is None:
                return None
            game = dict(zip([col[0] for col in con.description], row))
            game["game_date"] = str(game["game_date"])[:10] if game["game_date"] else None
            rows = con.execute(
                """SELECT team_side, team_abbr, fgm, fga, fg_pct, fg3m, fg3a, fg3_pct,
                          ftm, fta, ft_pct, oreb, dreb, reb, ast, stl, blk, tov, pts
                   FROM box_scores_team WHERE game_id = ? ORDER BY team_side""", [game_id]
            ).fetchall()
            teams = [dict(zip([col[0] for col in con.description], r)) for r in rows]
            rows = con.execute(
                """SELECT player_id, player_name, team_abbr, minutes, pts, reb, ast, plus_minus
                   FROM box_scores_player WHERE game_id = ? AND minutes > 0
                   ORDER BY pts DESC, reb DESC, ast DESC, player_id LIMIT 10""", [game_id]
            ).fetchall()
            players = [dict(zip([col[0] for col in con.description], r)) for r in rows]
            updated = con.execute(
                "SELECT MAX(fetched_at) FROM raw_responses WHERE game_id = ?", [game_id]
            ).fetchone()[0]
            if updated and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            return {"game": game, "teams": teams, "players": players,
                    "stats_available": len(teams) == 2 and bool(players),
                    "stats_updated_at": updated.isoformat() if updated else None}
        finally:
            con.close()

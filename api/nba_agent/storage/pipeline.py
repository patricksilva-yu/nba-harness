"""Per-game state for the post-game pipeline, through the storage boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.nba_agent.storage.base import StorageBackend


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GamePipelineRepository:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def _read(self, query: str, parameters: list) -> list[tuple]:
        connection = self.storage.open()
        try:
            return connection.execute(query, parameters).fetchall()
        finally:
            connection.close()

    def _write(self, query: str, parameters: list) -> None:
        connection = self.storage.open(read_only=False)
        try:
            connection.execute(query, parameters)
        finally:
            connection.close()

    def followed_finals(self, dates: list[str]) -> list[str]:
        """Finals on these dates involving a team at least one user follows."""
        placeholders = ", ".join("?" for _ in dates)
        rows = self._read(
            f"""SELECT game_id FROM games
                WHERE CAST(game_date AS DATE) IN ({placeholders})
                  AND home_score IS NOT NULL AND away_score IS NOT NULL
                  AND (home_team_abbr IN (SELECT team_abbr FROM favorite_teams)
                    OR away_team_abbr IN (SELECT team_abbr FROM favorite_teams))
                ORDER BY game_id""",
            dates,
        )
        return [row[0] for row in rows]

    def enqueue(self, game_ids: list[str]) -> None:
        # Retry times always come from this process's clock, never the database's, so
        # `due()` compares like with like even when the two clocks drift apart.
        for game_id in game_ids:
            self._write("INSERT INTO game_pipeline (game_id, next_attempt_at) VALUES (?, ?) ON CONFLICT (game_id) DO NOTHING",
                        [game_id, utc_now()])

    def due(self, limit: int) -> list[dict]:
        """Unfinished games whose retry time has come, oldest final first."""
        rows = self._read(
            """SELECT p.game_id, p.status, p.attempts, g.season_type
               FROM game_pipeline AS p JOIN games AS g ON g.game_id = p.game_id
               WHERE p.status IN ('pending', 'loaded') AND p.next_attempt_at <= ?
               ORDER BY p.created_at, p.game_id LIMIT ?""",
            [utc_now(), limit],
        )
        return [{"game_id": r[0], "status": r[1], "attempts": r[2], "season_type": r[3]} for r in rows]

    def get(self, game_id: str) -> dict | None:
        rows = self._read(
            """SELECT status, attempts, last_error, breakdown_run_id, created_at, loaded_at, analyzed_at
               FROM game_pipeline WHERE game_id = ?""",
            [game_id],
        )
        if not rows:
            return None
        keys = ("status", "attempts", "last_error", "breakdown_run_id", "created_at", "loaded_at", "analyzed_at")
        return dict(zip(keys, rows[0]))

    def breakdown_run_id(self, game_id: str) -> str | None:
        rows = self._read("SELECT breakdown_run_id FROM game_pipeline WHERE game_id = ?", [game_id])
        return rows[0][0] if rows else None

    def is_breakdown(self, run_id: str) -> bool:
        return bool(self._read("SELECT 1 FROM game_pipeline WHERE breakdown_run_id = ?", [run_id]))

    def mark_loaded(self, game_id: str) -> None:
        self._write(
            """UPDATE game_pipeline SET status = 'loaded', attempts = 0, last_error = NULL, loaded_at = ?
               WHERE game_id = ? AND status = 'pending'""",
            [utc_now(), game_id],
        )

    def mark_analyzed(self, game_id: str, run_id: str) -> None:
        self._write(
            """UPDATE game_pipeline SET status = 'analyzed', last_error = NULL, breakdown_run_id = ?, analyzed_at = ?
               WHERE game_id = ? AND status = 'loaded'""",
            [run_id, utc_now(), game_id],
        )

    def retry_later(self, game_id: str, error: str, delay: timedelta, max_attempts: int) -> None:
        """Count a failed attempt; the last allowed one marks the game failed."""
        self._write(
            """UPDATE game_pipeline
               SET attempts = attempts + 1, last_error = ?, next_attempt_at = ?,
                   status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE status END
               WHERE game_id = ? AND status IN ('pending', 'loaded')""",
            [error, utc_now() + delay, max_attempts, game_id],
        )

    def missing_stats(self, game_id: str) -> str | None:
        """Why the stored stats don't yet match the final, or None when they do."""
        rows = self._read(
            """SELECT g.home_team_abbr, g.away_team_abbr, g.home_score, g.away_score,
                      (SELECT pts FROM box_scores_team WHERE game_id = g.game_id AND team_abbr = g.home_team_abbr),
                      (SELECT pts FROM box_scores_team WHERE game_id = g.game_id AND team_abbr = g.away_team_abbr),
                      (SELECT COUNT(DISTINCT team_abbr) FROM box_scores_player WHERE game_id = g.game_id),
                      (SELECT COUNT(*) FROM box_scores_advanced_team WHERE game_id = g.game_id)
               FROM games AS g WHERE g.game_id = ?""",
            [game_id],
        )
        if not rows:
            return "game not stored"
        home, away, home_score, away_score, home_pts, away_pts, player_teams, advanced = rows[0]
        if home_pts is None or away_pts is None:
            return "team box score missing"
        if (int(home_pts), int(away_pts)) != (home_score, away_score):
            return f"team box score {away} {int(away_pts)}-{home} {int(home_pts)} differs from the final"
        if player_teams < 2:
            return "player box score missing"
        if advanced < 2:
            return "advanced box score missing"
        last = self._read(
            """SELECT score_home, score_away FROM play_by_play_events
               WHERE game_id = ? AND score_home IS NOT NULL AND score_away IS NOT NULL
               ORDER BY period DESC, eventnum DESC LIMIT 1""",
            [game_id],
        )
        if not last:
            return "play-by-play missing"
        if (last[0][0], last[0][1]) != (home_score, away_score):
            return "play-by-play does not reach the final score"
        return None

"""Application-facing NBA domain service.

The web API, Responses API function tools, and MCP adapter all call this
module. Transport concerns belong at the edges; NBA data and evidence rules
live here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from api.nba_agent.agent import resolve_or_use_game_id, season_type_for_ingest
from api.nba_agent.tools import (
    DEFAULT_DB,
    ensure_game_cached,
    find_decisive_runs,
    get_advanced_game_context,
    get_game_snapshot,
    get_lineup_stints,
    get_player_game_context,
    get_possession_summary,
    rehydrate_evidence_packet,
)


ANALYSIS_SECTIONS = {"snapshot", "advanced", "runs", "possessions", "players", "lineups"}


class NBAService:
    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self.db_path = db_path

    def resolve_game(
        self,
        query: str,
        game_id: str | None = None,
        season: str | None = None,
        season_type: str = "Auto",
        timeout: int = 20,
    ) -> dict[str, Any]:
        return resolve_or_use_game_id(query, game_id, season, season_type, timeout)

    def ensure_game_data(
        self,
        game_id: str,
        season: str | None = None,
        season_type: str = "Playoffs",
        timeout: int = 20,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return ensure_game_cached(
            game_id,
            self.db_path,
            season=season,
            season_type=season_type,
            timeout=timeout,
            force_refresh=force_refresh,
        )

    def prepare_game(
        self,
        question: str,
        game_id: str | None = None,
        season: str | None = None,
        season_type: str = "Auto",
        timeout: int = 20,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        resolution = self.resolve_game(question, game_id, season, season_type, timeout)
        resolved_id = resolution.get("summary", {}).get("game_id")
        if not resolved_id:
            return resolution, None
        cache = self.ensure_game_data(
            resolved_id,
            season,
            season_type_for_ingest(resolution, season_type),
            timeout,
        )
        snapshot = get_game_snapshot(resolved_id, self.db_path, persist=False)
        resolution["summary"] = {
            **resolution["summary"],
            "label": resolution["summary"].get("label") or snapshot.get("summary", {}).get("label"),
            "game_date": resolution["summary"].get("game_date") or snapshot.get("summary", {}).get("date"),
        }
        return resolution, cache

    def get_analysis_context(
        self,
        game_id: str,
        sections: Iterable[str] | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(sections or ANALYSIS_SECTIONS))
        unknown = sorted(set(requested) - ANALYSIS_SECTIONS)
        if unknown:
            raise ValueError(f"Unknown analysis sections: {', '.join(unknown)}")
        loaders = {
            "snapshot": lambda: get_game_snapshot(game_id, self.db_path, persist=persist),
            "advanced": lambda: get_advanced_game_context(game_id, self.db_path, persist=persist),
            "runs": lambda: find_decisive_runs(game_id, self.db_path, persist=persist),
            "possessions": lambda: get_possession_summary(game_id, self.db_path, persist=persist),
            "players": lambda: get_player_game_context(game_id, self.db_path, persist=persist),
            "lineups": lambda: get_lineup_stints(game_id, db_path=self.db_path, persist=persist),
        }
        context = {name: loaders[name]() for name in requested}
        packets = [packet for response in context.values() for packet in response.get("evidence_packets", [])]
        return {
            "summary": {"game_id": game_id, "sections": requested, "packet_count": len(packets)},
            "context": context,
            "evidence_packets": packets,
        }

    def get_evidence_detail(self, packet_id: str, game_id: str) -> dict[str, Any]:
        return rehydrate_evidence_packet(packet_id, game_id, self.db_path)


def service(db_path: Path = DEFAULT_DB) -> NBAService:
    return NBAService(db_path)


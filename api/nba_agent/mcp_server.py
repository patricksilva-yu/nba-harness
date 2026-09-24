#!/usr/bin/env python3
"""MCP wrapper for the NBA analyst tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from api.nba_agent.service import NBAService
from api.nba_agent.db import get_storage
from api.nba_agent.storage.repositories import EvidenceRepository


mcp = FastMCP("nba-analyst")
domain = NBAService(Path(os.environ["NBA_MCP_DB_PATH"])) if os.getenv("NBA_MCP_DB_PATH") else NBAService()


@mcp.tool()
def resolve_game(query: str, season_type: str = "Auto", game_id: str | None = None, season: str | None = None) -> dict:
    """Identify a completed NBA game from a question or game ID.
    Use when the game has not yet been resolved."""
    return domain.resolve_game(query, game_id=game_id, season=season, season_type=season_type)


@mcp.tool()
def ensure_game_data(game_id: str, season_type: str = "Playoffs", season: str | None = None) -> dict:
    """Check cached game data and fetch missing official NBA data.
    Use after resolving a game, before requesting analysis evidence."""
    return domain.ensure_game_data(game_id, season=season, season_type=season_type)


Section = Literal["stakes", "snapshot", "periods", "runs", "players", "advanced", "possessions", "lineups"]

SECTIONS_HELP = """Request only the sections the question needs. Each returns evidence packets:
- stakes: what the game meant. Playoffs: round, game number, series record before and after, and whether it
  clinched, forced a Game 7 or changed the series lead. Regular season: each team's record, last 10 and streak.
- snapshot: final score and both teams' traditional box-score totals, including shooting and assists.
- periods: points per quarter/overtime, score and leader at each break, each team's largest lead
  with its clock time, lead changes and ties. Start here for leads, comebacks and "which quarter".
- runs: the top three scoring stretches, each with start/end clock, start/end score and margin change.
  Summaries only; get_evidence_detail on a run lists its plays and per-player points.
- players: box-score lines (minutes, points, rebounds, assists, shooting, plus/minus) for leading players.
- advanced: team offensive/defensive/net rating, effective and true shooting, turnover and rebound rates, pace.
- possessions: whole-game counts of shots, turnovers and free-throw events. Not per quarter.
- lineups: rotation stint counts inferred from substitutions; low confidence, no validated five-man units.
For what happened in a specific stretch of time, use get_game_window instead."""


@mcp.tool()
def get_game_analysis_context(
    game_id: str,
    sections: Annotated[list[Section], Field(min_length=1, description=SECTIONS_HELP)],
) -> dict:
    """Return summary evidence for selected sections of a cached game.
    Use for the final score, game flow, player performance, or team statistics."""
    result = domain.get_analysis_context(game_id, sections=sections, persist=False)
    EvidenceRepository(get_storage(domain.db_path)).save_many(game_id, result["evidence_packets"])
    return result


Clock = Annotated[str, Field(pattern=r"^\d{1,2}:\d{2}$", description="Game clock remaining in the period, e.g. 8:51.")]


@mcp.tool()
def get_game_window(
    game_id: str,
    period: Annotated[int, Field(ge=1, le=10, description="Period where the window starts: 1-4, 5 for OT, 6 for 2OT.")],
    from_clock: Annotated[str | None, Field(pattern=r"^\d{1,2}:\d{2}$", description="Start clock; omit for the start of the period.")] = None,
    to_clock: Clock = "0:00",
    end_period: Annotated[int | None, Field(ge=1, le=10, description="Period where the window ends; omit for the same period.")] = None,
) -> dict:
    """Return plays, score changes, and team and player statistics for a time window in a cached game.
    Use to examine a quarter, scoring stretch, or late-game sequence. A reversed or invalid window returns
    summary.resolution_status "invalid_window" and no packets; an empty window returns a low-confidence packet."""
    result = domain.get_game_window(game_id, period, from_clock, to_clock, end_period)
    EvidenceRepository(get_storage(domain.db_path)).save_many(game_id, result["evidence_packets"])
    return result


@mcp.tool()
def get_evidence_detail(packet_id: str, game_id: str) -> dict:
    """Return supporting detail for a previously retrieved evidence packet, including plays and player scoring for runs.
    Use when a packet's summary needs closer inspection."""
    return domain.get_evidence_detail(packet_id, game_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

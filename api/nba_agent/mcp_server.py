#!/usr/bin/env python3
"""MCP wrapper for the NBA analyst tools."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from api.nba_agent.agent import run_agent
from api.nba_agent.analysis import run_analysis
from api.nba_agent.official_ingest import import_official_player_box
from api.nba_agent.service import NBAService
from api.nba_agent.db import get_storage
from api.nba_agent.storage.repositories import EvidenceRepository
from api.nba_agent.tools import (
    ensure_game_cached,
    find_decisive_runs,
    find_recent_completed_games,
    get_advanced_game_context,
    get_box_score,
    get_game_snapshot,
    get_lineup_stints,
    get_player_game_context,
    get_possession_summary,
    rehydrate_evidence_packet,
    resolve_game_reference,
)


mcp = FastMCP("nba-analyst")
domain = NBAService(Path(os.environ["NBA_MCP_DB_PATH"])) if os.getenv("NBA_MCP_DB_PATH") else NBAService()


@mcp.tool()
def resolve_game(query: str, season_type: str = "Auto", game_id: str | None = None, season: str | None = None) -> dict:
    """Resolve a natural-language completed NBA game reference. Read-only and safe to retry."""
    return domain.resolve_game(query, game_id=game_id, season=season, season_type=season_type)


@mcp.tool()
def ensure_game_data(game_id: str, season_type: str = "Playoffs", season: str | None = None) -> dict:
    """Ensure official data for a game is cached. May use the network and is safe to retry."""
    return domain.ensure_game_data(game_id, season=season, season_type=season_type)


Section = Literal["snapshot", "periods", "runs", "players", "advanced", "possessions", "lineups"]

SECTIONS_HELP = """Request only the sections the question needs. Each returns evidence packets:
- snapshot: final score.
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
    """Return evidence packets for chosen sections of one cached game. Overview data: use it to find
    where the game turned, then get_game_window for what happened in that stretch."""
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
    """What happened in one stretch of game time, as a single evidence packet: score before and after,
    points per team, team shooting and turnovers, per-player points and shooting, and the plays.
    Use it for questions like "last five minutes", "start of the third" or a run's window."""
    result = domain.get_game_window(game_id, period, from_clock, to_clock, end_period)
    EvidenceRepository(get_storage(domain.db_path)).save_many(game_id, result["evidence_packets"])
    return result


@mcp.tool()
def get_evidence_detail(packet_id: str, game_id: str) -> dict:
    """Rehydrate one evidence packet into its supporting detail. For a scoring-run packet this
    includes every described play in the run and per-player points and shooting for the run."""
    return domain.get_evidence_detail(packet_id, game_id)


@mcp.tool()
def games_find_recent_completed_games(
    season: str | None = None,
    season_type: str = "Playoffs",
    limit: int = 10,
    timeout: int = 20,
) -> dict:
    """Return recent completed NBA games from the official NBA LeagueGameLog endpoint."""
    return find_recent_completed_games(season=season, season_type=season_type, limit=limit, timeout=timeout)


@mcp.tool()
def games_resolve_game_reference(
    query: str,
    season: str | None = None,
    season_type: str = "Auto",
    limit: int = 20,
    timeout: int = 20,
) -> dict:
    """Resolves a natural-language game reference into a specific NBA game ID and game summary across NBA season types. Use this tool when the user names teams, dates, or a recent matchup instead of providing an exact game ID."""
    return resolve_game_reference(query=query, season=season, season_type=season_type, limit=limit, timeout=timeout)


@mcp.tool()
def games_ensure_game_cached(
    game_id: str,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
    force_refresh: bool = False,
) -> dict:
    """Checks whether a game is cached locally and fetches official NBA box-score, advanced, player, and play-by-play data when needed. Use this tool when a resolved game must be available in DuckDB before asking for snapshots, advanced stats, player context, or play-by-play context."""
    return ensure_game_cached(
        game_id=game_id,
        season=season,
        season_type=season_type,
        timeout=timeout,
        force_refresh=force_refresh,
    )


@mcp.tool()
def game_context_get_game_snapshot(game_id: str = "0042200404") -> dict:
    """Returns the core game snapshot, final score, team identities, and compact traditional team box-score context for one game. Use this tool when you need the baseline facts of the game before explaining what happened or comparing teams."""
    return get_game_snapshot(game_id)


@mcp.tool()
def game_context_get_box_score(game_id: str = "0042200404", level: str = "team", detail: bool = False) -> dict:
    """Returns normalized team or player box-score rows. Summary mode limits player rows; detail mode returns all cached rows."""
    return get_box_score(game_id=game_id, level=level, detail=detail)


@mcp.tool()
def advanced_stats_get_advanced_game_context(game_id: str = "0042200404") -> dict:
    """Returns team-level advanced stat context such as ratings, pace, true shooting, turnover rate, rebound rate, and usage-style efficiency signals for one game. Use this tool when the user asks why a team won or lost, especially in close games where possession quality and efficiency matter."""
    return get_advanced_game_context(game_id)


@mcp.tool()
def player_context_get_player_game_context(game_id: str = "0042200404") -> dict:
    """Returns player-level box-score context for one game, including key contributors and individual production. Use this tool when the user asks about players, stars, bench impact, matchup responsibility, or which individual performances drove the result."""
    return get_player_game_context(game_id)


@mcp.tool()
def official_ingest_player_box_score(game_id: str = "0042200404", timeout: int = 20) -> dict:
    """Fetch official NBA BoxScoreTraditionalV3 player rows and cache them in DuckDB."""
    return import_official_player_box(game_id=game_id, timeout=timeout)


@mcp.tool()
def play_by_play_find_decisive_runs(game_id: str = "0042200404") -> dict:
    """Finds candidate decisive scoring runs and game-swing windows from local play-by-play events for one game. Use this tool when the user asks when the game turned, what stretch mattered most, or how momentum changed."""
    return find_decisive_runs(game_id)


@mcp.tool()
def play_by_play_get_possession_summary(game_id: str = "0042200404") -> dict:
    """Returns a compact, approximate possession-segment summary from play-by-play event counts for one game. Use this tool when the user asks about possession flow, turnovers, free throws, shot volume, or late-game execution context without needing full play-by-play rows."""
    return get_possession_summary(game_id)


@mcp.tool()
def lineups_get_lineup_stints(game_id: str = "0042200404", team: str | None = None, period: int | None = None) -> dict:
    """Returns official GameRotation player stints when cached, or substitution-derived inferred rotation events as a fallback."""
    return get_lineup_stints(game_id=game_id, team=team, period=period)


@mcp.tool()
def evidence_rehydrate_evidence_packet(packet_id: str, game_id: str = "0042200404") -> dict:
    """Rehydrates a prior evidence packet into its stored payload or underlying play-by-play rows. Use this tool when you need to inspect or cite the detailed evidence behind a packet ID returned by another tool."""
    return rehydrate_evidence_packet(packet_id, game_id)


@mcp.tool()
def analyst_answer_question(
    question: str,
    game_id: str | None = None,
    season: str | None = None,
    season_type: str = "Playoffs",
    timeout: int = 20,
    max_evidence: int = 4,
    persist: bool = False,
) -> dict:
    """Resolve a user question, route to the needed evidence tools, and return an analyst answer."""
    return run_agent(
        question=question,
        game_id=game_id,
        season=season,
        season_type=season_type,
        timeout=timeout,
        max_evidence=max_evidence,
        persist=persist,
    )


@mcp.tool()
def analyst_run_game_analysis(game_id: str = "0042200404") -> dict:
    """Run the deterministic analyst loop for any cached game and return memo markdown plus packets."""
    return run_analysis(game_id)


@mcp.tool()
def analyst_run_fixture_loop(game_id: str = "0042200404") -> dict:
    """Backward-compatible alias for analyst_run_game_analysis."""
    return run_analysis(game_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

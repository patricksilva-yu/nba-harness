#!/usr/bin/env python3
"""DuckDB schema utilities for the NBA analyst cache."""

from __future__ import annotations

import os
from pathlib import Path

from api.nba_agent.storage import DuckDBStorage, StorageBackend, StorageConnection


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "nba_agent.duckdb"


def storage_config() -> dict[str, str | None]:
    """Describe the explicit local/deployed storage contract.

    DuckDB is the supported local backend. A deployed multi-user service must
    provide DATABASE_URL and use the PostgreSQL migration before switching the
    backend flag; silently sharing a DuckDB file is intentionally disallowed.
    """
    backend = os.getenv("NBA_STORAGE_BACKEND", "duckdb").lower()
    database_url = os.getenv("DATABASE_URL")
    if backend not in {"duckdb", "postgres"}:
        raise RuntimeError(f"Unsupported NBA_STORAGE_BACKEND: {backend}")
    if backend == "postgres" and not database_url:
        raise RuntimeError("DATABASE_URL is required when NBA_STORAGE_BACKEND=postgres")
    return {"backend": backend, "database_url": database_url, "local_path": str(DEFAULT_DB)}


def get_storage(db_path: Path = DEFAULT_DB) -> StorageBackend:
    """Return the configured storage adapter for a local application instance.

    PostgreSQL is intentionally rejected until Phase 4 supplies its adapter;
    accepting the setting while silently opening DuckDB would be unsafe.
    """
    backend = storage_config()["backend"]
    if backend == "duckdb":
        return DuckDBStorage(db_path)
    raise RuntimeError("PostgreSQL storage is not implemented yet; complete Phase 4 before setting NBA_STORAGE_BACKEND=postgres")


def connect(db_path: Path = DEFAULT_DB, read_only: bool = True) -> StorageConnection:
    """Compatibility helper for tests and legacy scripts.

    New application code must depend on :func:`get_storage` instead.
    """
    return get_storage(db_path).open(read_only=read_only)


def create_schema(con: StorageConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS raw_responses (
            response_id TEXT PRIMARY KEY,
            provider TEXT,
            endpoint TEXT,
            game_id TEXT,
            request_json TEXT,
            response_json TEXT,
            fetched_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS games (
            game_id TEXT PRIMARY KEY,
            season_id TEXT,
            game_date TIMESTAMP,
            season_type TEXT,
            home_team_id TEXT,
            home_team_abbr TEXT,
            home_team_name TEXT,
            away_team_id TEXT,
            away_team_abbr TEXT,
            away_team_name TEXT,
            home_score INTEGER,
            away_score INTEGER,
            source TEXT,
            imported_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS box_scores_team (
            game_id TEXT,
            team_side TEXT,
            team_id TEXT,
            team_abbr TEXT,
            fgm DOUBLE,
            fga DOUBLE,
            fg_pct DOUBLE,
            fg3m DOUBLE,
            fg3a DOUBLE,
            fg3_pct DOUBLE,
            ftm DOUBLE,
            fta DOUBLE,
            ft_pct DOUBLE,
            oreb DOUBLE,
            dreb DOUBLE,
            reb DOUBLE,
            ast DOUBLE,
            stl DOUBLE,
            blk DOUBLE,
            tov DOUBLE,
            pf DOUBLE,
            pts DOUBLE,
            plus_minus DOUBLE,
            source TEXT,
            PRIMARY KEY (game_id, team_side)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS box_scores_player (
            game_id TEXT,
            player_id TEXT,
            player_name TEXT,
            team_abbr TEXT,
            matchup TEXT,
            minutes DOUBLE,
            fgm DOUBLE,
            fga DOUBLE,
            fg_pct DOUBLE,
            fg3m DOUBLE,
            fg3a DOUBLE,
            fg3_pct DOUBLE,
            ftm DOUBLE,
            fta DOUBLE,
            ft_pct DOUBLE,
            oreb DOUBLE,
            dreb DOUBLE,
            reb DOUBLE,
            ast DOUBLE,
            stl DOUBLE,
            blk DOUBLE,
            tov DOUBLE,
            pf DOUBLE,
            pts DOUBLE,
            plus_minus DOUBLE,
            source TEXT,
            PRIMARY KEY (game_id, player_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS box_scores_advanced_team (
            game_id TEXT,
            team_id TEXT,
            team_abbr TEXT,
            minutes DOUBLE,
            offensive_rating DOUBLE,
            defensive_rating DOUBLE,
            net_rating DOUBLE,
            assist_pct DOUBLE,
            assist_to_turnover DOUBLE,
            assist_ratio DOUBLE,
            oreb_pct DOUBLE,
            dreb_pct DOUBLE,
            reb_pct DOUBLE,
            estimated_team_tov_pct DOUBLE,
            turnover_ratio DOUBLE,
            efg_pct DOUBLE,
            ts_pct DOUBLE,
            usage_pct DOUBLE,
            estimated_usage_pct DOUBLE,
            pace DOUBLE,
            possessions DOUBLE,
            pie DOUBLE,
            source TEXT,
            PRIMARY KEY (game_id, team_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS play_by_play_events (
            game_id TEXT,
            eventnum INTEGER,
            eventmsgtype INTEGER,
            eventmsgactiontype INTEGER,
            period INTEGER,
            pctimestring TEXT,
            homedescription TEXT,
            neutraldescription TEXT,
            visitordescription TEXT,
            score TEXT,
            score_away INTEGER,
            score_home INTEGER,
            scoremargin TEXT,
            player1_id TEXT,
            player1_name TEXT,
            player1_team_id TEXT,
            player1_team_abbreviation TEXT,
            player2_id TEXT,
            player2_name TEXT,
            player2_team_id TEXT,
            player2_team_abbreviation TEXT,
            source TEXT,
            PRIMARY KEY (game_id, eventnum)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS lineup_stints (
            stint_id TEXT PRIMARY KEY,
            game_id TEXT,
            team_abbr TEXT,
            team_id TEXT,
            player_id TEXT,
            player_name TEXT,
            period INTEGER,
            start_clock TEXT,
            end_clock TEXT,
            start_eventnum INTEGER,
            end_eventnum INTEGER,
            start_elapsed_seconds DOUBLE,
            end_elapsed_seconds DOUBLE,
            duration_seconds DOUBLE,
            player_pts DOUBLE,
            plus_minus DOUBLE,
            source TEXT,
            confidence TEXT,
            caveat TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_packets (
            packet_id TEXT PRIMARY KEY,
            game_id TEXT,
            packet_type TEXT,
            claim_seed TEXT,
            source_provider TEXT,
            source_detail TEXT,
            evidence_level TEXT,
            confidence TEXT,
            payload_json TEXT,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            run_id TEXT PRIMARY KEY,
            game_id TEXT,
            user_question TEXT,
            memo_markdown TEXT,
            packet_ids_json TEXT,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            job_id TEXT PRIMARY KEY,
            game_id TEXT,
            status TEXT,
            error TEXT,
            result_json TEXT,
            created_at TIMESTAMP DEFAULT current_timestamp,
            updated_at TIMESTAMP DEFAULT current_timestamp
        )
        """
    )


def initialize_database(db_path: Path = DEFAULT_DB) -> None:
    get_storage(db_path).initialize()

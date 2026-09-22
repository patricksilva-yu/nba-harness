"""Small local ingestion job runner with explicit persisted states."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from api.nba_agent.db import DEFAULT_DB, get_storage
from api.nba_agent.service import NBAService
from api.nba_agent.storage.repositories import IngestionJobRepository

VALID_JOB_STATES = {"queued", "fetching", "ready", "partial", "failed"}


def jobs(db_path: Path = DEFAULT_DB) -> IngestionJobRepository:
    return IngestionJobRepository(get_storage(db_path))


def create_ingestion_job(game_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    return jobs(db_path).create(game_id)


def update_ingestion_job(job_id: str, status: str, *, result: dict[str, Any] | None = None, error: str | None = None, db_path: Path = DEFAULT_DB) -> None:
    if status not in VALID_JOB_STATES:
        raise ValueError(f"Unknown ingestion job status: {status}")
    jobs(db_path).update(job_id, status, result=result, error=error)


def run_ingestion_job(job_id: str, game_id: str, season: str | None = None, season_type: str = "Playoffs", force_refresh: bool = False, db_path: Path = DEFAULT_DB) -> None:
    update_ingestion_job(job_id, "fetching", db_path=db_path)
    try:
        result = NBAService(db_path).ensure_game_data(game_id, season=season, season_type=season_type, force_refresh=force_refresh)
        update_ingestion_job(job_id, "partial" if result.get("warnings") else "ready", result=result, db_path=db_path)
    except Exception as exc:
        update_ingestion_job(job_id, "failed", error=str(exc), db_path=db_path)


def get_ingestion_job(job_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any] | None:
    return jobs(db_path).get(job_id)

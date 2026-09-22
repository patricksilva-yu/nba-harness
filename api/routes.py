"""HTTP route handlers for the NBA analyst API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.models import AskRequest, IngestionRequest
from api.nba_agent.agent import run_agent
from api.nba_agent.db import get_storage, storage_config
from api.nba_agent.ingestion_jobs import create_ingestion_job, get_ingestion_job, run_ingestion_job
from api.nba_agent.openai_agent import openai_agent_config, run_openai_agent
from api.nba_agent.responses_agent import run_responses_agent
from api.nba_agent.storage import StorageError, storage_health
from api.nba_agent.tools import find_recent_completed_games, find_recent_completed_games_for_resolution, get_box_score, get_cached_games_status


router = APIRouter()


@router.get("/api/health/storage")
def health_storage() -> dict[str, str]:
    try:
        return storage_health(get_storage())
    except (RuntimeError, StorageError) as exc:
        raise HTTPException(status_code=503, detail="Storage is unavailable") from exc


@router.get("/api/recent-games")
def recent_games(
    season: str | None = None,
    season_type: str = "Auto",
    limit: int = 8,
) -> dict[str, Any]:
    if not season_type or season_type.lower() == "auto":
        return find_recent_completed_games_for_resolution(
            season=season or None,
            season_type="Auto",
            limit=limit,
        )
    return find_recent_completed_games(
        season=season or None,
        season_type=season_type,
        limit=limit,
    )


@router.get("/api/db-status")
def db_status(limit: int = 20) -> dict[str, Any]:
    return get_cached_games_status(limit=limit)


@router.get("/api/games/{game_id}/box-score")
def box_score(game_id: str, level: str = "team", detail: bool = False) -> dict[str, Any]:
    return get_box_score(game_id=game_id, level=level, detail=detail)


@router.get("/api/openai-agent/config")
def openai_config() -> dict[str, Any]:
    return {**openai_agent_config(), "storage": storage_config()}


@router.post("/api/ingestion-jobs", status_code=202)
def start_ingestion(request: IngestionRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    job = create_ingestion_job(request.game_id)
    background_tasks.add_task(
        run_ingestion_job,
        job["job_id"],
        request.game_id,
        request.season,
        request.season_type,
        request.force_refresh,
    )
    return job


@router.get("/api/ingestion-jobs/{job_id}")
def ingestion_status(job_id: str) -> dict[str, Any]:
    job = get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


@router.post("/api/ask")
def ask(request: AskRequest) -> dict[str, Any]:
    if request.mode == "responses_tools":
        try:
            return run_responses_agent(
                question=request.question,
                game_id=request.game_id or None,
                season=request.season or None,
                season_type=request.season_type,
                max_evidence=request.max_evidence,
                persist=request.persist,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.mode != "deterministic":
        try:
            return run_openai_agent(
                question=request.question,
                game_id=request.game_id or None,
                season=request.season or None,
                season_type=request.season_type,
                max_evidence=request.max_evidence,
                persist=request.persist,
                mode=request.mode,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_agent(
        question=request.question,
        game_id=request.game_id or None,
        season=request.season or None,
        season_type=request.season_type,
        max_evidence=request.max_evidence,
        persist=request.persist,
    )

"""HTTP route handlers for the NBA analyst API."""

from __future__ import annotations

from contextlib import suppress
from typing import Any
import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import Viewer, require_admin, require_user
from api.models import AskRequest, IngestionRequest
from api.nba_agent.db import get_storage
from api.nba_agent.ingestion_jobs import create_ingestion_job, get_ingestion_job, run_ingestion_job
from api.nba_agent.harness import FollowUpError, follow_up_context, public_run, run_harness
from api.nba_agent.harness.contracts import Limits
from api.nba_agent.harness.model import ResponsesModel
from api.nba_agent.harness.spans import build_spans, summarize
from api.nba_agent.storage.repositories import HarnessRunRepository
from api.nba_agent.storage.favorites import FavoriteTeamsRepository
from api.nba_agent.storage import StorageError, storage_health
from api.nba_agent.tools import (
    find_recent_completed_games,
    find_recent_completed_games_for_resolution,
    get_box_score,
    get_cached_games_status,
    get_game_flow,
)


router = APIRouter()

NBA_TEAM_ABBRS = frozenset("ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS".split())
LOCAL_DEVELOPMENT_USER = "00000000-0000-0000-0000-000000000000"


class FavoriteTeamRequest(BaseModel):
    team_abbr: str


def favorites_repository() -> FavoriteTeamsRepository:
    return FavoriteTeamsRepository(get_storage())


def favorite_owner(viewer: Viewer) -> str:
    return viewer.user_id or LOCAL_DEVELOPMENT_USER


@router.get("/api/me/favorite-teams")
def favorite_teams(viewer: Viewer = Depends(require_user)) -> dict[str, list[str]]:
    try:
        return {"teams": favorites_repository().list(favorite_owner(viewer))}
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Favorite teams unavailable; verify migrations") from exc


@router.get("/api/me/favorite-games")
def favorite_games(viewer: Viewer = Depends(require_user)) -> dict[str, list[dict]]:
    try:
        return {"games": favorites_repository().recent_games(favorite_owner(viewer))}
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Favorite games unavailable; verify migrations") from exc


@router.post("/api/me/favorite-teams", status_code=201)
def add_favorite_team(request: FavoriteTeamRequest, viewer: Viewer = Depends(require_user)) -> dict[str, str]:
    abbr = request.team_abbr.upper().strip()
    if abbr not in NBA_TEAM_ABBRS:
        raise HTTPException(status_code=422, detail="Choose a valid NBA team")
    try:
        favorites_repository().add(favorite_owner(viewer), abbr)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Favorite teams unavailable; verify migrations") from exc
    return {"team_abbr": abbr}


@router.delete("/api/me/favorite-teams/{team_abbr}", status_code=204)
def remove_favorite_team(team_abbr: str, viewer: Viewer = Depends(require_user)) -> None:
    abbr = team_abbr.upper().strip()
    if abbr not in NBA_TEAM_ABBRS:
        raise HTTPException(status_code=422, detail="Choose a valid NBA team")
    try:
        favorites_repository().remove(favorite_owner(viewer), abbr)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Favorite teams unavailable; verify migrations") from exc


def harness_follow_up(request: AskRequest, viewer: Viewer) -> dict | None:
    """Validate a follow-up before any run starts, so failures are plain HTTP errors.

    Only the user who started a conversation can continue it; to anyone else it reads as missing.
    """
    if not request.parent_run_id:
        return None
    try:
        context = follow_up_context(HarnessRunRepository(get_storage()), request.parent_run_id)
    except FollowUpError as exc:
        missing = str(exc) == "parent_run_not_found"
        raise HTTPException(status_code=404 if missing else 409,
                            detail="Earlier run not found" if missing else "Earlier run has not finished") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc
    if viewer.user_id and context["user_id"] != viewer.user_id:
        raise HTTPException(status_code=404, detail="Earlier run not found")
    if request.game_id and context["game_id"] and request.game_id != context["game_id"]:
        raise HTTPException(status_code=400, detail="Follow-up questions stay on the earlier run's game")
    return context


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, allow_nan=False)}\n\n"


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


@router.get("/api/me")
def me(viewer: Viewer = Depends(require_user)) -> dict[str, Any]:
    return {"user_id": viewer.user_id, "is_admin": viewer.is_admin}


@router.get("/api/db-status", dependencies=[Depends(require_admin)])
def db_status(limit: int = 20) -> dict[str, Any]:
    return get_cached_games_status(limit=limit)


@router.get("/api/games/{game_id}/box-score")
def box_score(game_id: str, level: str = "team", detail: bool = False) -> dict[str, Any]:
    return get_box_score(game_id=game_id, level=level, detail=detail)


@router.get("/api/games/{game_id}/flow")
def game_flow(game_id: str) -> dict[str, Any]:
    flow = get_game_flow(game_id)
    if flow["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Game not found")
    return flow


@router.get("/api/conversations")
def conversations(limit: int = 20, viewer: Viewer = Depends(require_user)) -> dict[str, Any]:
    try:
        return {"conversations": HarnessRunRepository(get_storage()).recent_conversations(
            min(max(limit, 1), 100), viewer.user_id)}
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc


@router.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str, viewer: Viewer = Depends(require_user)) -> dict[str, Any]:
    try:
        records = HarnessRunRepository(get_storage()).conversation(conversation_id, viewer.user_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc
    if not records:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation_id": conversation_id, "runs": [public_run(record) for record in records]}


@router.get("/api/runs/{run_id}")
def harness_run(run_id: str, viewer: Viewer = Depends(require_user)) -> dict[str, Any]:
    try:
        record = HarnessRunRepository(get_storage()).get(run_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc
    if record is None or not (viewer.is_admin or record.get("user_id") == viewer.user_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return record


@router.get("/api/traces", dependencies=[Depends(require_admin)])
def traces(limit: int = 50, offset: int = 0, q: str | None = None, status: str | None = None,
           stop_reason: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
    try:
        runs, total = HarnessRunRepository(get_storage()).list_runs(
            min(max(limit, 1), 200), max(offset, 0), (q or "").strip() or None, status, stop_reason, conversation_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc
    return {"traces": runs, "total": total}


@router.get("/api/traces/{run_id}", dependencies=[Depends(require_admin)])
def trace_detail(run_id: str) -> dict[str, Any]:
    try:
        record = HarnessRunRepository(get_storage()).get(run_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Run storage unavailable; verify migrations") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"trace": summarize(record), "spans": build_spans(record)}


@router.post("/api/ingestion-jobs", status_code=202, dependencies=[Depends(require_admin)])
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


@router.get("/api/ingestion-jobs/{job_id}", dependencies=[Depends(require_admin)])
def ingestion_status(job_id: str) -> dict[str, Any]:
    job = get_ingestion_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


@router.post("/api/ask/stream")
async def ask_stream(request: AskRequest, viewer: Viewer = Depends(require_user)) -> StreamingResponse:
    """Server-sent events: one `step` per durable harness event, then `result` or `error`.

    Closing the connection cancels the run, which is recorded as `cancelled`.
    """
    follow_up = harness_follow_up(request, viewer)
    try:
        limits = Limits.from_environment()
        model = ResponsesModel()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid harness configuration; check model and resource settings") from exc
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            result = await run_harness(
                question=request.question, game_id=request.game_id or None, season=request.season or None,
                season_type=request.season_type, configuration=request.harness_configuration,
                limits=limits, model=model, follow_up=follow_up, on_event=queue.put_nowait, user_id=viewer.user_id,
            )
            queue.put_nowait(("result", public_run(result["trace"])))
        except Exception:
            # Raw exception text may carry provider or storage detail; never stream it.
            queue.put_nowait(("error", {"detail": "Harness unavailable; check configuration and database migrations"}))
        finally:
            try:
                await model.close()
            finally:
                queue.put_nowait(None)

    async def stream():
        task = asyncio.create_task(produce())
        try:
            while (item := await queue.get()) is not None:
                yield sse(*item) if isinstance(item, tuple) else sse("step", item)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/ask")
def ask(request: AskRequest, viewer: Viewer = Depends(require_user)) -> dict[str, Any]:
    follow_up = harness_follow_up(request, viewer)
    try:
        return asyncio.run(run_harness(
            question=request.question, game_id=request.game_id or None, season=request.season or None,
            season_type=request.season_type, configuration=request.harness_configuration, follow_up=follow_up,
            user_id=viewer.user_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid harness configuration; check model and resource settings") from exc
    except (StorageError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Harness unavailable; check configuration and database migrations") from exc

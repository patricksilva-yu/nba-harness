"""Small local ingestion job runner with explicit persisted states."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from api.nba_agent.db import DEFAULT_DB, connect, create_schema
from api.nba_agent.service import NBAService

VALID_JOB_STATES = {"queued", "fetching", "ready", "partial", "failed"}


def create_ingestion_job(game_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    job_id = f"ingest_{uuid.uuid4().hex}"
    con = connect(db_path, read_only=False)
    create_schema(con)
    con.execute("INSERT INTO ingestion_jobs (job_id, game_id, status) VALUES (?, ?, ?)", [job_id, game_id, "queued"])
    con.close()
    return {"job_id": job_id, "game_id": game_id, "status": "queued"}


def update_ingestion_job(job_id: str, status: str, *, result: dict[str, Any] | None = None, error: str | None = None, db_path: Path = DEFAULT_DB) -> None:
    if status not in VALID_JOB_STATES:
        raise ValueError(f"Unknown ingestion job status: {status}")
    con = connect(db_path, read_only=False)
    con.execute(
        "UPDATE ingestion_jobs SET status = ?, result_json = ?, error = ?, updated_at = current_timestamp WHERE job_id = ?",
        [status, json.dumps(result, default=str) if result is not None else None, error, job_id],
    )
    con.close()


def run_ingestion_job(job_id: str, game_id: str, season: str | None = None, season_type: str = "Playoffs", force_refresh: bool = False, db_path: Path = DEFAULT_DB) -> None:
    update_ingestion_job(job_id, "fetching", db_path=db_path)
    try:
        result = NBAService(db_path).ensure_game_data(game_id, season=season, season_type=season_type, force_refresh=force_refresh)
        update_ingestion_job(job_id, "partial" if result.get("warnings") else "ready", result=result, db_path=db_path)
    except Exception as exc:
        update_ingestion_job(job_id, "failed", error=str(exc), db_path=db_path)


def get_ingestion_job(job_id: str, db_path: Path = DEFAULT_DB) -> dict[str, Any] | None:
    con = connect(db_path)
    row = con.execute(
        "SELECT job_id, game_id, status, error, result_json, created_at, updated_at FROM ingestion_jobs WHERE job_id = ?",
        [job_id],
    ).fetchone()
    con.close()
    if not row:
        return None
    return {"job_id": row[0], "game_id": row[1], "status": row[2], "error": row[3], "result": json.loads(row[4]) if row[4] else None, "created_at": row[5], "updated_at": row[6]}

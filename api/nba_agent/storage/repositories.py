"""Repositories for persisted application records.

They deliberately expose domain operations instead of database connections.
Additional analytical reads will move here incrementally in later phases.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from api.nba_agent.storage.base import StorageBackend


def decode_json(value: Any) -> Any:
    """Normalize DuckDB text and psycopg2 JSONB return values."""
    return json.loads(value) if isinstance(value, str) else value


class HarnessRunRepository:
    """One atomic snapshot per event; no connection is held across network awaits.

    A run has one controller writer. Terminal records are immutable. An abrupt
    process death leaves the last checkpoint visibly running, never successful.
    """

    def __init__(self, storage: StorageBackend):
        self._storage = storage

    def create(self, record: dict) -> None:
        self._storage.initialize()
        connection = self._storage.open(read_only=False)
        try:
            connection.execute(
                """INSERT INTO harness_runs (run_id, status, record_json, conversation_id, parent_run_id)
                VALUES (?, ?, ?, ?, ?)""",
                [record["run_id"], "running", json.dumps(record, allow_nan=False),
                 record.get("conversation_id"), record.get("parent_run_id")],
            )
        finally:
            connection.close()

    def save(self, record: dict) -> None:
        connection = self._storage.open(read_only=False)
        try:
            row = connection.execute(
                """UPDATE harness_runs SET status = ?, stop_reason = ?, record_json = ?,
                updated_at = current_timestamp WHERE run_id = ? AND status = 'running'
                RETURNING run_id""",
                [record["status"], record.get("stop_reason"), json.dumps(record, allow_nan=False), record["run_id"]],
            ).fetchone()
            if row is None:
                raise RuntimeError("Harness run missing or already terminal")
        finally:
            connection.close()

    def get(self, run_id: str) -> dict | None:
        connection = self._storage.open()
        try:
            row = connection.execute("SELECT record_json FROM harness_runs WHERE run_id = ?", [run_id]).fetchone()
            return decode_json(row[0]) if row else None
        finally:
            connection.close()

    def conversation(self, conversation_id: str) -> list[dict]:
        """Every run in a conversation, oldest first."""
        connection = self._storage.open()
        try:
            rows = connection.execute(
                """SELECT record_json FROM harness_runs WHERE conversation_id = ?
                ORDER BY created_at, run_id""",
                [conversation_id],
            ).fetchall()
            return [decode_json(row[0]) for row in rows]
        finally:
            connection.close()

    def recent_conversations(self, limit: int = 20) -> list[dict]:
        """Newest conversations first, each described by its opening run."""
        connection = self._storage.open()
        try:
            rows = connection.execute(
                """SELECT first.conversation_id, first.record_json, latest.runs, latest.updated_at
                FROM (SELECT conversation_id, COUNT(*) AS runs, MAX(updated_at) AS updated_at
                      FROM harness_runs WHERE conversation_id IS NOT NULL GROUP BY conversation_id) AS latest
                JOIN harness_runs AS first
                  ON first.conversation_id = latest.conversation_id AND first.parent_run_id IS NULL
                ORDER BY latest.updated_at DESC LIMIT ?""",
                [limit],
            ).fetchall()
        finally:
            connection.close()
        conversations = []
        for conversation_id, record_json, runs, updated_at in rows:
            record = decode_json(record_json)
            resolution = record.get("resolution") or {}
            conversations.append({
                "conversation_id": conversation_id, "question": record["question"], "game_id": record.get("game_id"),
                "game_label": resolution.get("label"), "runs": runs,
                "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
            })
        return conversations


class EvidenceRepository:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def save_many(self, game_id: str, packets: list[dict[str, Any]]) -> None:
        if not packets:
            return
        connection = self._storage.open(read_only=False)
        try:
            connection.executemany(
                """
                INSERT INTO evidence_packets (
                    packet_id, game_id, packet_type, claim_seed, source_provider,
                    source_detail, evidence_level, confidence, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (packet_id) DO UPDATE SET
                    game_id = EXCLUDED.game_id,
                    packet_type = EXCLUDED.packet_type,
                    claim_seed = EXCLUDED.claim_seed,
                    source_provider = EXCLUDED.source_provider,
                    source_detail = EXCLUDED.source_detail,
                    evidence_level = EXCLUDED.evidence_level,
                    confidence = EXCLUDED.confidence,
                    payload_json = EXCLUDED.payload_json
                """,
                [
                    [
                        packet["packet_id"],
                        game_id,
                        packet.get("type"),
                        packet.get("claim_seed"),
                        packet.get("source", {}).get("provider"),
                        packet.get("source", {}).get("detail")
                        or packet.get("source", {}).get("endpoint"),
                        packet.get("evidence_level"),
                        packet.get("confidence"),
                        json.dumps(packet, default=str),
                    ]
                    for packet in packets
                ],
            )
        finally:
            connection.close()


class AnalysisRunRepository:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def create(self, game_id: str, user_question: str, memo_markdown: str, packet_ids: list[str]) -> str:
        run_id = f"analysis_{game_id}_{uuid.uuid4().hex}"
        connection = self._storage.open(read_only=False)
        try:
            connection.execute(
                """
                INSERT INTO analysis_runs (
                    run_id, game_id, user_question, memo_markdown, packet_ids_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [run_id, game_id, user_question, memo_markdown, json.dumps(packet_ids)],
            )
        finally:
            connection.close()
        return run_id


class IngestionJobRepository:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def create(self, game_id: str) -> dict[str, Any]:
        self._storage.initialize()
        job_id = f"ingest_{uuid.uuid4().hex}"
        connection = self._storage.open(read_only=False)
        try:
            connection.execute(
                "INSERT INTO ingestion_jobs (job_id, game_id, status) VALUES (?, ?, ?)",
                [job_id, game_id, "queued"],
            )
        finally:
            connection.close()
        return {"job_id": job_id, "game_id": game_id, "status": "queued"}

    def update(self, job_id: str, status: str, *, result: dict[str, Any] | None, error: str | None) -> None:
        connection = self._storage.open(read_only=False)
        try:
            connection.execute(
                "UPDATE ingestion_jobs SET status = ?, result_json = ?, error = ?, updated_at = current_timestamp WHERE job_id = ?",
                [status, json.dumps(result, default=str) if result is not None else None, error, job_id],
            )
        finally:
            connection.close()

    def claim(self, job_id: str) -> bool:
        """Atomically transition a queued job to fetching exactly once."""
        connection = self._storage.open(read_only=False)
        try:
            claimed = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'fetching', updated_at = current_timestamp
                WHERE job_id = ? AND status = 'queued'
                RETURNING job_id
                """,
                [job_id],
            ).fetchone()
            return claimed is not None
        finally:
            connection.close()

    def get(self, job_id: str) -> dict[str, Any] | None:
        connection = self._storage.open()
        try:
            row = connection.execute(
                "SELECT job_id, game_id, status, error, result_json, created_at, updated_at FROM ingestion_jobs WHERE job_id = ?",
                [job_id],
            ).fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return {
            "job_id": row[0],
            "game_id": row[1],
            "status": row[2],
            "error": row[3],
            "result": decode_json(row[4]) if row[4] is not None else None,
            "created_at": row[5],
            "updated_at": row[6],
        }

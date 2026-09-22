"""Safe storage operations shared by local maintenance commands and HTTP health checks."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from api.nba_agent.storage.base import StorageBackend, StorageError


logger = logging.getLogger(__name__)


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def raw_response_retention_days() -> int:
    """Return the configured retention period; 60 days is the initial default."""
    return _bounded_int("NBA_RAW_RESPONSE_RETENTION_DAYS", default=60, minimum=1, maximum=3650)


def raw_response_retention_batch_size() -> int:
    """Limit every cleanup transaction to prevent long-running delete locks."""
    return _bounded_int("NBA_RAW_RESPONSE_RETENTION_BATCH_SIZE", default=500, minimum=1, maximum=10_000)


def cleanup_expired_raw_responses(
    storage: StorageBackend,
    *,
    retention_days: int | None = None,
    batch_size: int | None = None,
    now: datetime | None = None,
) -> int:
    """Delete at most one oldest-first batch of expired raw captures.

    A scheduler may invoke this repeatedly until it returns zero. The operation
    intentionally stores no request or response data in logs.
    """
    retention_days = retention_days if retention_days is not None else raw_response_retention_days()
    batch_size = batch_size if batch_size is not None else raw_response_retention_batch_size()
    if retention_days < 1 or batch_size < 1:
        raise ValueError("retention_days and batch_size must be positive")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    connection = storage.open(read_only=False)
    try:
        deleted = connection.execute(
            """
            DELETE FROM raw_responses
            WHERE response_id IN (
                SELECT response_id
                FROM raw_responses
                WHERE fetched_at < ?
                ORDER BY fetched_at ASC, response_id ASC
                LIMIT ?
            )
            RETURNING response_id
            """,
            [cutoff, batch_size],
        ).fetchall()
    finally:
        connection.close()
    logger.info(
        "raw_response_retention_batch_completed",
        extra={"storage_backend": storage.backend, "deleted_count": len(deleted), "retention_days": retention_days},
    )
    return len(deleted)


def storage_health(storage: StorageBackend) -> dict[str, str]:
    """Perform a non-mutating round trip without disclosing connection details."""
    connection = storage.open()
    try:
        connection.execute("SELECT 1").fetchone()
    except StorageError:
        logger.warning("storage_health_check_failed", extra={"storage_backend": storage.backend})
        raise
    finally:
        connection.close()
    return {"status": "ok", "backend": storage.backend}

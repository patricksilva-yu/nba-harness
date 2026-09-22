"""Backend-neutral storage contracts and database adapters."""

from api.nba_agent.storage.base import StorageBackend, StorageConnection, StorageError
from api.nba_agent.storage.duckdb import DuckDBStorage
from api.nba_agent.storage.postgres import PostgresStorage
from api.nba_agent.storage.operations import cleanup_expired_raw_responses, storage_health

__all__ = [
    "DuckDBStorage",
    "PostgresStorage",
    "StorageBackend",
    "StorageConnection",
    "StorageError",
    "cleanup_expired_raw_responses",
    "storage_health",
]

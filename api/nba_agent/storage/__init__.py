"""Backend-neutral storage contracts and database adapters."""

from api.nba_agent.storage.base import StorageBackend, StorageConnection, StorageError
from api.nba_agent.storage.duckdb import DuckDBStorage
from api.nba_agent.storage.postgres import PostgresStorage

__all__ = ["DuckDBStorage", "PostgresStorage", "StorageBackend", "StorageConnection", "StorageError"]

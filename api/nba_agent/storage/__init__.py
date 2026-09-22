"""Backend-neutral storage contracts and the current DuckDB adapter.

Application code depends on these contracts rather than importing a database
driver. PostgreSQL is deliberately not registered until its adapter exists.
"""

from api.nba_agent.storage.base import StorageBackend, StorageConnection, StorageError
from api.nba_agent.storage.duckdb import DuckDBStorage

__all__ = ["DuckDBStorage", "StorageBackend", "StorageConnection", "StorageError"]

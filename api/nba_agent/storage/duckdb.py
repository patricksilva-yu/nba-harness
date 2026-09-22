"""DuckDB implementation of the storage contract.

This adapter is a transition implementation. It keeps local behavior stable
while callers stop depending on DuckDB types and connection construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import duckdb

from api.nba_agent.storage.base import StorageConnection, StorageError


class DuckDBConnection:
    """Translate driver failures while preserving the current query API."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self._connection = connection

    @property
    def description(self) -> Any:
        return self._connection.description

    def execute(self, query: str, parameters: Sequence[Any] | None = None) -> Any:
        try:
            if parameters is None:
                return self._connection.execute(query)
            return self._connection.execute(query, parameters)
        except duckdb.Error as exc:
            raise StorageError(str(exc)) from exc

    def executemany(self, query: str, parameters: Sequence[Sequence[Any]]) -> Any:
        try:
            return self._connection.executemany(query, parameters)
        except duckdb.Error as exc:
            raise StorageError(str(exc)) from exc

    def close(self) -> None:
        self._connection.close()


class DuckDBStorage:
    """Local-file storage adapter used until PostgreSQL is implemented."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def open(self, *, read_only: bool = True) -> StorageConnection:
        try:
            return DuckDBConnection(duckdb.connect(str(self.path), read_only=read_only))
        except duckdb.Error as exc:
            raise StorageError(str(exc)) from exc

    def initialize(self) -> None:
        # Kept as a compatibility bridge until Phase 2's PostgreSQL migration
        # owns production schema creation.
        from api.nba_agent.db import create_schema

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.open(read_only=False)
        try:
            create_schema(connection)
        finally:
            connection.close()

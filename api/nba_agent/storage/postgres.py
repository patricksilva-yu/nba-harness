"""PostgreSQL implementation of the NBA storage contract."""

from __future__ import annotations

import os
import re
from typing import Any, Sequence

import psycopg2
from psycopg2 import pool
from psycopg2 import sql

from api.nba_agent.storage.base import StorageConnection, StorageError


_QMARK = re.compile(r"\?")


class PostgresConnection:
    """One pooled PostgreSQL connection with a transaction per open/close scope."""

    backend = "postgres"

    def __init__(self, connection: Any, connection_pool: pool.ThreadedConnectionPool) -> None:
        self._connection = connection
        self._pool = connection_pool
        self._cursor: Any | None = None
        self._failed = False
        self._closed = False

    @property
    def description(self) -> Any:
        return self._cursor.description if self._cursor is not None else None

    @staticmethod
    def _sql(query: str) -> str:
        # Existing application queries use DB-API qmark placeholders. Keep that
        # contract at the boundary and translate only for psycopg2.
        return _QMARK.sub("%s", query)

    def execute(self, query: str, parameters: Sequence[Any] | None = None) -> "PostgresConnection":
        try:
            self._cursor = self._connection.cursor()
            self._cursor.execute(self._sql(query), parameters)
            return self
        except psycopg2.Error as exc:
            self._failed = True
            raise StorageError("PostgreSQL query failed") from exc

    def executemany(self, query: str, parameters: Sequence[Sequence[Any]]) -> "PostgresConnection":
        try:
            self._cursor = self._connection.cursor()
            self._cursor.executemany(self._sql(query), parameters)
            return self
        except psycopg2.Error as exc:
            self._failed = True
            raise StorageError("PostgreSQL batch query failed") from exc

    def fetchone(self) -> Any:
        return self._cursor.fetchone() if self._cursor is not None else None

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall() if self._cursor is not None else []

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._failed:
                self._connection.rollback()
            else:
                self._connection.commit()
        except psycopg2.Error as exc:
            self._connection.rollback()
            raise StorageError("PostgreSQL transaction finalization failed") from exc
        finally:
            if self._cursor is not None:
                self._cursor.close()
            self._pool.putconn(self._connection)


class PostgresStorage:
    """Pooled PostgreSQL storage selected by ``DATABASE_URL``.

    The database must already be migrated with Alembic. This adapter never
    creates schema at application startup.
    """

    backend = "postgres"
    path = None
    _pools: dict[tuple[str, int, int, int, int], pool.ThreadedConnectionPool] = {}

    def __init__(self, database_url: str, *, schema: str | None = None) -> None:
        self.database_url = database_url
        if schema is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("PostgreSQL schema must be a simple identifier")
        self._schema = schema
        self._min_connections = int(os.getenv("NBA_DB_POOL_MIN", "1"))
        self._max_connections = int(os.getenv("NBA_DB_POOL_MAX", "5"))
        self._connect_timeout_seconds = int(os.getenv("NBA_DB_CONNECT_TIMEOUT_SECONDS", "5"))
        self._statement_timeout_ms = int(os.getenv("NBA_DB_STATEMENT_TIMEOUT_MS", "10000"))
        if self._min_connections < 1 or self._max_connections < self._min_connections:
            raise RuntimeError("NBA_DB_POOL_MIN and NBA_DB_POOL_MAX must define a positive valid range")

    @property
    def _pool(self) -> pool.ThreadedConnectionPool:
        key = (
            self.database_url,
            self._min_connections,
            self._max_connections,
            self._connect_timeout_seconds,
            self._statement_timeout_ms,
        )
        if key not in self._pools:
            try:
                self._pools[key] = pool.ThreadedConnectionPool(
                    self._min_connections,
                    self._max_connections,
                    self.database_url,
                    connect_timeout=self._connect_timeout_seconds,
                    options=f"-c statement_timeout={self._statement_timeout_ms}",
                )
            except (psycopg2.Error, ValueError) as exc:
                raise StorageError("PostgreSQL connection pool could not be created") from exc
        return self._pools[key]

    def open(self, *, read_only: bool = True) -> StorageConnection:
        try:
            connection = self._pool.getconn()
            connection.set_session(readonly=read_only, autocommit=False)
            if self._schema is not None:
                cursor = connection.cursor()
                cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self._schema)))
                cursor.close()
            return PostgresConnection(connection, self._pool)
        except psycopg2.Error as exc:
            raise StorageError("PostgreSQL connection could not be acquired") from exc

    def initialize(self) -> None:
        """Verify migrations were applied without performing runtime DDL."""
        connection = self.open()
        try:
            version = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            if version is None:
                raise StorageError("PostgreSQL schema is not at an Alembic revision; run `alembic upgrade head`")
        except StorageError:
            raise
        finally:
            connection.close()

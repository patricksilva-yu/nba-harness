"""Storage contracts shared by all database adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence


class StorageError(RuntimeError):
    """A database-driver error exposed through the application storage boundary."""


class StorageConnection(Protocol):
    """Small common subset of the connection API used by the current query layer."""

    description: Any
    backend: str

    def execute(self, query: str, parameters: Sequence[Any] | None = None) -> Any: ...

    def executemany(self, query: str, parameters: Sequence[Sequence[Any]]) -> Any: ...

    def close(self) -> None: ...


class StorageBackend(Protocol):
    """Adapter selected by configuration for one application process."""

    path: Path | None
    backend: str

    def open(self, *, read_only: bool = True) -> StorageConnection: ...

    def initialize(self) -> None: ...

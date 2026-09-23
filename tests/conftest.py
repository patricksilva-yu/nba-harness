import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_storage_configuration(monkeypatch):
    """Keep unit tests independent from a developer or deployment ``.env``.

    PostgreSQL integration tests opt in explicitly with their disposable test
    URL. No test may inherit the active application's backend or schema.
    """
    monkeypatch.setenv("NBA_STORAGE_BACKEND", "duckdb")
    monkeypatch.delenv("POSTGRES_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("NBA_POSTGRES_SCHEMA", raising=False)

"""Integration coverage for the versioned PostgreSQL schema.

These tests intentionally require an explicitly supplied disposable database.
They never guess a developer or production DATABASE_URL.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="set POSTGRES_TEST_DATABASE_URL to run PostgreSQL migration integration tests",
)


def alembic_config(connection) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    return config


def test_initial_migration_creates_canonical_schema_and_downgrades_cleanly():
    schema = f"phase2_{uuid.uuid4().hex}"
    engine = create_engine(POSTGRES_TEST_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = alembic_config(connection)

            command.upgrade(config, "head")

            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == {
                "alembic_version",
                "analysis_runs",
                "box_scores_advanced_team",
                "box_scores_player",
                "box_scores_team",
                "evidence_packets",
                "games",
                "ingestion_jobs",
                "lineup_stints",
                "play_by_play_events",
                "raw_responses",
            }
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260922_01"

            raw_columns = {column["name"]: column for column in inspector.get_columns("raw_responses")}
            evidence_columns = {column["name"]: column for column in inspector.get_columns("evidence_packets")}
            assert raw_columns["request_json"]["type"].__class__.__name__ == "JSONB"
            assert evidence_columns["created_at"]["type"].timezone is True

            game_fks = inspector.get_foreign_keys("box_scores_team")
            assert game_fks == [
                {
                    **game_fks[0],
                    "constrained_columns": ["game_id"],
                    "referred_table": "games",
                    "referred_columns": ["game_id"],
                    "options": {"ondelete": "CASCADE"},
                }
            ]
            constraints = {item["name"] for item in inspector.get_check_constraints("ingestion_jobs")}
            assert "ck_ingestion_jobs_status" in constraints
            indexes = {item["name"] for item in inspector.get_indexes("raw_responses")}
            assert {"ix_raw_responses_fetched_at", "ix_raw_responses_game_id"}.issubset(indexes)

            command.downgrade(config, "base")
            inspector = inspect(connection)
            assert inspector.get_table_names() == ["alembic_version"]
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()

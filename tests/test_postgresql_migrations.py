"""Integration coverage for the versioned PostgreSQL schema.

These tests intentionally require an explicitly supplied disposable database.
They never guess a developer or production POSTGRES_CONNECTION_STRING.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from api.nba_agent.storage import PostgresStorage, StorageError
from api.nba_agent.storage.operations import cleanup_expired_raw_responses, storage_health
from api.nba_agent.storage.repositories import EvidenceRepository, IngestionJobRepository
from api.nba_agent.storage.repositories import HarnessRunRepository
from api.nba_agent.db import get_storage
from api.nba_agent.tools import get_box_score
from api.app import app

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
                "harness_runs",
                "box_scores_advanced_team",
                "box_scores_player",
                "box_scores_team",
                "evidence_packets",
                "games",
                "ingestion_jobs",
                "lineup_stints",
                "play_by_play_events",
                "raw_responses",
                "seed_player_game_logs",
            }
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260924_01"
            harness_columns = {column["name"] for column in inspector.get_columns("harness_runs")}
            assert {"conversation_id", "parent_run_id", "user_id"}.issubset(harness_columns)
            assert any(fk["referred_table"] == "harness_runs" and fk["constrained_columns"] == ["parent_run_id"]
                       for fk in inspector.get_foreign_keys("harness_runs"))
            assert {"ix_harness_runs_conversation_id", "ix_harness_runs_user_id"}.issubset(
                {item["name"] for item in inspector.get_indexes("harness_runs")})
            # Every application table denies Supabase's browser-facing roles.
            without_rls = connection.execute(text(
                """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :schema AND c.relkind = 'r' AND NOT c.relrowsecurity"""), {"schema": schema}).all()
            assert without_rls == []

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


def test_postgres_storage_executes_parameterized_upserts_and_rolls_back_failures():
    schema = f"phase4_{uuid.uuid4().hex}"
    engine = create_engine(POSTGRES_TEST_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            command.upgrade(alembic_config(connection), "head")

        storage = PostgresStorage(POSTGRES_TEST_URL, schema=schema)
        storage.initialize()
        harness_repository = HarnessRunRepository(storage)
        harness_record = {"run_id": "harness_integration", "status": "running", "events": []}
        harness_repository.create(harness_record)
        harness_record.update(status="completed", stop_reason="supported", events=[{"sequence": 1, "kind": "run_stopped"}])
        harness_repository.save(harness_record)
        assert harness_repository.get("harness_integration") == harness_record
        follow_up = {"run_id": "harness_follow_up", "status": "running", "question": "Next?", "events": [],
                     "conversation_id": "harness_integration", "parent_run_id": "harness_integration"}
        harness_repository.create(follow_up)
        assert [r["run_id"] for r in harness_repository.conversation("harness_integration")] == ["harness_follow_up"]
        # The opening run predates conversation ids, so no conversation has a first run to describe.
        assert harness_repository.recent_conversations() == []
        owner, other = str(uuid.uuid4()), str(uuid.uuid4())
        harness_repository.create({"run_id": "harness_owned", "status": "running", "question": "Mine?", "events": [],
                                   "conversation_id": "harness_owned", "user_id": owner})
        assert [c["conversation_id"] for c in harness_repository.recent_conversations(user_id=owner)] == ["harness_owned"]
        assert harness_repository.recent_conversations(user_id=other) == []
        assert harness_repository.conversation("harness_owned", other) == []
        assert [r["run_id"] for r in harness_repository.conversation("harness_owned", owner)] == ["harness_owned"]
        connection = storage.open(read_only=False)
        connection.execute(
            "INSERT INTO games (game_id, game_date, source) VALUES (?, ?, ?)",
            ["game_1", date(2025, 5, 1), "test"],
        )
        connection.close()

        packet = {
            "packet_id": "packet_1",
            "type": "game_snapshot",
            "claim_seed": "first",
            "source": {"provider": "test", "detail": "phase4"},
            "evidence_level": "core",
            "confidence": "high",
        }
        EvidenceRepository(storage).save_many("game_1", [packet])
        packet["claim_seed"] = "replacement"
        EvidenceRepository(storage).save_many("game_1", [packet])
        job = IngestionJobRepository(storage).create("game_1")
        assert IngestionJobRepository(storage).claim(job["job_id"]) is True
        assert IngestionJobRepository(storage).claim(job["job_id"]) is False
        IngestionJobRepository(storage).update(job["job_id"], "ready", result={"game_id": "game_1"}, error=None)

        connection = storage.open()
        assert connection.execute("SELECT claim_seed, payload_json FROM evidence_packets WHERE packet_id = ?", ["packet_1"]).fetchone() == (
            "replacement",
            packet,
        )
        connection.close()
        assert IngestionJobRepository(storage).get(job["job_id"])["result"] == {"game_id": "game_1"}

        connection = storage.open(read_only=False)
        connection.execute(
            """
            INSERT INTO raw_responses (response_id, provider, endpoint, request_json, response_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ["old_raw", "test", "test", "{}", "{}", datetime.now(timezone.utc) - timedelta(days=61)],
        )
        connection.close()
        assert cleanup_expired_raw_responses(storage, retention_days=60, batch_size=10) == 1
        assert storage_health(storage) == {"status": "ok", "backend": "postgres"}

        failed = storage.open(read_only=False)
        failed.execute("INSERT INTO games (game_id, source) VALUES (?, ?)", ["rolled_back", "test"])
        with pytest.raises(StorageError):
            failed.execute("SELECT * FROM table_that_does_not_exist")
        failed.close()
        connection = storage.open()
        assert connection.execute("SELECT COUNT(*) FROM games WHERE game_id = ?", ["rolled_back"]).fetchone() == (0,)
        connection.close()

        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        engine.dispose()


def test_postgres_mode_matches_duckdb_box_score_and_handles_concurrent_claims(monkeypatch, tmp_path):
    schema = f"phase6_{uuid.uuid4().hex}"
    engine = create_engine(POSTGRES_TEST_URL)
    postgres_storage = PostgresStorage(POSTGRES_TEST_URL, schema=schema)
    duck_path = tmp_path / "parity.duckdb"
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            command.upgrade(alembic_config(connection), "head")

        from api.nba_agent.db import initialize_database

        initialize_database(duck_path)
        _seed_box_score(get_storage(duck_path))
        _seed_box_score(postgres_storage)
        assert get_box_score("game_parity", db_path=duck_path) == _box_score_from(postgres_storage)

        monkeypatch.setenv("NBA_STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("POSTGRES_CONNECTION_STRING", POSTGRES_TEST_URL)
        monkeypatch.setenv("NBA_POSTGRES_SCHEMA", schema)
        assert get_box_score("game_parity") == _box_score_from(postgres_storage)
        response = TestClient(app).get("/api/games/game_parity/box-score")
        assert response.status_code == 200
        assert response.json()["summary"]["row_count"] == 2

        job = IngestionJobRepository(postgres_storage).create("game_claim")
        barrier = threading.Barrier(2)
        claimed: list[bool] = []

        def claim_once() -> None:
            barrier.wait()
            claimed.append(IngestionJobRepository(postgres_storage).claim(job["job_id"]))

        threads = [threading.Thread(target=claim_once), threading.Thread(target=claim_once)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(claimed) == [False, True]
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def _seed_box_score(storage) -> None:
    connection = storage.open(read_only=False)
    try:
        connection.execute(
            """
            INSERT INTO games (
                game_id, game_date, season_type, home_team_id, home_team_abbr,
                away_team_id, away_team_abbr, home_score, away_score, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ["game_parity", date(2025, 5, 1), "Playoffs", "home", "HOM", "away", "AWY", 100, 101, "test"],
        )
        connection.executemany(
            """
            INSERT INTO box_scores_team (game_id, team_side, team_id, team_abbr, fgm, fga, pts, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ["game_parity", "away", "away", "AWY", 38, 82, 101, "test"],
                ["game_parity", "home", "home", "HOM", 37, 81, 100, "test"],
            ],
        )
    finally:
        connection.close()


def _box_score_from(storage):
    # Route through the public read behavior while keeping the test's isolated
    # schema separate from process-level environment selection.
    connection = storage.open()
    try:
        rows = connection.execute(
            "SELECT * FROM box_scores_team WHERE game_id = ? ORDER BY team_side", ["game_parity"]
        ).fetchall()
        columns = [column[0] for column in connection.description]
    finally:
        connection.close()
    return {
        "summary": {
            "game_id": "game_parity",
            "level": "team",
            "detail": False,
            "row_count": 2,
            "confidence": "high",
        },
        "box_score": [dict(zip(columns, row)) for row in rows],
        "available_expansions": [
            {"tool": "game_context.get_box_score", "description": "Request detail=true for the full team box score."}
        ],
        "warnings": [],
    }

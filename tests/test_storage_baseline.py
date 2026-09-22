import json

import duckdb
import pytest

from api.nba_agent.db import connect, create_schema, initialize_database, storage_config
from api.nba_agent.ingestion_jobs import (
    create_ingestion_job,
    get_ingestion_job,
    update_ingestion_job,
)
from api.nba_agent.tools import persist_analysis_run, persist_evidence_packets


EXPECTED_PRIMARY_KEYS = {
    "raw_responses": ["response_id"],
    "games": ["game_id"],
    "box_scores_team": ["game_id", "team_side"],
    "box_scores_player": ["game_id", "player_id"],
    "box_scores_advanced_team": ["game_id", "team_id"],
    "play_by_play_events": ["game_id", "eventnum"],
    "lineup_stints": ["stint_id"],
    "evidence_packets": ["packet_id"],
    "analysis_runs": ["run_id"],
    "ingestion_jobs": ["job_id"],
}


def table_info(con, table_name):
    return con.execute(f"PRAGMA table_info('{table_name}')").fetchall()


def test_schema_contract_includes_exact_tables_and_primary_keys(tmp_path):
    db_path = tmp_path / "schema_contract.duckdb"
    con = connect(db_path, read_only=False)
    create_schema(con)

    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert tables == set(EXPECTED_PRIMARY_KEYS)

    for table_name, expected_columns in EXPECTED_PRIMARY_KEYS.items():
        primary_key_columns = [
            row[1]
            for row in sorted(table_info(con, table_name), key=lambda row: row[5] or 0)
            if row[5]
        ]
        assert primary_key_columns == expected_columns

    con.close()


def test_schema_contract_records_timestamp_defaults_and_text_json(tmp_path):
    db_path = tmp_path / "column_contract.duckdb"
    con = connect(db_path, read_only=False)
    create_schema(con)

    raw_columns = {row[1]: row for row in table_info(con, "raw_responses")}
    evidence_columns = {row[1]: row for row in table_info(con, "evidence_packets")}
    job_columns = {row[1]: row for row in table_info(con, "ingestion_jobs")}

    assert raw_columns["request_json"][2] == "VARCHAR"
    assert raw_columns["response_json"][2] == "VARCHAR"
    assert evidence_columns["payload_json"][2] == "VARCHAR"
    assert job_columns["result_json"][2] == "VARCHAR"
    assert "current_timestamp" in raw_columns["fetched_at"][4].lower()
    assert "current_timestamp" in evidence_columns["created_at"][4].lower()
    assert "current_timestamp" in job_columns["created_at"][4].lower()
    assert "current_timestamp" in job_columns["updated_at"][4].lower()

    con.close()


def test_initialize_database_is_idempotent(tmp_path):
    db_path = tmp_path / "idempotent.duckdb"

    initialize_database(db_path)
    initialize_database(db_path)

    con = connect(db_path)
    table_count = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchone()[0]
    con.close()
    assert table_count == len(EXPECTED_PRIMARY_KEYS)


def test_postgres_config_requires_url_but_does_not_change_runtime_connection(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("NBA_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        storage_config()

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/nba")
    assert storage_config()["backend"] == "postgres"

    con = connect(tmp_path / "still_duckdb.duckdb", read_only=False)
    assert isinstance(con, duckdb.DuckDBPyConnection)
    con.close()


def test_evidence_packet_write_replaces_same_packet_id(tmp_path):
    db_path = tmp_path / "evidence.duckdb"
    initialize_database(db_path)
    first = {
        "packet_id": "snapshot_game_1",
        "type": "game_snapshot",
        "claim_seed": "First claim",
        "source": {"provider": "fixture", "detail": "first"},
        "evidence_level": "core",
        "confidence": "low",
    }
    replacement = {
        **first,
        "claim_seed": "Replacement claim",
        "confidence": "high",
        "source": {"provider": "fixture", "detail": "replacement"},
    }

    assert persist_evidence_packets("game_1", [first], db_path) is True
    assert persist_evidence_packets("game_1", [replacement], db_path) is True

    con = connect(db_path)
    rows = con.execute(
        "SELECT claim_seed, confidence, payload_json FROM evidence_packets WHERE packet_id = ?",
        ["snapshot_game_1"],
    ).fetchall()
    con.close()

    assert len(rows) == 1
    assert rows[0][0:2] == ("Replacement claim", "high")
    assert json.loads(rows[0][2])["source"]["detail"] == "replacement"


def test_analysis_runs_are_append_only(tmp_path):
    db_path = tmp_path / "analysis_runs.duckdb"
    initialize_database(db_path)

    first_id = persist_analysis_run(
        game_id="game_1",
        user_question="Why?",
        memo_markdown="First answer",
        packet_ids=["packet_1"],
        db_path=db_path,
    )
    second_id = persist_analysis_run(
        game_id="game_1",
        user_question="Why?",
        memo_markdown="Second answer",
        packet_ids=["packet_1", "packet_2"],
        db_path=db_path,
    )

    con = connect(db_path)
    rows = con.execute(
        "SELECT run_id, packet_ids_json FROM analysis_runs WHERE game_id = ? ORDER BY created_at, run_id",
        ["game_1"],
    ).fetchall()
    con.close()

    assert first_id != second_id
    assert {row[0] for row in rows} == {first_id, second_id}
    assert {tuple(json.loads(row[1])) for row in rows} == {
        ("packet_1",),
        ("packet_1", "packet_2"),
    }


def test_ingestion_job_lifecycle_and_serialization(tmp_path):
    db_path = tmp_path / "jobs.duckdb"
    job = create_ingestion_job("game_1", db_path)

    queued = get_ingestion_job(job["job_id"], db_path)
    assert queued is not None
    assert queued["status"] == "queued"
    assert queued["result"] is None

    result = {"game_id": "game_1", "warnings": ["rotation unavailable"]}
    update_ingestion_job(job["job_id"], "partial", result=result, db_path=db_path)
    partial = get_ingestion_job(job["job_id"], db_path)

    assert partial is not None
    assert partial["status"] == "partial"
    assert partial["result"] == result
    assert partial["error"] is None
    assert partial["updated_at"] >= partial["created_at"]


def test_ingestion_job_rejects_unknown_state_and_returns_none_for_missing_job(tmp_path):
    db_path = tmp_path / "job_validation.duckdb"
    initialize_database(db_path)

    with pytest.raises(ValueError, match="Unknown ingestion job status"):
        update_ingestion_job("missing", "cancelled", db_path=db_path)

    assert get_ingestion_job("missing", db_path) is None

"""The post-game pipeline's state machine, with NBA loading and the harness faked."""

import asyncio
from datetime import date, datetime, timezone

import pytest

from api.nba_agent import pipeline
from api.nba_agent.db import get_storage
from api.nba_agent.storage.pipeline import GamePipelineRepository

DATE = "2026-06-13"
FAN = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "pipeline.duckdb"
    monkeypatch.setattr(pipeline, "get_storage", lambda: get_storage(path))
    storage = get_storage(path)
    storage.initialize()
    run(storage, "INSERT INTO favorite_teams (user_id, team_abbr) VALUES (?, 'TOR')", [FAN])
    for game_id, away, home in (("g_tor", "TOR", "NYK"), ("g_other", "BOS", "MIA")):
        run(storage, """INSERT INTO games (game_id, game_date, season_type, away_team_abbr, home_team_abbr,
                        away_score, home_score, source) VALUES (?, ?, 'Playoffs', ?, ?, 101, 99, 'test')""",
            [game_id, DATE, away, home])
    return storage


def run(storage, query, parameters=()):
    connection = storage.open(read_only=False)
    try:
        connection.execute(query, list(parameters))
    finally:
        connection.close()


def publish_stats(storage, game_id="g_tor", *, home_pts=99, final_pbp=True):
    """Store what the NBA publishes after the game: box scores and play-by-play."""
    for side, abbr, pts in (("away", "TOR", 101), ("home", "NYK", home_pts)):
        run(storage, "INSERT INTO box_scores_team (game_id, team_side, team_abbr, pts) VALUES (?, ?, ?, ?)",
            [game_id, side, abbr, pts])
        run(storage, "INSERT INTO box_scores_player (game_id, player_id, team_abbr) VALUES (?, ?, ?)",
            [game_id, f"p_{abbr}", abbr])
        run(storage, "INSERT INTO box_scores_advanced_team (game_id, team_id, team_abbr) VALUES (?, ?, ?)",
            [game_id, abbr, abbr])
    run(storage, """INSERT INTO play_by_play_events (game_id, eventnum, period, score_home, score_away)
                    VALUES (?, 500, 4, ?, ?)""", [game_id, 99 if final_pbp else 90, 101 if final_pbp else 95])


def fake_harness(stop_reason="supported"):
    calls = []

    async def run_harness(question, game_id, season_type):
        calls.append(game_id)
        return {"stop_reason": stop_reason, "analysis_run_id": f"run_{game_id}_{len(calls)}"}

    return run_harness, calls


def once(**kwargs):
    return asyncio.run(pipeline.run_once([DATE], sync=False, **kwargs))


@pytest.mark.parametrize("eastern, expected", [
    ("2026-01-14T18:59", False),  # Wednesday, before tip-off
    ("2026-01-14T19:00", True),
    ("2026-01-15T01:59", True),   # late West Coast finals
    ("2026-01-15T02:00", False),
    ("2026-01-17T12:00", True),   # Saturday afternoon games
    ("2026-01-17T11:59", False),
])
def test_game_window(eastern, expected):
    moment = datetime.fromisoformat(eastern).replace(tzinfo=pipeline.EASTERN)
    assert pipeline.in_game_window(moment.astimezone(timezone.utc)) is expected


def test_eastern_dates_cover_games_that_end_after_midnight():
    assert pipeline.eastern_dates(date(2026, 6, 14)) == ["2026-06-14", "2026-06-13"]


def test_followed_final_is_loaded_then_analyzed_once(db, monkeypatch):
    harness, calls = fake_harness()
    monkeypatch.setattr(pipeline, "ensure_game_cached", lambda game_id, **_: publish_stats(db, game_id))
    monkeypatch.setattr(pipeline, "run_harness", harness)

    summary = once()
    assert summary["loaded"] == ["g_tor"] and summary["analyzed"] == ["g_tor"]
    state = GamePipelineRepository(db).get("g_tor")
    assert state["status"] == "analyzed" and state["breakdown_run_id"] == "run_g_tor_1"
    assert state["loaded_at"] and state["analyzed_at"]

    assert GamePipelineRepository(db).get("g_other") is None  # nobody follows BOS or MIA
    assert once()["analyzed"] == [] and calls == ["g_tor"]  # repeating a pass does nothing


@pytest.mark.parametrize("stats, reason", [
    ({"home_pts": 90}, "differs from the final"),
    ({"final_pbp": False}, "play-by-play does not reach the final score"),
])
def test_incomplete_stats_wait_for_a_later_pass(db, monkeypatch, stats, reason):
    harness, calls = fake_harness()
    monkeypatch.setattr(pipeline, "ensure_game_cached", lambda game_id, **_: publish_stats(db, game_id, **stats))
    monkeypatch.setattr(pipeline, "run_harness", harness)

    assert once()["waiting"] == ["g_tor"]
    state = GamePipelineRepository(db).get("g_tor")
    assert state["status"] == "pending" and state["attempts"] == 1 and reason in state["last_error"]
    assert calls == []
    assert once()["waiting"] == []  # not due again until the retry delay passes


def test_load_errors_retry_until_the_game_is_marked_failed(db, monkeypatch):
    def unreachable(game_id, **_):
        raise TimeoutError

    monkeypatch.setattr(pipeline, "ensure_game_cached", unreachable)
    monkeypatch.setattr(pipeline, "MAX_LOAD_ATTEMPTS", 2)
    monkeypatch.setattr(pipeline, "RETRY_DELAY", pipeline.timedelta(0))
    once()
    once()
    state = GamePipelineRepository(db).get("g_tor")
    assert state["status"] == "failed" and state["last_error"] == "load failed: TimeoutError"


def test_unsupported_breakdowns_retry_less_than_loading(db, monkeypatch):
    harness, calls = fake_harness("insufficient_evidence")
    publish_stats(db)
    monkeypatch.setattr(pipeline, "run_harness", harness)
    monkeypatch.setattr(pipeline, "RETRY_DELAY", pipeline.timedelta(0))
    for _ in range(4):
        once()
    state = GamePipelineRepository(db).get("g_tor")
    assert state["status"] == "failed" and state["last_error"] == "analysis stopped: insufficient_evidence"
    assert len(calls) == pipeline.MAX_ANALYSIS_ATTEMPTS


def test_analysis_budget_caps_harness_runs_per_pass(db, monkeypatch):
    harness, calls = fake_harness()
    publish_stats(db)
    monkeypatch.setattr(pipeline, "run_harness", harness)
    assert once(max_analyses=0)["loaded"] == ["g_tor"]
    assert calls == [] and GamePipelineRepository(db).get("g_tor")["status"] == "loaded"
    assert once()["analyzed"] == ["g_tor"]

"""The S3 path must reject partial games and preserve atomic, repeatable imports."""
import copy
import os
import uuid
from pathlib import Path

import pytest

from api.nba_agent import s3_ingest, tools
from api.nba_agent.db import get_storage
from api.nba_agent.storage.nba_live import NBALiveRepository
from api.nba_agent.storage.pipeline import GamePipelineRepository

GID = "0022600110"


@pytest.fixture
def feeds():
    def stats(points, duration="PT48M00.00S"):
        d = {key: 0 for key in s3_ingest.STAT_KEYS}
        d.update(points=points, fieldGoalsMade=40, fieldGoalsAttempted=90,
                 threePointersMade=10, threePointersAttempted=30, freeThrowsAttempted=20,
                 reboundsOffensive=10, reboundsDefensive=30, reboundsTotal=40,
                 reboundsPersonal=40, turnoversTotal=12, turnovers=11,
                 minutes=duration)
        return d
    def team(team_id, abbr, points):
        return {"teamId": team_id, "teamTricode": abbr, "teamCity": abbr, "teamName": "Team",
                "score": points, "statistics": stats(points),
                "players": [{"personId": team_id, "name": abbr + " Player", "statistics": stats(points)}]}
    box = {"game": {"gameId": GID, "gameStatus": 3, "gameTimeUTC": "2026-10-25T01:00:00Z", "period": 5,
                    "homeTeam": team(1, "DEN", 141), "awayTeam": team(2, "NOP", 135)}}
    actions = [{"actionNumber": i, "period": i, "clock": "PT00M00.00S", "actionType": "period",
                "subType": "end", "scoreHome": "141", "scoreAway": "135"} for i in range(1, 6)]
    actions.append({**actions[-1], "actionNumber": 6, "actionType": "game", "subType": "end"})
    return box, {"game": {"gameId": GID, "actions": actions}}


@pytest.fixture(params=["duckdb", "postgres"])
def storage(tmp_path, monkeypatch, request):
    if request.param == "duckdb":
        s = get_storage(tmp_path / "s3.duckdb")
        s.initialize()
        yield s
        return
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set explicit disposable POSTGRES_TEST_DATABASE_URL for PostgreSQL S3 tests")
    from sqlalchemy import create_engine, text
    from alembic import command
    from alembic.config import Config
    schema = f"nba_s3_{uuid.uuid4().hex}"
    engine = create_engine(url)
    try:
        with engine.begin() as con:
            con.execute(text(f'CREATE SCHEMA "{schema}"'))
            con.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = con
            command.upgrade(config, "head")
        monkeypatch.setenv("NBA_STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("POSTGRES_CONNECTION_STRING", url)
        monkeypatch.setenv("NBA_POSTGRES_SCHEMA", schema)
        s = get_storage()
        s.initialize()
        yield s
    finally:
        with engine.begin() as con:
            con.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def read(storage, sql, params=()):
    c = storage.open()
    try:
        return c.execute(sql, list(params)).fetchall()
    finally:
        c.close()


def save(storage, feeds):
    box, pbp = feeds
    record, teams, players, events = s3_ingest.parse_bundle(GID, box, pbp)
    NBALiveRepository(storage).save_bundle(record, teams, players, events, box, pbp)


def test_overtime_import_is_repeatable_and_analysis_uses_labeled_estimates(storage, feeds, monkeypatch):
    save(storage, feeds)
    save(storage, feeds)
    assert read(storage, "SELECT COUNT(*) FROM box_scores_team") == [(2,)]
    assert read(storage, "SELECT COUNT(*) FROM play_by_play_events") == [(6,)]
    assert str(read(storage, "SELECT game_date FROM games")[0][0])[:10] == "2026-10-24"
    assert read(storage, "SELECT tov FROM box_scores_team ORDER BY team_side") == [(12,), (12,)]
    assert read(storage, "SELECT COUNT(*) FROM box_scores_advanced_team") == [(0,)]
    assert GamePipelineRepository(storage).missing_stats(GID) is None
    monkeypatch.setenv("NBA_DATA_SOURCE", "s3")
    monkeypatch.setattr(tools, "import_s3_game_bundle", lambda **_: pytest.fail("complete cache must not refetch"))
    result = tools.ensure_game_cached(GID, storage.path)
    assert not result["ingested"] and result["warnings"]
    context = tools.get_advanced_game_context(GID, storage.path)
    assert context["summary"]["advanced_context_source"] == "local_fallback"
    assert context["evidence_packets"][0]["evidence_level"] == "fallback_advanced"
    assert "offensive_rating" not in context["team_metrics"]["DEN"]
    assert tools.get_cached_games_status(storage.path)["games"][0]["complete"]


@pytest.mark.parametrize("damage", ["not_final", "wrong_id", "player_points", "missing_stat", "no_game_end", "wrong_final", "missing_period", "duplicate"])
def test_incomplete_or_mismatched_feed_never_replaces_stored_data(storage, feeds, damage):
    save(storage, feeds)
    box, pbp = copy.deepcopy(feeds)
    if damage == "not_final": box["game"]["gameStatus"] = 2
    if damage == "wrong_id": pbp["game"]["gameId"] = "0022600111"
    if damage == "player_points": box["game"]["homeTeam"]["players"][0]["statistics"]["points"] = 0
    if damage == "missing_stat": del box["game"]["homeTeam"]["statistics"]["fieldGoalsAttempted"]
    if damage == "no_game_end": pbp["game"]["actions"].pop()
    if damage == "wrong_final": pbp["game"]["actions"][-1]["scoreHome"] = "140"
    if damage == "missing_period": pbp["game"]["actions"].pop(0)
    if damage == "duplicate": pbp["game"]["actions"].insert(0, pbp["game"]["actions"][0])
    with pytest.raises((ValueError, KeyError)):
        save(storage, (box, pbp))
    assert read(storage, "SELECT home_score FROM games") == [(141,)]
    assert read(storage, "SELECT COUNT(*) FROM play_by_play_events") == [(6,)]


def test_write_failure_rolls_back_deletes_and_updates(storage, feeds):
    save(storage, feeds)
    record, teams, players, events = s3_ingest.parse_bundle(GID, *feeds)
    players.append(players[0])  # primary-key failure after previous rows were replaced
    with pytest.raises(Exception):
        NBALiveRepository(storage).save_bundle(record, teams, players, events, *feeds)
    assert read(storage, "SELECT COUNT(*) FROM box_scores_player") == [(2,)]
    assert read(storage, "SELECT COUNT(*) FROM play_by_play_events") == [(6,)]
    assert read(storage, "SELECT COUNT(*) FROM raw_responses") == [(2,)]


def test_schedule_skips_live_games_and_checks_season(feeds):
    game = feeds[0]["game"]
    live = {**game, "gameId": "0022600111", "gameStatus": 2}
    schedule = {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [
        {"gameDate": "10/24/2026 00:00:00", "games": [game, live]}]}}
    games = s3_ingest.schedule_results(schedule, "2026-27")
    assert [g["game_id"] for g in games] == [GID]
    with pytest.raises(ValueError, match="season"):
        s3_ingest.schedule_results(schedule, "2025-26")


def test_schedule_refresh_does_not_downgrade_completed_bundle(storage, feeds):
    save(storage, feeds)
    record = s3_ingest.parse_bundle(GID, *feeds)[0]
    record.update(source="nba_s3:results", home_score=0)
    NBALiveRepository(storage).save_results([record], {})
    assert read(storage, "SELECT home_score, source FROM games") == [(141, "nba_s3:liveData")]


def test_stats_mode_still_requires_official_advanced_rows(storage, feeds):
    save(storage, feeds)
    c = storage.open(read_only=False)
    try:
        c.execute("UPDATE games SET source = 'nba_api:LeagueGameLog'")
    finally:
        c.close()
    assert GamePipelineRepository(storage).missing_stats(GID) == "advanced box score missing"


def test_s3_can_repair_a_stranded_partial_official_import(storage, feeds):
    record, teams, players, events = s3_ingest.parse_bundle(GID, *feeds)
    record["source"] = "nba_api:LeagueGameLog"
    NBALiveRepository(storage).save_results([record], {})
    save(storage, feeds)
    assert GamePipelineRepository(storage).missing_stats(GID) is None
    assert read(storage, "SELECT source FROM games") == [("nba_s3:liveData",)]


def test_s3_preserves_a_complete_official_bundle(storage, feeds):
    save(storage, feeds)
    c = storage.open(read_only=False)
    try:
        c.execute("UPDATE games SET source = 'nba_api:LeagueGameLog'")
        for team_id, abbr in [(1, "DEN"), (2, "NOP")]:
            c.execute("INSERT INTO box_scores_advanced_team (game_id, team_id, team_abbr) VALUES (?, ?, ?)",
                      [GID, str(team_id), abbr])
    finally:
        c.close()
    save(storage, feeds)
    assert read(storage, "SELECT source FROM games") == [("nba_api:LeagueGameLog",)]
    assert read(storage, "SELECT COUNT(*) FROM raw_responses") == [(2,)]

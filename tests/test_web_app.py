from fastapi.testclient import TestClient

from api.app import app


client = TestClient(app)


def test_api_root_has_no_frontend():
    response = client.get("/")
    assert response.status_code == 404


def test_db_status_endpoint_shape():
    response = client.get("/api/db-status?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "games" in payload
    if payload["games"]:
        game = payload["games"][0]
        assert {"game_id", "team_rows", "advanced_rows", "player_rows", "pbp_rows"}.issubset(game)


def test_recent_games_auto_endpoint_shape():
    response = client.get("/api/recent-games?season_type=Auto&limit=4")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "games" in payload
    assert payload["summary"]["requested_season_type"] == "Auto"


def test_openai_config_endpoint_shape():
    response = client.get("/api/openai-agent/config")
    assert response.status_code == 200
    payload = response.json()
    assert {"mode", "model", "has_api_key", "has_agents_sdk", "has_openai_sdk"}.issubset(payload)


def test_ask_endpoint_cached_game_shape():
    response = client.post(
        "/api/ask",
        json={
            "question": "who swung the Knicks Cavs game",
            "mode": "deterministic",
            "game_id": "0042500303",
            "max_evidence": 2,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "players"
    assert payload["persisted"] is False
    assert payload["answer_markdown"].startswith("# NYK 121, CLE 108")
    assert payload["evidence"]


def test_openai_mode_without_key_returns_400(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        "/api/ask",
        json={
            "question": "advanced stats for Knicks Cavs",
            "game_id": "0042500303",
            "mode": "local_agents_sdk_mcp",
        },
    )
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_game_flow_tracks_margin_through_overtime(tmp_path, monkeypatch):
    from api.nba_agent.db import get_storage, initialize_database
    from api.nba_agent.tools import game_elapsed_minutes, get_game_flow

    path = tmp_path / "flow.duckdb"
    initialize_database(path)
    con = get_storage(path).open(read_only=False)
    try:
        con.execute("INSERT INTO games (game_id, home_team_abbr, away_team_abbr, home_score, away_score, source) "
                    "VALUES ('g1', 'HOM', 'AWY', 105, 103, 'fixture')")
        rows = [(1, 1, "11:30", 2, 0), (2, 1, "11:30", 2, 0), (3, 4, "0:04", 98, 98),
                (4, 5, "2:30", 101, 103), (5, 5, "0:00", 103, 105), (6, 2, "5:00", None, None)]
        for eventnum, period, clock, away, home in rows:
            con.execute("INSERT INTO play_by_play_events (game_id, eventnum, period, pctimestring, score_away, score_home) "
                        "VALUES ('g1', ?, ?, ?, ?, ?)", [eventnum, period, clock, away, home])
    finally:
        con.close()

    assert game_elapsed_minutes(1, "12:00") == 0
    assert game_elapsed_minutes(5, "2:30") == 50.5
    flow = get_game_flow("g1", path)
    assert flow["status"] == "ok"
    assert flow["periods"] == 5 and flow["length_minutes"] == 53
    # Unchanged scores and events without a score are not new points.
    assert [(p["minute"], p["margin"]) for p in flow["points"]] == [(0, 0), (0.5, 2), (47.933, 0), (50.5, -2), (53, -2)]

    monkeypatch.setattr("api.routes.get_game_flow", lambda game_id: get_game_flow(game_id, path))
    assert client.get("/api/games/g1/flow").json()["points"] == flow["points"]
    assert client.get("/api/games/missing/flow").status_code == 404


def test_run_detail_lists_the_plays_inside_the_window(tmp_path):
    from api.nba_agent.db import get_storage, initialize_database
    from api.nba_agent.tools import persist_evidence_packets, rehydrate_evidence_packet

    path = tmp_path / "plays.duckdb"
    initialize_database(path)
    con = get_storage(path).open(read_only=False)
    try:
        con.execute("INSERT INTO games (game_id, home_team_abbr, away_team_abbr, home_score, away_score, source) "
                    "VALUES ('g1', 'SAS', 'NYK', 90, 94, 'fixture')")
        rows = [(9, 4, "8:30", None, "Brunson 3PT Jump Shot", 76, 83), (10, 4, "8:30", "Wembanyama REBOUND", None, None, None),
                (11, 4, "8:10", None, "Hart Layup", 78, 83), (12, 4, "7:50", "Fox Bad Pass Turnover", None, None, None),
                (13, 4, "7:30", None, None, None, None), (14, 4, "7:10", None, "Bridges Jump Shot", 80, 83)]
        for eventnum, period, clock, home, away, score_away, score_home in rows:
            con.execute("INSERT INTO play_by_play_events (game_id, eventnum, period, pctimestring, homedescription, "
                        "visitordescription, score_away, score_home) VALUES ('g1', ?, ?, ?, ?, ?, ?, ?)",
                        [eventnum, period, clock, home, away, score_away, score_home])
    finally:
        con.close()
    packet = {"packet_id": "run_g1_1_9_14", "type": "run_candidate", "claim_seed": "NYK run.", "confidence": "medium",
              "source": {"provider": "fixture"}, "window": {"start_eventnum": 9, "end_eventnum": 14}}
    assert persist_evidence_packets("g1", [packet], path)

    # A stored run packet still returns its plays (previously only unstored packets did).
    detail = rehydrate_evidence_packet("run_g1_1_9_14", "g1", path)
    assert detail["packet"]["packet_id"] == "run_g1_1_9_14"
    assert detail["summary"]["play_count"] == 5 and detail["summary"]["scoring_play_count"] == 3
    assert [(p["team"], p["description"], p["scoring"]) for p in detail["plays"]] == [
        ("NYK", "Brunson 3PT Jump Shot", True), ("SAS", "Wembanyama REBOUND", False), ("NYK", "Hart Layup", True),
        ("SAS", "Fox Bad Pass Turnover", False), ("NYK", "Bridges Jump Shot", True)]
    assert detail["plays"][2]["score"] == "NYK 78, SAS 83"


def seed_close_game(path):
    """AWY at HOM: HOM leads by 5 after three, AWY wins in overtime."""
    from api.nba_agent.db import get_storage, initialize_database

    initialize_database(path)
    con = get_storage(path).open(read_only=False)
    rows = [
        # eventnum, type, period, clock, home text, away text, away, home, player, team
        (1, 1, 1, "11:40", None, "Ace 3PT Jump Shot", 3, 0, "Ace", "AWY"),
        (2, 1, 2, "6:00", "Hal Layup", None, 3, 2, "Hal", "HOM"),
        (3, 1, 3, "2:00", "Hal 3PT Jump Shot", None, 3, 5, "Hal", "HOM"),
        (4, 1, 3, "1:00", "Hal Dunk", None, 3, 7, "Hal", "HOM"),
        (5, 2, 4, "8:00", None, "MISS Ace 3PT Jump Shot", None, None, "Ace", "AWY"),
        (6, 1, 4, "7:30", None, "Ace Layup", 5, 7, "Ace", "AWY"),
        (7, 3, 4, "7:30", None, "Ace Free Throw 1 of 1", 6, 7, "Ace", "AWY"),
        (8, 5, 4, "7:00", "Hal Bad Pass Turnover", None, None, None, "Hal", "HOM"),
        (9, 1, 4, "6:00", None, "Bo Jump Shot", 8, 7, "Bo", "AWY"),
        (10, 1, 4, "0:10", "Hal Layup", None, 8, 9, "Hal", "HOM"),
        (11, 3, 4, "0:01", None, "MISS Ace Free Throw 1 of 2", None, None, "Ace", "AWY"),
        (12, 3, 4, "0:01", None, "Ace Free Throw 2 of 2", 9, 9, "Ace", "AWY"),
        (13, 1, 5, "2:30", None, "Bo 3PT Jump Shot", 12, 9, "Bo", "AWY"),
    ]
    try:
        con.execute("INSERT INTO games (game_id, home_team_abbr, away_team_abbr, home_score, away_score, source) "
                    "VALUES ('g1', 'HOM', 'AWY', 9, 12, 'fixture')")
        for eventnum, kind, period, clock, home, away, score_away, score_home, player, team in rows:
            con.execute("INSERT INTO play_by_play_events (game_id, eventnum, eventmsgtype, period, pctimestring, homedescription, "
                        "visitordescription, score_away, score_home, player1_name, player1_team_abbreviation, source) "
                        "VALUES ('g1', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'nba_api:PlayByPlayV3')",
                        [eventnum, kind, period, clock, home, away, score_away, score_home, player, team])
    finally:
        con.close()


def test_period_summary_reports_quarters_leads_and_changes(tmp_path):
    from api.nba_agent.tools import get_period_summary

    seed_close_game(tmp_path / "close.duckdb")
    [packet] = get_period_summary("g1", tmp_path / "close.duckdb")["evidence_packets"]
    metrics = packet["metrics"]
    assert packet["type"] == "period_summary" and packet["confidence"] == "high"
    assert [(p["label"], p["AWY_points"], p["HOM_points"], p["leader_at_end"]) for p in metrics["periods"]] == [
        ("Q1", 3, 0, "AWY"), ("Q2", 0, 2, "AWY"), ("Q3", 0, 5, "HOM"), ("Q4", 6, 2, "tied"), ("OT", 3, 0, "AWY")]
    assert metrics["largest_lead"]["HOM"] == {"points": 4, "period": "Q3", "clock": "1:00", "score": "AWY 3, HOM 7"}
    assert metrics["largest_lead"]["AWY"]["points"] == 3
    # AWY -> HOM (Q3) -> AWY (Q4 6:00) -> HOM (0:10) -> tie -> AWY (OT)
    assert metrics["lead_changes"] == 4 and metrics["ties"] == 1
    assert "HOM led by as many as 4 (Q3 1:00)" in packet["claim_seed"]


def test_game_window_reports_the_stretch_and_its_players(tmp_path):
    from api.nba_agent.tools import get_game_window

    seed_close_game(tmp_path / "close.duckdb")
    result = get_game_window("g1", 4, "8:00", "6:00", db_path=tmp_path / "close.duckdb")
    [packet] = result["evidence_packets"]
    metrics = packet["metrics"]
    assert packet["type"] == "game_window"
    assert metrics["score_before"] == "AWY 3, HOM 7" and metrics["score_after"] == "AWY 8, HOM 7"
    assert metrics["team_points"] == {"AWY": 5, "HOM": 0}
    assert packet["claim_seed"] == "From Q4 8:00 to Q4 6:00, AWY outscored HOM 5-0 (AWY 3, HOM 7 to AWY 8, HOM 7)."
    ace = next(p for p in metrics["players"] if p["player"] == "Ace")
    assert (ace["pts"], ace["fgm"], ace["fga"], ace["fg3a"], ace["ftm"], ace["fta"]) == (3, 1, 2, 1, 1, 1)
    assert metrics["team_stats"]["HOM"]["tov"] == 1
    assert [p["description"] for p in packet["plays"]][0] == "MISS Ace 3PT Jump Shot"

    overtime = get_game_window("g1", 4, "0:10", end_period=5, db_path=tmp_path / "close.duckdb")["evidence_packets"][0]
    assert overtime["metrics"]["team_points"] == {"AWY": 4, "HOM": 2}
    assert overtime["window"] == {"period_start": 4, "clock_start": "0:10", "period_end": 5, "clock_end": "0:00"}

    empty = get_game_window("g1", 2, "11:00", "10:00", db_path=tmp_path / "close.duckdb")["evidence_packets"][0]
    assert empty["confidence"] == "low" and empty["metrics"]["team_points"] == {"AWY": 0, "HOM": 0}
    assert get_game_window("g1", 4, "2:00", "5:00", db_path=tmp_path / "close.duckdb")["summary"]["resolution_status"] == "invalid_window"

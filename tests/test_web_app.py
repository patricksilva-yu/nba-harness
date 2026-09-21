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

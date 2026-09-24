"""Supabase access tokens, verified against a local ES256 key in place of the project's JWKS."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from fastmcp import Client

from api import auth
from api.app import app
from api.nba_agent.db import get_storage
from api.nba_agent.harness import run_harness
from tests.test_harness import ScriptedModel, answer, preparation, review, server, sse_events


SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())
ALICE, BOB, ADMIN = (str(uuid.uuid4()) for _ in range(3))


def token(sub, *, key=KEY, aud="authenticated", iss=ISSUER, expires_in=3600):
    claims = {"sub": sub, "aud": aud, "iss": iss, "exp": int(time.time()) + expires_in, "role": "authenticated"}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test"})


def bearer(sub, **kwargs):
    return {"Authorization": f"Bearer {token(sub, **kwargs)}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_AUTH_MODE", "supabase")
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL + "/")
    monkeypatch.setenv("NBA_ADMIN_USER_IDS", f" {ADMIN} ,")
    monkeypatch.setattr(auth, "signing_key", lambda _token, issuer: KEY.public_key())
    path = tmp_path / "auth.duckdb"

    async def configured(**kwargs):
        return await run_harness(**kwargs, db_path=path, mcp_client=Client(server()))

    monkeypatch.setattr("api.routes.run_harness", configured)
    monkeypatch.setattr("api.routes.ResponsesModel", lambda: ScriptedModel([*preparation(), answer(), review()]))
    monkeypatch.setattr("api.routes.get_storage", lambda: get_storage(path))
    get_storage(path).initialize()
    return TestClient(app)


def ask(client, headers=None, **body):
    response = client.post("/api/ask/stream", json={"question": "Who won?", "game_id": "g1", **body}, headers=headers)
    return response.status_code, sse_events(response.text)[-1][1] if response.status_code == 200 else response.json()


def test_valid_token_identifies_the_user(client):
    assert client.get("/api/me", headers=bearer(ALICE)).json() == {"user_id": ALICE, "is_admin": False}
    assert client.get("/api/me", headers=bearer(ADMIN)).json()["is_admin"] is True


@pytest.mark.parametrize("headers", [
    None,
    {"Authorization": "Basic abc"},
    {"Authorization": "Bearer "},
])
def test_missing_token_needs_sign_in(client, headers):
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("bad", [
    {"expires_in": -60},
    {"aud": "anon"},
    {"iss": "https://other.supabase.co/auth/v1"},
    {"key": ec.generate_private_key(ec.SECP256R1())},
])
def test_invalid_tokens_are_rejected(client, bad):
    assert client.get("/api/me", headers=bearer(ALICE, **bad)).status_code == 401


def test_symmetric_tokens_are_rejected(client):
    forged = jwt.encode({"sub": ALICE, "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
                        "secret-at-least-32-bytes-long-for-hmac", algorithm="HS256")
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_missing_supabase_url_fails_closed(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    assert client.get("/api/me", headers=bearer(ALICE)).status_code == 503


def test_operator_routes_need_an_admin(client):
    for path in ("/api/traces", "/api/db-status", "/api/ingestion-jobs/x"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=bearer(ALICE)).status_code == 403, path
    ask(client, bearer(ALICE))
    assert client.get("/api/traces", headers=bearer(ADMIN)).json()["total"] == 1
    assert client.post("/api/ingestion-jobs", json={"game_id": "g1"}, headers=bearer(ALICE)).status_code == 403


def test_public_data_stays_open(client, monkeypatch):
    monkeypatch.setattr("api.routes.find_recent_completed_games_for_resolution", lambda **_: {"games": []})
    assert client.get("/api/recent-games").status_code == 200


def test_favorite_teams_are_account_scoped_and_idempotent(client):
    path = "/api/me/favorite-teams"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=bearer(ALICE)).json() == {"teams": []}
    assert client.post(path, json={"team_abbr": "tor"}, headers=bearer(ALICE)).status_code == 201
    assert client.post(path, json={"team_abbr": "TOR"}, headers=bearer(ALICE)).status_code == 201
    assert client.get(path, headers=bearer(ALICE)).json() == {"teams": ["TOR"]}
    assert client.get(path, headers=bearer(BOB)).json() == {"teams": []}
    assert client.post(path, json={"team_abbr": "INVALID"}, headers=bearer(ALICE)).status_code == 422
    assert client.delete(path + "/TOR", headers=bearer(BOB)).status_code == 204
    assert client.get(path, headers=bearer(ALICE)).json() == {"teams": ["TOR"]}
    assert client.delete(path + "/TOR", headers=bearer(ALICE)).status_code == 204
    assert client.get(path, headers=bearer(ALICE)).json() == {"teams": []}


def test_home_games_only_include_followed_teams(client):
    from api import routes

    storage = routes.get_storage()
    storage.initialize()
    connection = storage.open(read_only=False)
    try:
        connection.execute(
            """INSERT INTO games (game_id, game_date, away_team_abbr, away_score, home_team_abbr, home_score)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ["raptors_game", "2026-04-01", "TOR", 108, "BOS", 102],
        )
        connection.execute(
            """INSERT INTO games (game_id, game_date, away_team_abbr, away_score, home_team_abbr, home_score)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ["other_game", "2026-04-02", "LAL", 110, "GSW", 105],
        )
    finally:
        connection.close()
    client.post("/api/me/favorite-teams", json={"team_abbr": "TOR"}, headers=bearer(ALICE))
    assert [g["game_id"] for g in client.get("/api/me/favorite-games", headers=bearer(ALICE)).json()["games"]] == ["raptors_game"]
    assert client.get("/api/me/favorite-games", headers=bearer(BOB)).json() == {"games": []}


def test_history_belongs_to_the_asker(client):
    status, alice_run = ask(client, bearer(ALICE))
    assert status == 200 and alice_run["stop_reason"] == "supported"
    conversation_id, run_id = alice_run["conversation_id"], alice_run["analysis_run_id"]

    listed = client.get("/api/conversations", headers=bearer(ALICE)).json()["conversations"]
    assert [c["conversation_id"] for c in listed] == [conversation_id]
    assert client.get(f"/api/conversations/{conversation_id}", headers=bearer(ALICE)).status_code == 200
    assert client.get(f"/api/runs/{run_id}", headers=bearer(ALICE)).json()["user_id"] == ALICE

    assert client.get("/api/conversations", headers=bearer(BOB)).json()["conversations"] == []
    assert client.get(f"/api/conversations/{conversation_id}", headers=bearer(BOB)).status_code == 404
    assert client.get(f"/api/runs/{run_id}", headers=bearer(BOB)).status_code == 404
    assert client.get(f"/api/runs/{run_id}", headers=bearer(ADMIN)).status_code == 200
    assert client.get("/api/conversations").status_code == 401


def test_follow_ups_continue_only_as_the_same_user(client):
    _, alice_run = ask(client, bearer(ALICE))
    follow = {"question": "Who scored most?", "parent_run_id": alice_run["analysis_run_id"]}
    assert client.post("/api/ask/stream", json=follow, headers=bearer(BOB)).status_code == 404
    status, second = ask(client, bearer(ALICE), **follow)
    assert status == 200 and second["parent_run_id"] == alice_run["analysis_run_id"]


def test_asking_needs_sign_in(client):
    assert ask(client)[0] == 401
    assert client.post("/api/ask", json={"question": "Who won?", "game_id": "g1"}).status_code == 401

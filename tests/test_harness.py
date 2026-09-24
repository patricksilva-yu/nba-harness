"""Behavior tests use the actual MCP protocol with deterministic model decisions."""

import asyncio
import json
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from api.app import app
from api.nba_agent.db import get_storage, initialize_database
from api.nba_agent.harness import FollowUpError, follow_up_context, run_harness
from api.nba_agent.harness.contracts import Limits
from api.nba_agent.harness.controller import clean
from api.nba_agent.harness.mcp_client import MCPBoundary
from api.nba_agent.storage.repositories import HarnessRunRepository


PACKET = {"packet_id": "p1", "type": "game_snapshot", "claim_seed": "AWY defeated HOM 101-100.",
          "source": {"provider": "fixture"}, "confidence": "high", "metrics": {"away_score": 101, "home_score": 100}}


def call(name, **arguments):
    return {"id": "response", "status": "completed", "text": "", "usage": {"input_tokens": 100, "output_tokens": 50},
            "items": [{"type": "function_call", "name": name, "arguments": json.dumps(arguments), "call_id": name}]}


def output(value):
    return {"id": "response", "status": "completed", "items": [], "text": json.dumps(value),
            "usage": {"input_tokens": 100, "output_tokens": 50}}


def claim(text="AWY defeated HOM 101-100.", packet="p1", follow_up=None):
    return {"text": text, "packet_ids": [packet], "follow_up": follow_up}


def answer(text="AWY defeated HOM 101-100.", packet="p1", headline="AWY edged HOM by one.", claims=None):
    return output({"headline": claim(headline, packet) if headline else None,
                   "claims": claims or [claim(text, packet)], "limitations": []})


def finding(index, classification="supported", need="", follow_up_ok=True):
    return {"claim_index": index, "classification": classification,
            "reason": "Checked score against the cited snapshot.", "evidence_need": need, "follow_up_ok": follow_up_ok}


def review(classification="supported", need="", headline="supported"):
    """Findings for one claim (index 0) and the headline (index 1)."""
    return output({"findings": [finding(0, classification, need), finding(1, headline)]})


class ScriptedModel:
    name = "test-model"

    def __init__(self, steps):
        self.steps = iter(steps)
        self.requests = []

    async def respond(self, history, tools, **kwargs):
        self.requests.append(deepcopy({"history": history, "tools": tools, **kwargs}))
        step = next(self.steps)
        if isinstance(step, Exception):
            raise step
        return deepcopy(step)

    async def close(self):
        self.closed = True


def preparation():
    return [call("resolve_game", query="Who won?", game_id="g1"),
            call("ensure_game_data", game_id="g1"),
            call("get_game_analysis_context", game_id="g1", sections=["snapshot"])]


def server(*, packet=None, wrong_game=False, unresolved=False):
    mcp = FastMCP("test-nba")

    @mcp.tool()
    def resolve_game(query: str, game_id: str | None = None) -> dict:
        return {"summary": {} if unresolved else {"game_id": game_id or "g1"}}

    @mcp.tool()
    def ensure_game_data(game_id: str) -> dict:
        return {"summary": {"game_id": game_id, "cache_status": "already_cached"}}

    @mcp.tool()
    def get_game_analysis_context(game_id: str, sections: list[str]) -> dict:
        return {"summary": {"game_id": "other" if wrong_game else game_id},
                "evidence_packets": [deepcopy(PACKET if packet is None else packet)]}

    @mcp.tool()
    def get_game_window(game_id: str, period: int, from_clock: str | None = None, to_clock: str = "0:00",
                        end_period: int | None = None) -> dict:
        return {"summary": {"game_id": game_id}, "evidence_packets": [{
            "packet_id": f"window_{period}", "type": "game_window", "claim_seed": "AWY outscored HOM 9-2.",
            "source": {"provider": "fixture"}, "confidence": "high", "metrics": {"team_points": {"AWY": 9, "HOM": 2}}}]}

    @mcp.tool()
    def get_evidence_detail(packet_id: str, game_id: str) -> dict:
        return {"summary": {"game_id": game_id, "packet_id": packet_id}, "detail": "AWY scored 101."}

    @mcp.tool()
    def dangerous_unapproved_tool() -> dict:
        raise AssertionError("Must never execute")

    return mcp


def run(tmp_path, steps, *, config="investigation", limits=None, mcp=None):
    return asyncio.run(run_harness("Who won?", game_id="g1", configuration=config,
        db_path=tmp_path / "trace.duckdb", limits=limits, model=ScriptedModel(steps),
        mcp_client=Client(mcp or server())))


def test_success_persists_complete_ordered_trace(tmp_path):
    result = run(tmp_path, [*preparation(), answer(), review()])
    assert result["stop_reason"] == "supported"
    assert result["usage"]["tool_calls"] == 3
    assert result["usage"]["input_tokens"] == 500
    stored = HarnessRunRepository(get_storage(tmp_path / "trace.duckdb")).get(result["analysis_run_id"])
    assert stored == result["trace"]
    assert [e["sequence"] for e in stored["events"]] == list(range(1, len(stored["events"]) + 1))
    assert stored["events"][-1]["kind"] == "run_stopped"
    assert stored["evidence"]["p1"]["tool"] == "get_game_analysis_context"
    discovered = next(e for e in stored["events"] if e["kind"] == "mcp_discovered")
    assert "dangerous_unapproved_tool" not in str(discovered)
    with pytest.raises(RuntimeError, match="already terminal"):
        HarnessRunRepository(get_storage(tmp_path / "trace.duckdb")).save(stored)


def test_basic_is_explicitly_unverified(tmp_path):
    result = run(tmp_path, [*preparation(), answer()], config="basic")
    assert result["stop_reason"] == "answered_unverified"
    assert result["usage"]["verification_passes"] == 0


def test_verification_repairs_bad_claim(tmp_path):
    result = run(tmp_path, [*preparation(), answer("AWY scored 999."), review("unsupported"), answer(), review()], config="verification")
    assert result["stop_reason"] == "supported"
    assert "999" not in result["answer_markdown"]
    assert len(result["trace"]["drafts"]) == 2
    assert result["trace"]["reviews"][0]["findings"][0]["classification"] == "unsupported"


def test_revision_reuses_ledger_without_replaying_tool_transcripts(tmp_path):
    model = ScriptedModel([*preparation(), answer("AWY scored 999."), review("unsupported"), answer(), review()])
    result = asyncio.run(run_harness("Who won?", game_id="g1", configuration="verification",
                                     db_path=tmp_path / "trace.duckdb", model=model,
                                     mcp_client=Client(server())))

    assert result["stop_reason"] == "supported"
    revision_history = model.requests[5]["history"]
    assert len(revision_history) == 1
    context = json.loads(revision_history[0]["content"])
    assert context["evidence_ledger"]["p1"]["packet"]["metrics"]["away_score"] == 101
    assert context["harness_feedback"]["review"]["findings"][0]["classification"] == "unsupported"


def test_investigation_gathers_mcp_detail_then_reverifies(tmp_path):
    result = run(tmp_path, [*preparation(), answer(), review("insufficient", "Check the underlying score."),
        call("get_evidence_detail", game_id="g1", packet_id="p1"), answer(), review()])
    assert result["stop_reason"] == "supported"
    assert result["usage"]["investigation_passes"] == 1
    assert result["usage"]["verification_passes"] == 2
    assert "detail" in result["trace"]["evidence"]["p1"]


@pytest.mark.parametrize("bad_call", [call("dangerous_unapproved_tool"), call("get_game_analysis_context", game_id="wrong", sections=["snapshot"]),
                                     call("resolve_game", query=123), call("resolve_game", query="test", game_id="g1", injected=True)])
def test_invalid_calls_never_cross_mcp(tmp_path, bad_call):
    result = run(tmp_path, [bad_call] * 3)
    assert result["stop_reason"] == "no_progress"
    assert result["usage"]["tool_calls"] == 0


def test_duplicate_calls_stop_without_reexecution(tmp_path):
    result = run(tmp_path, [*preparation(), preparation()[-1], preparation()[-1], preparation()[-1]])
    assert result["stop_reason"] == "no_progress"
    assert result["usage"]["tool_calls"] == 3


def test_fabricated_citations_fail_closed(tmp_path):
    result = run(tmp_path, [*preparation(), *[answer(packet="invented")] * 3])
    assert result["stop_reason"] == "no_progress"
    assert not result["analysis"]["claims"]


def test_wrong_game_result_is_not_evidence(tmp_path):
    result = run(tmp_path, [*preparation(), answer(), answer()], mcp=server(wrong_game=True))
    assert result["stop_reason"] == "no_progress"
    assert result["trace"]["evidence"] == {}


@pytest.mark.parametrize("limits,reason", [(Limits(tool_calls=1), "tool_limit"),
    (Limits(model_turns=1), "iteration_limit"), (Limits(total_tokens=1), "token_limit"),
    (Limits(max_cost_usd=.000001, input_usd_per_million=1, output_usd_per_million=1), "cost_limit"),
    (Limits(verification_passes=0), "verification_limit")])
def test_budgets_are_enforced(tmp_path, limits, reason):
    result = run(tmp_path, [*preparation(), answer(), review()], limits=limits)
    assert result["stop_reason"] == reason
    assert result["trace"]["events"][-1]["reason"] == reason
    assert not result["analysis"]["claims"]


def test_large_evidence_uses_token_estimate_not_byte_count(tmp_path):
    packet = {**PACKET, "claim_seed": "x" * 45_000}
    result = run(tmp_path, [*preparation(), answer(), review()],
                 limits=Limits(total_tokens=50_000), mcp=server(packet=packet))
    assert result["stop_reason"] == "supported"


def test_streaming_model_gets_openai_trace_when_supplied_by_route(tmp_path, monkeypatch):
    from api.nba_agent.harness import controller

    class ProvidedResponsesModel(ScriptedModel):
        pass

    traces = []
    spans = []

    @contextmanager
    def fake_trace(name, **kwargs):
        traces.append((name, kwargs))
        yield

    @contextmanager
    def fake_span(name, data):
        spans.append(name)
        yield SimpleNamespace(span_data=SimpleNamespace(data=data))

    monkeypatch.setattr(controller, "ResponsesModel", ProvidedResponsesModel)
    monkeypatch.setattr(controller, "gen_trace_id", lambda: "trace_" + "1" * 32)
    monkeypatch.setattr(controller, "trace", fake_trace)
    monkeypatch.setattr(controller, "custom_span", fake_span)
    result = asyncio.run(run_harness("Who won?", game_id="g1", db_path=tmp_path / "trace.duckdb",
                                     model=ProvidedResponsesModel([*preparation(), answer(), review()]),
                                     mcp_client=Client(server())))

    assert result["openai_trace_id"] == "trace_" + "1" * 32
    assert traces[0][1]["metadata"]["run_id"] == result["analysis_run_id"]
    assert "MCP get_game_analysis_context" in spans
    assert "Verify claims" in spans
    assert "Run outcome" in spans


def test_unresolved_game_persists_failure_without_model_guess(tmp_path):
    result = run(tmp_path, preparation(), mcp=server(unresolved=True))
    assert result["stop_reason"] == "insufficient_evidence"
    assert result["usage"]["tool_calls"] == 1


def test_model_timeout_is_bounded_and_not_replayed(tmp_path):
    result = run(tmp_path, [TimeoutError("secret exception")])
    assert result["stop_reason"] == "time_limit"
    assert "secret exception" not in str(result)
    assert result["usage"]["model_turns"] == 1


def test_redaction_preserves_token_accounting(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "a-private-value")
    assert clean({"input_tokens": 10, "api_key": "abc", "text": "a-private-value"}) == {
        "input_tokens": 10, "api_key": "[REDACTED]", "text": "[REDACTED]"}


def seed_cached_game(path):
    initialize_database(path)
    con = get_storage(path).open(read_only=False)
    try:
        con.execute("INSERT INTO games (game_id, home_team_abbr, away_team_abbr, home_score, away_score, source) VALUES (?, ?, ?, ?, ?, ?)",
                    ["g1", "HOM", "AWY", 100, 101, "fixture"])
        for side in ("home", "away"):
            con.execute("INSERT INTO box_scores_team (game_id, team_side) VALUES (?, ?)", ["g1", side])
            con.execute("INSERT INTO box_scores_advanced_team (game_id, team_id) VALUES (?, ?)", ["g1", side])
        con.execute("INSERT INTO box_scores_player (game_id, player_id) VALUES (?, ?)", ["g1", "player"])
        con.execute("INSERT INTO play_by_play_events (game_id, eventnum) VALUES (?, ?)", ["g1", 1])
    finally:
        con.close()


def test_fastapi_real_stdio_mcp_to_storage(tmp_path, monkeypatch):
    path = tmp_path / "stdio.duckdb"
    seed_cached_game(path)
    model = ScriptedModel([*preparation(), answer(packet="snapshot_g1"), review()])

    async def configured(**kwargs):
        return await run_harness(**kwargs, db_path=path, model=model)

    monkeypatch.setattr("api.routes.run_harness", configured)
    monkeypatch.setattr("api.routes.get_storage", lambda: get_storage(path))
    client = TestClient(app)
    response = client.post("/api/ask", json={"question": "Who won?", "game_id": "g1"})
    assert response.status_code == 200
    result = response.json()
    assert result["stop_reason"] == "supported", result["trace"]["events"]
    assert result["packet_ids"] == ["snapshot_g1"]
    saved = client.get("/api/runs/" + result["analysis_run_id"])
    assert saved.json() == result["trace"]
    assert client.get("/api/runs/missing").status_code == 404


def test_tool_contract_discovery_is_from_actual_server():
    async def check():
        async with Client(server()) as client:
            boundary = MCPBoundary(client)
            tools = await boundary.discover()
            assert [t["name"] for t in tools] == ["resolve_game", "ensure_game_data", "get_game_analysis_context",
                                                  "get_game_window", "get_evidence_detail"]
            assert tools[0]["parameters"]["properties"]["query"]["type"] == "string"
    asyncio.run(check())


def test_transient_read_failure_has_one_recorded_retry(tmp_path, monkeypatch):
    original = MCPBoundary.call
    attempts = 0

    async def flaky(self, name, arguments):
        nonlocal attempts
        if name == "get_game_analysis_context":
            attempts += 1
            if attempts == 1:
                raise TimeoutError()
        return await original(self, name, arguments)

    monkeypatch.setattr(MCPBoundary, "call", flaky)
    result = run(tmp_path, [*preparation(), answer(), review()])
    assert result["stop_reason"] == "supported"
    assert result["usage"]["tool_calls"] == 4
    assert len([e for e in result["trace"]["events"] if e["kind"] == "retry"]) == 1


def test_verification_configuration_cannot_investigate(tmp_path):
    result = run(tmp_path, [*preparation(), answer(), review("insufficient", "More detail"),
        call("get_evidence_detail", game_id="g1", packet_id="p1"), answer(), review()], config="verification")
    assert result["usage"]["tool_calls"] == 3
    assert any(e.get("error") == "evidence_gathering_closed" for e in result["trace"]["events"])


def test_malformed_verifier_cannot_approve_an_answer(tmp_path):
    result = run(tmp_path, [*preparation(), answer(), output({"findings": []}),
                           answer(), output({"findings": []}), answer(), output({"findings": []})])
    assert result["stop_reason"] == "no_progress"
    assert not result["analysis"]["claims"]


def test_deadline_cancels_pending_work_and_persists(tmp_path):
    class SlowModel(ScriptedModel):
        async def respond(self, *args, **kwargs):
            await asyncio.Event().wait()

    result = asyncio.run(run_harness("Who won?", game_id="g1", db_path=tmp_path / "timeout.duckdb",
        model=SlowModel([]), limits=Limits(seconds=.2), mcp_client=Client(server())))
    assert result["stop_reason"] == "time_limit"
    assert result["trace"]["events"][-1]["kind"] == "run_stopped"


def test_cancellation_is_persisted(tmp_path):
    async def scenario():
        ready = asyncio.Event()

        class WaitingModel(ScriptedModel):
            async def respond(self, *args, **kwargs):
                ready.set()
                await asyncio.Event().wait()

        repository = HarnessRunRepository(get_storage(tmp_path / "cancel.duckdb"))
        task = asyncio.create_task(run_harness("Who won?", game_id="g1", model=WaitingModel([]),
            repository=repository, mcp_client=Client(server())))
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        con = get_storage(tmp_path / "cancel.duckdb").open()
        try:
            run_id = con.execute("SELECT run_id FROM harness_runs").fetchone()[0]
        finally:
            con.close()
        record = repository.get(run_id)
        assert record["stop_reason"] == "cancelled"
        assert record["events"][-1]["kind"] == "run_stopped"
    asyncio.run(scenario())


def test_responses_adapter_stores_schema_constrained_requests_for_logs():
    import httpx
    from openai import AsyncOpenAI
    from api.nba_agent.harness.model import ResponsesModel

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1, "model": "test-model",
            "status": "completed", "output": [{"type": "message", "id": "msg_test", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": '{"claims": [], "limitations": []}', "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    async def scenario():
        model = ResponsesModel.__new__(ResponsesModel)
        model.name = "test-model"
        model.client = AsyncOpenAI(api_key="test-placeholder", max_retries=0,
                                  http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await model.respond([{"role": "user", "content": "question"}], [])
            assert result["usage"] == {"input_tokens": 10, "output_tokens": 5}
            assert result["text"] == '{"claims": [], "limitations": []}'
        finally:
            await model.close()

    asyncio.run(scenario())
    assert sent[0]["store"] is True
    assert sent[0]["include"] == ["reasoning.encrypted_content"]
    assert sent[0]["text"]["format"]["strict"] is True
    assert sent[0]["parallel_tool_calls"] is False


def test_harness_has_no_direct_basketball_imports():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "api" / "nba_agent" / "harness"
    forbidden = {"api.nba_agent.service", "api.nba_agent.tools", "api.nba_agent.agent",
                 "api.nba_agent.responses_agent", "api.nba_agent.analysis", "api.nba_agent.official_ingest"}
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden, path
            elif isinstance(node, ast.Import):
                assert not forbidden.intersection(alias.name for alias in node.names), path


def test_headline_is_required_and_returned(tmp_path):
    result = run(tmp_path, [*preparation(), answer(headline=None), answer(), review()])
    assert result["stop_reason"] == "supported"
    assert any(e.get("reason") == "missing_headline" for e in result["trace"]["events"])
    assert result["analysis"]["headline"] == "AWY edged HOM by one."
    assert result["answer_markdown"].startswith("# AWY edged HOM by one.")


def test_unsupported_headline_is_revised_like_any_claim(tmp_path):
    result = run(tmp_path, [*preparation(), answer(headline="AWY dominated."), review(headline="unsupported"),
                            answer(), review()], config="verification")
    assert result["stop_reason"] == "supported"
    assert result["analysis"]["headline"] == "AWY edged HOM by one."
    first_review = result["trace"]["reviews"][0]["findings"]
    assert first_review[1] == finding(1, "unsupported")


def test_stopped_run_has_no_headline(tmp_path):
    result = run(tmp_path, [*preparation(), *[answer(packet="invented")] * 3])
    assert result["analysis"]["headline"] is None


def follow_up_run(tmp_path, steps, parent_run_id, mcp=None):
    repository = HarnessRunRepository(get_storage(tmp_path / "trace.duckdb"))
    context = follow_up_context(repository, parent_run_id)
    model = ScriptedModel(steps)
    result = asyncio.run(run_harness("Who scored most?", db_path=tmp_path / "trace.duckdb", model=model,
                                     follow_up=context, mcp_client=Client(mcp or server())))
    return result, model


def test_follow_up_reuses_game_and_verified_ledger_without_new_calls(tmp_path):
    first = run(tmp_path, [*preparation(), answer(), review()])
    result, model = follow_up_run(tmp_path, [answer("AWY scored 101.", headline="AWY reached 101."), review()],
                                  first["analysis_run_id"])
    assert result["stop_reason"] == "supported"
    assert result["usage"]["tool_calls"] == 0
    assert result["parent_run_id"] == first["analysis_run_id"]
    assert result["conversation_id"] == first["conversation_id"] == first["analysis_run_id"]
    assert result["trace"]["evidence"]["p1"]["inherited_from"] == first["analysis_run_id"]
    opening = json.loads(model.requests[0]["history"][0]["content"])
    assert opening["game_id"] == "g1"
    assert opening["conversation"][0]["headline"] == "AWY edged HOM by one."
    assert opening["evidence_ledger"]["p1"]["packet"]["packet_id"] == "p1"
    assert opening["game_resolved"] is True and opening["game_data_cached"] is True

    repository = HarnessRunRepository(get_storage(tmp_path / "trace.duckdb"))
    assert [r["run_id"] for r in repository.conversation(first["conversation_id"])] == [
        first["analysis_run_id"], result["analysis_run_id"]]
    [summary] = repository.recent_conversations()
    assert summary["conversation_id"] == first["conversation_id"]
    assert summary["runs"] == 2
    assert summary["question"] == "Who won?"


def test_follow_up_cannot_switch_games(tmp_path):
    first = run(tmp_path, [*preparation(), answer(), review()])
    result, _ = follow_up_run(tmp_path, [call("resolve_game", query="Other game", game_id="g2")] * 3,
                              first["analysis_run_id"])
    assert result["stop_reason"] == "no_progress"
    assert result["usage"]["tool_calls"] == 0
    assert any(e.get("error") == "game_already_resolved" for e in result["trace"]["events"])


def test_follow_up_requires_a_completed_parent(tmp_path):
    repository = HarnessRunRepository(get_storage(tmp_path / "trace.duckdb"))
    record = {"run_id": "running_run", "status": "running", "question": "q", "events": []}
    repository.create(record)
    with pytest.raises(FollowUpError, match="not_found"):
        follow_up_context(repository, "missing")
    with pytest.raises(FollowUpError, match="not_completed"):
        follow_up_context(repository, "running_run")


def test_live_events_are_durable_public_views(tmp_path):
    seen = []
    result = asyncio.run(run_harness("Who won?", game_id="g1", db_path=tmp_path / "trace.duckdb",
        model=ScriptedModel([*preparation(), answer(), review()]), mcp_client=Client(server()), on_event=seen.append))
    assert [e["sequence"] for e in seen] == [e["sequence"] for e in result["trace"]["events"]]
    assert {"result", "input", "items", "text"}.isdisjoint(set().union(*seen))
    resolved = next(e for e in seen if e["kind"] == "mcp_call_completed" and e["name"] == "resolve_game")
    assert resolved["game"] == {"game_id": "g1"}
    context = next(e for e in seen if e["kind"] == "mcp_call_completed" and e["name"] == "get_game_analysis_context")
    assert context["evidence"] == [{"packet_id": "p1", "type": "game_snapshot"}]
    assert next(e for e in seen if e["kind"] == "verification")["findings"][1]["classification"] == "supported"
    assert all(e["elapsed_seconds"] >= 0 for e in seen)


def sse_events(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_streaming_endpoint_and_follow_up_over_http(tmp_path, monkeypatch):
    path = tmp_path / "stream.duckdb"
    models = iter([ScriptedModel([*preparation(), answer(), review()]),
                   ScriptedModel([answer("AWY scored 101.", headline="AWY reached 101."), review()])])

    async def configured(**kwargs):
        return await run_harness(**kwargs, db_path=path, mcp_client=Client(server()))

    monkeypatch.setattr("api.routes.run_harness", configured)
    monkeypatch.setattr("api.routes.ResponsesModel", lambda: next(models))
    monkeypatch.setattr("api.routes.get_storage", lambda: get_storage(path))
    client = TestClient(app)

    response = client.post("/api/ask/stream", json={"question": "Who won?", "game_id": "g1"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert {name for name, _ in events[:-1]} == {"step"}
    name, result = events[-1]
    assert name == "result"
    assert result["stop_reason"] == "supported"
    assert result["analysis"]["headline"] == "AWY edged HOM by one."
    assert "trace" not in result
    assert [e["sequence"] for _, e in events[:-1]] == [e["sequence"] for e in result["events"]]

    follow = client.post("/api/ask/stream", json={"question": "Who scored most?", "parent_run_id": result["analysis_run_id"]})
    _, second = sse_events(follow.text)[-1]
    assert second["stop_reason"] == "supported"
    assert second["parent_run_id"] == result["analysis_run_id"]

    conversation = client.get(f"/api/conversations/{result['conversation_id']}").json()
    assert [r["analysis_run_id"] for r in conversation["runs"]] == [result["analysis_run_id"], second["analysis_run_id"]]
    assert client.get("/api/conversations").json()["conversations"][0]["runs"] == 2
    assert client.post("/api/ask/stream", json={"question": "Again?", "parent_run_id": "missing"}).status_code == 404
    assert client.post("/api/ask/stream", json={"question": "Again?", "parent_run_id": result["analysis_run_id"],
                                                "game_id": "other"}).status_code == 400
    assert client.post("/api/ask/stream", json={"question": "Again?", "mode": "deterministic"}).status_code == 400
    assert client.get("/api/conversations/missing").status_code == 404


def test_only_verified_follow_ups_survive_up_to_the_limit(tmp_path):
    claims = [claim(f"Fact {i}.", follow_up=f"What happened next {i}?") for i in range(5)]
    findings = [finding(i, follow_up_ok=i != 1) for i in range(5)] + [finding(5)]
    result = run(tmp_path, [*preparation(), answer(claims=claims), output({"findings": findings})])
    assert result["stop_reason"] == "supported"
    kept = [c["follow_up"] for c in result["analysis"]["claims"]]
    # Claim 1's question failed review; the limit keeps the first three that passed.
    assert kept == ["What happened next 0?", None, "What happened next 2?", "What happened next 3?", None]
    assert result["analysis"]["headline_claim"]["follow_up"] is None


def test_unverified_answers_carry_no_follow_ups(tmp_path):
    result = run(tmp_path, [*preparation(), answer(claims=[claim(follow_up="Who scored last?")])], config="basic")
    assert result["stop_reason"] == "answered_unverified"
    assert result["analysis"]["claims"][0]["follow_up"] is None


def test_removed_claims_are_reported_with_reasons(tmp_path):
    first = answer(claims=[claim(), claim("AWY scored 999.")])
    second = output({"findings": [finding(0), finding(1, "unsupported"), finding(2)]})
    result = run(tmp_path, [*preparation(), first, second, answer(), review()], config="verification")
    assert result["stop_reason"] == "supported"
    assert result["analysis"]["removed_claims"] == [{"text": "AWY scored 999.", "classification": "unsupported",
                                                     "reason": "Checked score against the cited snapshot."}]


def test_real_server_documents_sections_and_rejects_guessed_ones(tmp_path):
    from api.nba_agent.mcp_server import mcp as real_server

    async def discover():
        async with Client(real_server) as client:
            boundary = MCPBoundary(client)
            tools = {t["name"]: t for t in await boundary.discover()}
            sections = tools["get_game_analysis_context"]["parameters"]["properties"]["sections"]
            assert sections["items"]["enum"] == ["snapshot", "periods", "runs", "players", "advanced", "possessions", "lineups"]
            assert "largest lead" in sections["description"]
            assert "get_game_window" in tools
            with pytest.raises(Exception, match="invalid_arguments"):
                boundary.validate("get_game_analysis_context", {"game_id": "g1", "sections": ["fourth_quarter"]})
            with pytest.raises(Exception, match="invalid_arguments"):
                boundary.validate("get_game_window", {"game_id": "g1", "period": 4, "from_clock": "late"})
    asyncio.run(discover())


def test_window_evidence_can_back_a_claim(tmp_path):
    steps = [*preparation(), call("get_game_window", game_id="g1", period=4, from_clock="8:00"),
             answer("AWY outscored HOM 9-2 late.", packet="window_4"), review()]
    result = run(tmp_path, steps)
    assert result["stop_reason"] == "supported"
    assert result["trace"]["evidence"]["window_4"]["tool"] == "get_game_window"



def test_trace_spans_nest_calls_under_run_and_verification(tmp_path):
    from api.nba_agent.harness.spans import build_spans

    result = run(tmp_path, [*preparation(), answer("AWY scored 999."), review("unsupported"), answer(), review()],
                 config="verification")
    spans = build_spans(result["trace"])
    by_id = {s["span_id"]: s for s in spans}
    parent = lambda s: by_id[s["parent_id"]]["name"] if s["parent_id"] else None
    root = spans[0]
    assert root["name"] == "NBA MCP Harness" and root["attributes"]["run_id"] == result["analysis_run_id"]
    assert root["tokens"] == {"input": 700, "output": 350}
    tools = [s for s in spans if s["type"] == "tool"]
    assert [s["name"] for s in tools] == ["MCP resolve_game", "MCP ensure_game_data", "MCP get_game_analysis_context"]
    assert all(parent(s) == "NBA MCP Harness" and s["outputs"]["summary"] for s in tools)
    verifies = [s for s in spans if s["type"] == "verify"]
    assert [s["status"] for s in verifies] == ["warning", "ok"]
    checks = [s for s in spans if s["name"] == "Fact-check model"]
    assert [parent(s) for s in checks] == ["Verify claims", "Verify claims"]
    assert all(s["end"] >= s["start"] for s in spans)
    assert next(s for s in spans if s["name"] == "answer_drafted")["outputs"]["draft"]["claims"]


def test_interrupted_run_leaves_open_spans_visible(tmp_path):
    from api.nba_agent.harness.spans import build_spans

    record = {"run_id": "r", "status": "running", "events": [
        {"kind": "model_requested", "elapsed_seconds": 1, "purpose": "decision", "input": []}]}
    spans = build_spans(record)
    assert [s["status"] for s in spans] == ["running", "running"]
    assert spans[1]["end"] == 1


def test_traces_api_lists_filters_and_details_runs(tmp_path, monkeypatch):
    path = tmp_path / "trace.duckdb"
    supported = run(tmp_path, [*preparation(), answer(), review()])
    stopped = run(tmp_path, [call("resolve_game", game_id="other")])
    monkeypatch.setattr("api.routes.get_storage", lambda: get_storage(path))
    client = TestClient(app)

    listed = client.get("/api/traces").json()
    assert listed["total"] == 2
    assert [t["run_id"] for t in listed["traces"]] == [stopped["analysis_run_id"], supported["analysis_run_id"]]
    row = listed["traces"][1]
    assert row["question"] == "Who won?" and row["input_tokens"] == 500 and row["tool_calls"] == 3
    assert row["duration_seconds"] > 0 and row["created_at"]
    only = client.get("/api/traces", params={"stop_reason": "supported"}).json()
    assert [t["run_id"] for t in only["traces"]] == [supported["analysis_run_id"]]
    assert client.get("/api/traces", params={"q": "WHO WON"}).json()["total"] == 2
    assert client.get("/api/traces", params={"q": supported["analysis_run_id"]}).json()["total"] == 1
    assert client.get("/api/traces", params={"limit": 1, "offset": 1}).json()["traces"][0]["run_id"] == supported["analysis_run_id"]

    detail = client.get("/api/traces/" + supported["analysis_run_id"]).json()
    assert detail["trace"]["stop_reason"] == "supported"
    assert detail["spans"][0]["name"] == "NBA MCP Harness"
    assert client.get("/api/traces/missing").status_code == 404

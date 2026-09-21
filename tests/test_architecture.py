import json
from types import SimpleNamespace

import duckdb

from api.nba_agent.db import create_schema, storage_config
from api.nba_agent.evaluation import score_result
from api.nba_agent.responses_agent import ANALYSIS_SCHEMA, FUNCTION_TOOLS, analysis_to_markdown, run_responses_agent, validate_citations


def test_schema_includes_ingestion_jobs(tmp_path):
    con = duckdb.connect(str(tmp_path / "test.duckdb"))
    create_schema(con)
    assert "ingestion_jobs" in {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def test_model_tool_surface_is_consolidated():
    assert [tool["name"] for tool in FUNCTION_TOOLS] == [
        "resolve_game",
        "ensure_game_data",
        "get_game_analysis_context",
        "get_evidence_detail",
    ]
    assert ANALYSIS_SCHEMA["additionalProperties"] is False


def test_citations_are_limited_to_available_packets():
    analysis = {
        "citations": [
            {"packet_id": "real", "claim": "supported"},
            {"packet_id": "invented", "claim": "unsupported"},
        ]
    }
    ids, packets = validate_citations(analysis, [{"packet_id": "real"}], 4)
    assert ids == ["real"]
    assert packets == [{"packet_id": "real"}]
    assert analysis["citations"] == [{"packet_id": "real", "claim": "supported"}]


def test_structured_analysis_renders_markdown():
    analysis = {
        "headline": "A game",
        "summary": "A supported summary.",
        "deciding_factors": ["Shooting"],
        "player_findings": [],
        "decisive_windows": [],
        "limitations": [],
        "citations": [{"packet_id": "packet_1", "claim": "Box score"}],
    }
    assert "# A game" in analysis_to_markdown(analysis)
    assert "`packet_1`" in analysis_to_markdown(analysis)


def test_evaluation_scoring_detects_grounding_failures():
    case = {"id": "x", "expected_route": "full", "required_terms_any": ["turnover"], "forbidden_terms": ["overtime"], "minimum_evidence": 1}
    scored = score_result(case, {"route": "full", "answer_markdown": "Turnover margin mattered.", "packet_ids": ["p1"]})
    assert scored["passed"] is True


def test_storage_defaults_to_local_duckdb(monkeypatch):
    monkeypatch.delenv("NBA_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert storage_config()["backend"] == "duckdb"


def test_responses_path_returns_validated_structured_analysis(monkeypatch, tmp_path):
    analysis = {
        "headline": "NYK 121, CLE 108",
        "summary": "New York's shooting decided it.",
        "deciding_factors": ["Shot making"],
        "player_findings": [],
        "decisive_windows": [],
        "limitations": [],
        "citations": [{"packet_id": "p1", "claim": "Team efficiency"}],
    }
    response = SimpleNamespace(id="resp_1", output=[], output_text=json.dumps(analysis))
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
    monkeypatch.setattr(
        "api.nba_agent.responses_agent.NBAService.prepare_game",
        lambda self, *args, **kwargs: (
            {"summary": {"game_id": "0042500303", "label": "NYK 121, CLE 108", "game_date": "2026-05-23"}},
            {"summary": {"cache_status": "already_cached"}},
        ),
    )
    monkeypatch.setattr(
        "api.nba_agent.responses_agent.NBAService.get_analysis_context",
        lambda self, *args, **kwargs: {"evidence_packets": [{"packet_id": "p1", "type": "advanced_context"}]},
    )
    result = run_responses_agent("Why did New York win?", client=client, db_path=tmp_path / "unused.duckdb")
    assert result["route"] == "openai_responses_tools"
    assert result["analysis"]["headline"] == "NYK 121, CLE 108"
    assert result["packet_ids"] == ["p1"]

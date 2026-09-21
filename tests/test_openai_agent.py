import re

import pytest

from api.nba_agent.openai_agent import (
    OPENAI_TRACE_WORKFLOW_NAME,
    assert_openai_mode_ready,
    build_trace_metadata,
    build_openai_agent_input,
    extract_packet_ids,
    trace_metadata_value,
    trace_id,
)
from api.nba_agent.tools import resolution_season_type_order


def test_extract_packet_ids_from_answer():
    text = "Evidence: adv_0042500303_official-team-advanced and run_0042500303_1_258_309."
    assert extract_packet_ids(text) == [
        "adv_0042500303_official-team-advanced",
        "run_0042500303_1_258_309",
    ]


def test_local_openai_mode_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        assert_openai_mode_ready("local_agents_sdk_mcp")


def test_trace_id_matches_openai_format():
    assert re.fullmatch(r"trace_[a-f0-9]{32}", trace_id())


def test_trace_metadata_has_debugging_fields():
    metadata = build_trace_metadata(
        question="Why did the Knicks win?",
        resolved_game_id="0042500303",
        resolution={
            "summary": {
                "resolution_status": "provided",
                "label": "NYK 121, CLE 108",
                "game_date": "2026-05-23",
            }
        },
        cache={"summary": {"cache_status": "already_cached"}},
        mode="local_agents_sdk_mcp",
        max_evidence=4,
        persist=False,
    )

    assert metadata["app"] == "nba-analyst-agent"
    assert metadata["game_id"] == "0042500303"
    assert metadata["cache_status"] == "already_cached"
    assert metadata["tool_count"] == "4"
    assert metadata["question_length"] == str(len("Why did the Knicks win?"))
    assert metadata["persist"] == "false"
    assert all(isinstance(value, str) for value in metadata.values())
    assert OPENAI_TRACE_WORKFLOW_NAME == "NBA Analyst Agent"


def test_trace_metadata_values_are_strings():
    assert trace_metadata_value(None) == ""
    assert trace_metadata_value(True) == "true"
    assert trace_metadata_value(False) == "false"
    assert trace_metadata_value(8) == "8"


def test_openai_agent_input_pins_backend_resolved_game():
    agent_input = build_openai_agent_input(
        "did the Thunder lose last night because SGA did not get to the free throw line as much?",
        {
            "summary": {
                "resolution_status": "resolved",
                "game_id": "0042500316",
                "label": "OKC 91, SAS 118",
                "game_date": "2026-05-28",
            }
        },
        {"summary": {"cache_status": "already_cached"}},
    )

    assert "game_id: 0042500316" in agent_input
    assert "game_date: 2026-05-28" in agent_input
    assert "Analyze only this resolved game_id" in agent_input
    assert "Do not answer from another Thunder game" in agent_input


def test_resolution_searches_playoffs_even_when_regular_season_is_requested():
    assert resolution_season_type_order("Regular Season") == ["Regular Season", "Playoffs"]
    assert resolution_season_type_order("Auto") == ["Playoffs", "Regular Season"]

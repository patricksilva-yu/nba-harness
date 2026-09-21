"""Direct OpenAI Responses API adapter using application function tools."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from api.nba_agent.agent import expand_evidence_from_packets
from api.nba_agent.service import NBAService
from api.nba_agent.tools import DEFAULT_DB, persist_analysis_run


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "deciding_factors": {"type": "array", "items": {"type": "string"}},
        "player_findings": {"type": "array", "items": {"type": "string"}},
        "decisive_windows": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "packet_id": {"type": "string"},
                    "claim": {"type": "string"},
                },
                "required": ["packet_id", "claim"],
            },
        },
    },
    "required": [
        "headline",
        "summary",
        "deciding_factors",
        "player_findings",
        "decisive_windows",
        "limitations",
        "citations",
    ],
}


FUNCTION_TOOLS = [
    {
        "type": "function",
        "name": "resolve_game",
        "description": "Resolve a natural-language NBA game reference. Read-only and safe to retry.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}, "season_type": {"type": "string"}},
            "required": ["query", "season_type"],
        },
    },
    {
        "type": "function",
        "name": "ensure_game_data",
        "description": "Ensure official NBA data for a game is locally cached. May perform network ingestion; safe to retry.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"game_id": {"type": "string"}, "season_type": {"type": "string"}},
            "required": ["game_id", "season_type"],
        },
    },
    {
        "type": "function",
        "name": "get_game_analysis_context",
        "description": "Return grounded game context and evidence packets for requested analysis sections. Use the fewest sections needed.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "game_id": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["snapshot", "advanced", "runs", "possessions", "players", "lineups"]},
                },
            },
            "required": ["game_id", "sections"],
        },
    },
    {
        "type": "function",
        "name": "get_evidence_detail",
        "description": "Rehydrate one cited evidence packet when its compact claim is insufficient.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"packet_id": {"type": "string"}, "game_id": {"type": "string"}},
            "required": ["packet_id", "game_id"],
        },
    },
]


def dispatch_tool(domain: NBAService, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "resolve_game":
        return domain.resolve_game(arguments["query"], season_type=arguments["season_type"])
    if name == "ensure_game_data":
        return domain.ensure_game_data(arguments["game_id"], season_type=arguments["season_type"])
    if name == "get_game_analysis_context":
        return domain.get_analysis_context(arguments["game_id"], arguments["sections"], persist=False)
    if name == "get_evidence_detail":
        return domain.get_evidence_detail(arguments["packet_id"], arguments["game_id"])
    raise ValueError(f"Unknown tool: {name}")


def analysis_to_markdown(analysis: dict[str, Any]) -> str:
    lines = [f"# {analysis['headline']}", "", analysis["summary"]]
    sections = [
        ("What Decided It", "deciding_factors"),
        ("Player Findings", "player_findings"),
        ("Decisive Windows", "decisive_windows"),
        ("Limitations", "limitations"),
    ]
    for title, key in sections:
        values = analysis.get(key, [])
        if values:
            lines.extend(["", f"## {title}", *[f"- {value}" for value in values]])
    if analysis.get("citations"):
        lines.extend(["", "## Evidence", *[f"- `{c['packet_id']}` — {c['claim']}" for c in analysis["citations"]]])
    return "\n".join(lines)


def validate_citations(analysis: dict[str, Any], available_packets: list[dict[str, Any]], max_evidence: int) -> tuple[list[str], list[dict[str, Any]]]:
    packet_by_id = {packet["packet_id"]: packet for packet in available_packets}
    requested = [item["packet_id"] for item in analysis.get("citations", [])]
    valid_ids = list(dict.fromkeys(packet_id for packet_id in requested if packet_id in packet_by_id))[:max_evidence]
    analysis["citations"] = [item for item in analysis.get("citations", []) if item["packet_id"] in valid_ids]
    return valid_ids, [packet_by_id[packet_id] for packet_id in valid_ids]


def run_responses_agent(
    question: str,
    game_id: str | None = None,
    season: str | None = None,
    season_type: str = "Auto",
    max_evidence: int = 4,
    persist: bool = False,
    db_path: Path = DEFAULT_DB,
    client: Any | None = None,
) -> dict[str, Any]:
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for responses_tools mode.")
        from openai import OpenAI

        client = OpenAI()
    domain = NBAService(db_path)
    resolution, cache = domain.prepare_game(question, game_id, season, season_type)
    resolved_id = resolution.get("summary", {}).get("game_id")
    if not resolved_id:
        return {
            "question": question,
            "mode": "responses_tools",
            "route": "unresolved",
            "resolution": resolution.get("summary", {}),
            "analysis": None,
            "answer_markdown": "I could not resolve a unique completed game. Please identify the teams or date.",
            "packet_ids": [],
            "evidence": [],
            "warnings": ["No unique game was resolved."],
        }

    # Preload compact context so evidence validation is deterministic even when
    # the model chooses only a subset of tools.
    reference = domain.get_analysis_context(resolved_id, persist=False)
    prompt = (
        f"Question: {question}\nResolved game_id: {resolved_id}\n"
        f"Game: {resolution['summary'].get('label')} on {resolution['summary'].get('game_date')}.\n"
        "Use only tool-provided game facts. Cite packet IDs exactly. State limitations rather than guessing."
    )
    response = client.responses.create(
        model=os.getenv("NBA_OPENAI_MODEL", "gpt-5.5"),
        instructions=(
            "You are an evidence-first NBA postgame analyst. Answer the requested game question directly. "
            "Use the minimum tool evidence sufficient, distinguish inferred rotation data, and stop when supported."
        ),
        input=prompt,
        tools=FUNCTION_TOOLS,
        text={"format": {"type": "json_schema", "name": "nba_analysis", "strict": True, "schema": ANALYSIS_SCHEMA}, "verbosity": "low"},
        reasoning={"effort": "medium"},
        metadata={"app": "nba-analyst", "game_id": resolved_id},
        max_tool_calls=6,
    )
    tool_calls = 0
    while True:
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not calls:
            break
        tool_calls += len(calls)
        if tool_calls > 6:
            raise RuntimeError("Responses tool-call budget exceeded.")
        outputs = []
        for call in calls:
            result = dispatch_tool(domain, call.name, json.loads(call.arguments))
            outputs.append({"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result, default=str)})
        response = client.responses.create(
            model=os.getenv("NBA_OPENAI_MODEL", "gpt-5.5"),
            previous_response_id=response.id,
            input=outputs,
            tools=FUNCTION_TOOLS,
            text={"format": {"type": "json_schema", "name": "nba_analysis", "strict": True, "schema": ANALYSIS_SCHEMA}, "verbosity": "low"},
            reasoning={"effort": "medium"},
            max_tool_calls=max(1, 6 - tool_calls),
        )
    analysis = json.loads(response.output_text)
    packet_ids, packets = validate_citations(analysis, reference["evidence_packets"], max_evidence)
    markdown = analysis_to_markdown(analysis)
    run_id = None
    if persist:
        run_id = persist_analysis_run(resolved_id, question, markdown, packet_ids, db_path)
    return {
        "question": question,
        "mode": "responses_tools",
        "route": "openai_responses_tools",
        "resolution": resolution.get("summary", {}),
        "cache": cache.get("summary", {}) if cache else None,
        "analysis": analysis,
        "answer_markdown": markdown,
        "packet_ids": packet_ids,
        "analysis_run_id": run_id,
        "evidence": expand_evidence_from_packets(packets, max_items=max_evidence),
        "persisted": persist,
        "warnings": [] if packet_ids else ["The structured answer did not cite a valid evidence packet."],
        "trace": {"provider": "openai_responses", "response_id": response.id, "tool_calls": tool_calls, "request_id": uuid.uuid4().hex},
    }


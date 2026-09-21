#!/usr/bin/env python3
"""OpenAI-backed analyst adapter scaffold.

The deterministic agent remains the default. This module defines the OpenAI
integration modes and reports whether the current environment can run them.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

from api.nba_agent.agent import expand_evidence_from_packets, resolve_or_use_game_id, season_type_for_ingest
from api.nba_agent.tools import (
    DEFAULT_DB,
    ensure_game_cached,
    find_decisive_runs,
    get_advanced_game_context,
    get_game_snapshot,
    get_player_game_context,
    get_possession_summary,
    persist_analysis_run,
)


OpenAIAgentMode = Literal["deterministic", "responses_tools", "local_agents_sdk_mcp", "remote_responses_mcp"]

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULT_OPENAI_MODEL = os.getenv("NBA_OPENAI_MODEL", "gpt-5.5")
DEFAULT_OPENAI_AGENT_MODE = os.getenv("NBA_OPENAI_AGENT_MODE", "deterministic")
DEFAULT_REMOTE_MCP_URL = os.getenv("NBA_MCP_SERVER_URL")
OPENAI_TRACE_WORKFLOW_NAME = "NBA Analyst Agent"
PROMPT_VERSION = "openai_analyst_v1"
TOOL_ALLOWLIST_VERSION = "nba_mcp_tools_v1"


def load_openai_analyst_prompt() -> str | None:
    env_prompt = os.getenv("NBA_OPENAI_AGENT_INSTRUCTIONS")
    if env_prompt:
        return env_prompt
    try:
        from prompts.openai_analyst import OPENAI_ANALYST_PROMPT
    except Exception:
        return None
    prompt = OPENAI_ANALYST_PROMPT.strip()
    return prompt or None


def trace_id() -> str:
    return f"trace_{uuid.uuid4().hex}"


def tool_allowlist_hash() -> str:
    payload = "|".join(LOCAL_ALLOWED_TOOLS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def trace_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_trace_metadata(
    *,
    question: str,
    resolved_game_id: str | None,
    resolution: dict[str, Any],
    cache: dict[str, Any] | None,
    mode: str,
    max_evidence: int,
    persist: bool,
) -> dict[str, Any]:
    resolution_summary = resolution.get("summary", {})
    cache_summary = cache.get("summary", {}) if cache else {}
    metadata = {
        "app": "nba-analyst-agent",
        "mode": mode,
        "model": DEFAULT_OPENAI_MODEL,
        "game_id": resolved_game_id,
        "game_label": resolution_summary.get("label"),
        "game_date": resolution_summary.get("game_date"),
        "resolution_status": resolution_summary.get("resolution_status"),
        "cache_status": cache_summary.get("cache_status"),
        "prompt_version": PROMPT_VERSION,
        "tool_allowlist_version": TOOL_ALLOWLIST_VERSION,
        "tool_allowlist_hash": tool_allowlist_hash(),
        "tool_count": len(LOCAL_ALLOWED_TOOLS),
        "max_evidence": max_evidence,
        "persist": persist,
        "question_length": len(question),
    }
    return {key: trace_metadata_value(value) for key, value in metadata.items()}

LOCAL_ALLOWED_TOOLS = [
    "resolve_game",
    "ensure_game_data",
    "get_game_analysis_context",
    "get_evidence_detail",
]


@dataclass
class OpenAIAgentConfig:
    mode: str
    model: str
    has_api_key: bool
    has_agents_sdk: bool
    has_openai_sdk: bool
    remote_mcp_url: str | None
    local_allowed_tools: list[str]


def openai_agent_config() -> dict[str, Any]:
    try:
        import agents  # noqa: F401

        has_agents_sdk = True
    except Exception:
        has_agents_sdk = False
    try:
        import openai  # noqa: F401

        has_openai_sdk = True
    except Exception:
        has_openai_sdk = False

    return asdict(
        OpenAIAgentConfig(
            mode=DEFAULT_OPENAI_AGENT_MODE,
            model=DEFAULT_OPENAI_MODEL,
            has_api_key=bool(os.getenv("OPENAI_API_KEY")),
            has_agents_sdk=has_agents_sdk,
            has_openai_sdk=has_openai_sdk,
            remote_mcp_url=DEFAULT_REMOTE_MCP_URL,
            local_allowed_tools=LOCAL_ALLOWED_TOOLS,
        )
    )


def assert_openai_mode_ready(mode: str) -> None:
    config = openai_agent_config()
    if mode == "deterministic":
        return
    if not config["has_api_key"]:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI agent modes.")
    if mode == "responses_tools" and not config["has_openai_sdk"]:
        raise RuntimeError("openai is required for responses_tools mode.")
    if mode == "local_agents_sdk_mcp" and not config["has_agents_sdk"]:
        raise RuntimeError("openai-agents is required for local_agents_sdk_mcp mode.")
    if mode == "remote_responses_mcp":
        if not config["has_openai_sdk"]:
            raise RuntimeError("openai is required for remote_responses_mcp mode.")
        if not config["remote_mcp_url"]:
            raise RuntimeError("NBA_MCP_SERVER_URL is required for remote_responses_mcp mode.")
    if mode not in ("responses_tools", "local_agents_sdk_mcp", "remote_responses_mcp"):
        raise RuntimeError(f"Unknown OpenAI agent mode: {mode}")


def extract_packet_ids(text: str) -> list[str]:
    seen: set[str] = set()
    packet_ids: list[str] = []
    for match in re.findall(r"\b(?:snapshot|adv|run|possession-summary|player)_[A-Za-z0-9_.-]+", text):
        if match not in seen:
            seen.add(match)
            packet_ids.append(match.rstrip(".,;)"))
    return packet_ids


def collect_reference_packets(game_id: str, db_path: Path = DEFAULT_DB) -> list[dict[str, Any]]:
    responses = [
        get_game_snapshot(game_id, db_path, persist=False),
        get_advanced_game_context(game_id, db_path, persist=False),
        find_decisive_runs(game_id, db_path, persist=False),
        get_possession_summary(game_id, db_path, persist=False),
        get_player_game_context(game_id, db_path, persist=False),
    ]
    packets: list[dict[str, Any]] = []
    for response in responses:
        packets.extend(response.get("evidence_packets", []))
    return packets


def build_openai_agent_input(question: str, resolution: dict[str, Any], cache: dict[str, Any] | None) -> str:
    summary = resolution.get("summary", {})
    game_id = summary.get("game_id")
    if not game_id:
        return question
    cache_status = (cache or {}).get("summary", {}).get("cache_status", "unknown")
    return "\n".join(
        [
            "User question:",
            question,
            "",
            "Backend-resolved game context:",
            f"- game_id: {game_id}",
            f"- label: {summary.get('label') or ''}",
            f"- game_date: {summary.get('game_date') or ''}",
            f"- resolution_status: {summary.get('resolution_status') or ''}",
            f"- local_data_status: {cache_status}",
            "",
            "Analyze only this resolved game_id unless the user explicitly corrects the game.",
            "When calling MCP tools, pass this exact game_id.",
            "Do not answer from another Thunder game, another date, or another opponent.",
            "If the user's relative date wording conflicts with this resolved game, say so before answering.",
        ]
    )


async def run_local_agents_sdk_mcp(
    agent_input: str,
    *,
    trace_id_value: str,
    group_id: str,
    trace_metadata: dict[str, Any],
) -> str:
    from agents import Agent, RunConfig, Runner
    from agents.mcp import MCPServerStdio, create_static_tool_filter
    from agents.tracing import flush_traces

    run_config = RunConfig(
        workflow_name=OPENAI_TRACE_WORKFLOW_NAME,
        trace_id=trace_id_value,
        group_id=group_id,
        trace_metadata=trace_metadata,
    )
    server = MCPServerStdio(
        params={
            "command": sys.executable,
            "args": ["-m", "api.nba_agent.mcp_server"],
            "cwd": str(ROOT),
        },
        cache_tools_list=True,
        name="nba-analyst-local",
        tool_filter=create_static_tool_filter(allowed_tool_names=LOCAL_ALLOWED_TOOLS),
        use_structured_content=True,
    )
    async with server:
        agent = Agent(
            name="NBA Analyst",
            instructions=load_openai_analyst_prompt(),
            model=DEFAULT_OPENAI_MODEL,
            mcp_servers=[server],
        )
        try:
            result = await Runner.run(agent, agent_input, max_turns=8, run_config=run_config)
            return str(result.final_output)
        finally:
            flush_traces()


def run_openai_agent(
    question: str,
    game_id: str | None = None,
    season: str | None = None,
    season_type: str = "Auto",
    max_evidence: int = 4,
    persist: bool = False,
    mode: str = "local_agents_sdk_mcp",
    db_path: Path = DEFAULT_DB,
    **_: Any,
) -> dict[str, Any]:
    assert_openai_mode_ready(mode)
    if mode == "remote_responses_mcp":
        return {
            "question": question,
            "mode": mode,
            "route": "openai_remote_mcp",
            "status": "not_implemented",
            "answer_markdown": "Remote Responses MCP mode is configured but not wired yet.",
            "packet_ids": [],
            "evidence": [],
            "persisted": persist,
            "config": openai_agent_config(),
        }

    resolution = resolve_or_use_game_id(question, game_id, season, season_type, timeout=20)
    resolved_game_id = resolution.get("summary", {}).get("game_id")
    cache = None
    reference_packets: list[dict[str, Any]] = []
    if resolved_game_id:
        ingest_season_type = season_type_for_ingest(resolution, season_type)
        cache = ensure_game_cached(resolved_game_id, db_path, season=season, season_type=ingest_season_type)
        snapshot = get_game_snapshot(resolved_game_id, db_path, persist=False)
        resolution["summary"] = {
            **resolution["summary"],
            "label": resolution["summary"].get("label") or snapshot.get("summary", {}).get("label"),
            "game_date": resolution["summary"].get("game_date") or snapshot.get("summary", {}).get("date"),
        }
        reference_packets = collect_reference_packets(resolved_game_id, db_path)

    current_trace_id = trace_id()
    trace_metadata = build_trace_metadata(
        question=question,
        resolved_game_id=resolved_game_id,
        resolution=resolution,
        cache=cache,
        mode=mode,
        max_evidence=max_evidence,
        persist=persist,
    )
    agent_input = build_openai_agent_input(question, resolution, cache)
    answer = asyncio.run(
        run_local_agents_sdk_mcp(
            agent_input,
            trace_id_value=current_trace_id,
            group_id=resolved_game_id or "unresolved",
            trace_metadata=trace_metadata,
        )
    )
    model_packet_ids = extract_packet_ids(answer)
    reference_packet_ids = [packet["packet_id"] for packet in reference_packets]
    packet_ids = model_packet_ids or reference_packet_ids[:max_evidence]
    evidence_packets = [packet for packet in reference_packets if packet["packet_id"] in packet_ids]
    analysis_run_id = None
    if resolved_game_id:
        analysis_run_id = persist_analysis_run(
            game_id=resolved_game_id,
            user_question=question,
            memo_markdown=answer,
            packet_ids=packet_ids,
            db_path=db_path,
        )

    return {
        "question": question,
        "mode": mode,
        "route": "openai_local_mcp",
        "resolution": resolution.get("summary", {}),
        "cache": cache["summary"] if cache else None,
        "answer_markdown": answer,
        "packet_ids": packet_ids,
        "analysis_run_id": analysis_run_id,
        "evidence": expand_evidence_from_packets(evidence_packets, max_items=max_evidence),
        "persisted": persist,
        "warnings": [] if model_packet_ids else ["Model output did not include packet IDs; showing reference packets from deterministic context."],
        "trace": {
            "provider": "openai_agents_sdk",
            "workflow_name": OPENAI_TRACE_WORKFLOW_NAME,
            "trace_id": current_trace_id,
            "group_id": resolved_game_id or "unresolved",
            "metadata": trace_metadata,
        },
        "config": openai_agent_config(),
    }

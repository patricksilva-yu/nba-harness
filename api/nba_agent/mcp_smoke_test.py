#!/usr/bin/env python3
"""Smoke test the FastMCP server in memory."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from fastmcp import Client

from api.nba_agent.mcp_server import mcp


def as_data(result: Any) -> Any:
    return getattr(result, "structured_content", None) or getattr(result, "data", None)


async def run_smoke_test(game_id: str) -> dict[str, Any]:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = sorted(tool.name for tool in tools)
        context = as_data(
            await client.call_tool(
                "get_game_analysis_context",
                {"game_id": game_id, "sections": ["snapshot", "advanced", "players", "runs"]},
            )
        )
        snapshot = context["context"]["snapshot"]
        advanced = context["context"]["advanced"]
        players = context["context"]["players"]
        runs = context["context"]["runs"]
        top_run_packet = runs["evidence_packets"][0]["packet_id"] if runs["evidence_packets"] else None
        return {
            "tool_count": len(tool_names),
            "tools": tool_names,
            "snapshot_label": snapshot["summary"]["label"],
            "advanced_source": advanced["summary"]["advanced_context_source"],
            "player_context_status": players["summary"].get("resolution_status", "available"),
            "player_count": players["summary"].get("player_count", 0),
            "top_run_packet": top_run_packet,
            "preferred_tools_present": all(
                name in tool_names
                for name in ("resolve_game", "ensure_game_data", "get_game_analysis_context", "get_evidence_detail")
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", default="0042200404")
    args = parser.parse_args()
    result = asyncio.run(run_smoke_test(args.game_id))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

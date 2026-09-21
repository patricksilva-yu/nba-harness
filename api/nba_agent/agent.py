#!/usr/bin/env python3
"""Thin deterministic analyst agent over the NBA MCP-style tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from api.nba_agent.analysis import build_advanced_read, build_memo, build_player_read, pick_top_packet
from api.nba_agent.tools import (
    DEFAULT_DB,
    ensure_game_cached,
    find_decisive_runs,
    get_advanced_game_context,
    get_game_snapshot,
    get_lineup_stints,
    get_player_game_context,
    get_possession_summary,
    persist_analysis_run,
    rehydrate_evidence_packet,
    resolve_game_reference,
)


def classify_question(question: str) -> str:
    text = question.lower()
    if any(term in text for term in ("lineup", "lineups", "rotation", "stint", "stints", "substitution")):
        return "lineups"
    if any(term in text for term in ("advanced", "offensive rating", "net rating", "efg", "true shooting", "pie")):
        return "advanced"
    if any(term in text for term in ("late", "clutch", "fourth", "4th", "run", "stretch", "close")):
        return "late_game"
    if any(term in text for term in ("player", "who", "swing", "scorer", "assist", "turnover")):
        return "players"
    return "full"


def collect_packet_ids(*responses: dict[str, Any]) -> list[str]:
    packet_ids: list[str] = []
    for response in responses:
        packet_ids.extend(packet["packet_id"] for packet in response.get("evidence_packets", []))
    return packet_ids


def packet_title(packet_id: str, hydrated: dict[str, Any]) -> str:
    packet = hydrated.get("packet", {})
    packet_type = packet.get("packet_type") or packet.get("payload", {}).get("type")
    if packet_type == "game_snapshot":
        return "Game snapshot"
    if packet_type == "advanced_context":
        return "Advanced team metrics"
    if packet_type == "run_candidate":
        return "Scoring window"
    if packet_type == "possession_segment_summary":
        return "Possession/event summary"
    if packet_type == "player_game_context":
        return "Player box-score context"
    if packet_type == "lineup_stints":
        return "Lineup/rotation stints"
    if packet_id.startswith("run_"):
        return "Scoring window play-by-play"
    return packet_id


def packet_title_from_packet(packet: dict[str, Any]) -> str:
    return packet_title(
        packet.get("packet_id", "evidence"),
        {"packet": {"payload": packet, "packet_type": packet.get("type")}},
    )


def collect_packets(*responses: dict[str, Any]) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for response in responses:
        packets.extend(response.get("evidence_packets", []))
    return packets


def build_structured_analysis(answer: str, packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Provide the UI a stable shape for deterministic answers too."""
    headings: dict[str, list[str]] = {}
    current = "summary"
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            current = line[3:]
            headings.setdefault(current, [])
        elif line and not line.startswith("Evidence:"):
            headings.setdefault(current, []).append(line.removeprefix("- "))
    summary_lines = headings.get("summary", []) or next(iter(headings.values()), [])
    return {
        "headline": answer.splitlines()[0].removeprefix("# ") if answer else "NBA analysis",
        "summary": summary_lines[0] if summary_lines else "Evidence-backed deterministic analysis.",
        "deciding_factors": headings.get("What Decided It", []) + headings.get("Advanced Stats Read", []),
        "player_findings": headings.get("Player Read", []) + headings.get("Box Score Lie", []),
        "decisive_windows": headings.get("Decisive Window", []) + headings.get("Rotation / Stint Read", []),
        "limitations": [warning for packet in packets for warning in packet.get("caveats", [])][:4],
        "citations": [
            {"packet_id": packet["packet_id"], "claim": packet.get("claim_seed", "Supporting evidence")}
            for packet in packets[:6]
        ],
    }


def expand_evidence_from_packets(
    packets: list[dict[str, Any]],
    max_items: int = 4,
) -> list[dict[str, Any]]:
    expanded = []
    for packet in packets[:max_items]:
        expanded.append(
            {
                "packet_id": packet["packet_id"],
                "title": packet_title_from_packet(packet),
                "collapsed": True,
                "source": "in_memory",
                "payload": {
                    "summary": {
                        "packet_id": packet["packet_id"],
                        "source": "in_memory",
                    },
                    "packet": {
                        "packet_id": packet["packet_id"],
                        "packet_type": packet.get("type"),
                        "claim_seed": packet.get("claim_seed"),
                        "source_provider": packet.get("source", {}).get("provider"),
                        "source_detail": packet.get("source", {}).get("detail"),
                        "evidence_level": packet.get("evidence_level"),
                        "confidence": packet.get("confidence"),
                        "payload": packet,
                    },
                },
            }
        )
    return expanded


def expand_evidence(
    game_id: str,
    packet_ids: list[str],
    db_path: Path,
    max_items: int = 4,
) -> list[dict[str, Any]]:
    expanded = []
    for packet_id in packet_ids[:max_items]:
        hydrated = rehydrate_evidence_packet(packet_id, game_id, db_path)
        expanded.append(
            {
                "packet_id": packet_id,
                "title": packet_title(packet_id, hydrated),
                "collapsed": True,
                "source": hydrated.get("summary", {}).get("source"),
                "payload": hydrated,
            }
        )
    return expanded


def resolve_or_use_game_id(
    question: str,
    game_id: str | None,
    season: str | None,
    season_type: str,
    timeout: int,
) -> dict[str, Any]:
    if game_id:
        return {
            "summary": {
                "resolution_status": "provided",
                "game_id": game_id,
                "confidence": "high",
            },
            "game": {"game_id": game_id},
            "warnings": [],
        }
    return resolve_game_reference(
        query=question,
        season=season,
        season_type=season_type,
        limit=20,
        timeout=timeout,
    )


def season_type_for_ingest(resolution: dict[str, Any], requested_season_type: str) -> str:
    resolved = resolution.get("summary", {}).get("season_type")
    if resolved:
        return resolved
    if requested_season_type and requested_season_type.lower() != "auto":
        return requested_season_type
    game_id = str(resolution.get("summary", {}).get("game_id") or "")
    if game_id.startswith("004"):
        return "Playoffs"
    if game_id.startswith("002"):
        return "Regular Season"
    return "Playoffs"


def build_routed_answer(
    route: str,
    snapshot: dict[str, Any],
    advanced: dict[str, Any] | None = None,
    runs: dict[str, Any] | None = None,
    possessions: dict[str, Any] | None = None,
    players: dict[str, Any] | None = None,
    lineups: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = [f"# {snapshot['summary']['label']} - Analyst Answer", ""]
    if route == "advanced" and advanced:
        lines.append("## Advanced Read")
        lines.extend(build_advanced_read(advanced))
    elif route == "late_game" and runs:
        lines.append("## Late-Game / Run Read")
        top_run = pick_top_packet(runs)
        if top_run:
            metrics = top_run["metrics"]
            lines.extend(
                [
                    top_run["claim_seed"],
                    f"Window score moved from {metrics['start_score']} to {metrics['end_score']}.",
                    f"Rank factors: {json.dumps(metrics.get('rank_factors', {}), sort_keys=True)}.",
                    "",
                    f"Evidence: `{top_run['packet_id']}` "
                    f"({top_run['source']['provider']}, {top_run['confidence']} confidence).",
                ]
            )
        else:
            lines.append("No run candidate was available.")
    elif route == "players" and players:
        lines.append("## Player Read")
        lines.extend(build_player_read(snapshot, players))
    elif route == "lineups" and lineups:
        lines.append("## Rotation / Stint Read")
        summary = lineups.get("summary", {})
        stints = lineups.get("stints", [])
        lines.append(
            f"Rotation context returned {summary.get('stint_count', 0)} rows "
            f"using `{summary.get('lineup_model')}`."
        )
        for stint in stints[:5]:
            lines.append(
                "- "
                f"{stint.get('team_abbr') or 'team'}: {stint.get('player_name')} "
                f"{stint.get('start_clock') or '?'} to {stint.get('end_clock') or '?'} "
                f"(source: {stint.get('source')}, confidence: {stint.get('confidence')})"
            )
        packet = pick_top_packet(lineups)
        if packet:
            lines.append("")
            lines.append(f"Evidence: `{packet['packet_id']}` ({packet['confidence']} confidence).")
    else:
        if not all((advanced, runs, possessions, players)):
            raise ValueError("Full answer route requires all context responses")
        return build_memo(snapshot, advanced, runs, possessions, players)
    return "\n".join(lines)


def run_agent(
    question: str,
    game_id: str | None = None,
    db_path: Path = DEFAULT_DB,
    season: str | None = None,
    season_type: str = "Auto",
    timeout: int = 20,
    max_evidence: int = 4,
    persist: bool = False,
) -> dict[str, Any]:
    resolution = resolve_or_use_game_id(question, game_id, season, season_type, timeout)
    resolved_game_id = resolution.get("summary", {}).get("game_id")
    if not resolved_game_id:
        return {
            "question": question,
            "resolution": resolution,
            "answer_markdown": "I could not resolve a recent completed game for that question.",
            "route": "unresolved",
            "packet_ids": [],
            "evidence": [],
            "tool_responses": {},
        }

    ingest_season_type = season_type_for_ingest(resolution, season_type)
    cache = ensure_game_cached(resolved_game_id, db_path, season=season, season_type=ingest_season_type, timeout=timeout)
    route = classify_question(question)
    snapshot = get_game_snapshot(resolved_game_id, db_path, persist=persist)
    resolution_summary = {
        **resolution["summary"],
        "label": resolution["summary"].get("label") or snapshot.get("summary", {}).get("label"),
        "game_date": resolution["summary"].get("game_date") or snapshot.get("summary", {}).get("date"),
    }

    advanced = runs = possessions = players = lineups = None
    if route in ("advanced", "full"):
        advanced = get_advanced_game_context(resolved_game_id, db_path, persist=persist)
    if route in ("late_game", "full"):
        runs = find_decisive_runs(resolved_game_id, db_path, persist=persist)
    if route == "full":
        possessions = get_possession_summary(resolved_game_id, db_path, persist=persist)
    if route in ("players", "full"):
        players = get_player_game_context(resolved_game_id, db_path, persist=persist)
    if route == "lineups":
        lineups = get_lineup_stints(resolved_game_id, db_path=db_path, persist=persist)

    answer = build_routed_answer(
        route=route,
        snapshot=snapshot,
        advanced=advanced,
        runs=runs,
        possessions=possessions,
        players=players,
        lineups=lineups,
    )
    responses = [response for response in (snapshot, advanced, runs, possessions, players, lineups) if response]
    packet_ids = collect_packet_ids(*responses)
    packets = collect_packets(*responses)
    run_id = None
    if persist:
        run_id = persist_analysis_run(
            game_id=resolved_game_id,
            user_question=question,
            memo_markdown=answer,
            packet_ids=packet_ids,
            db_path=db_path,
        )
    evidence = (
        expand_evidence(resolved_game_id, packet_ids, db_path, max_items=max_evidence)
        if persist
        else expand_evidence_from_packets(packets, max_items=max_evidence)
    )
    return {
        "question": question,
        "route": route,
        "resolution": resolution_summary,
        "cache": cache["summary"],
        "answer_markdown": answer,
        "analysis": build_structured_analysis(answer, packets),
        "packet_ids": packet_ids,
        "analysis_run_id": run_id,
        "evidence": evidence,
        "persisted": persist,
        "tool_responses": {
            "snapshot": snapshot,
            "advanced": advanced,
            "runs": runs,
            "possessions": possessions,
            "players": players,
            "lineups": lineups,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--game-id")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--season")
    parser.add_argument("--season-type", default="Auto")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-evidence", type=int, default=4)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_agent(
        question=args.question,
        game_id=args.game_id,
        db_path=args.db,
        season=args.season,
        season_type=args.season_type,
        timeout=args.timeout,
        max_evidence=args.max_evidence,
        persist=args.persist,
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result["answer_markdown"])
        print()
        print("Evidence packets:")
        for packet_id in result["packet_ids"]:
            print(f"- {packet_id}")
        if result["evidence"]:
            print()
            print("Expanded evidence:")
            for item in result["evidence"]:
                print(f"- {item['title']}: {item['packet_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

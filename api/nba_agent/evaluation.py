"""Deterministic regression evaluation for representative postgame questions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.nba_agent.agent import run_agent

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "evals" / "postgame_cases.json"


def score_result(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    answer = result.get("answer_markdown", "").lower()
    checks = {
        "route": result.get("route") == case["expected_route"],
        "required_term": any(term.lower() in answer for term in case["required_terms_any"]),
        "forbidden_terms": not any(term.lower() in answer for term in case.get("forbidden_terms", [])),
        "evidence": len(result.get("packet_ids", [])) >= case["minimum_evidence"],
    }
    return {"case_id": case["id"], "passed": all(checks.values()), "checks": checks}


def run_evaluation(cases_path: Path = DEFAULT_CASES, *, live: bool = False) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text())
    results = [
        score_result(
            case,
            run_agent(case["question"], game_id=case["game_id"], persist=False)
            if live
            else case["fixture_result"],
        )
        for case in cases
    ]
    return {"mode": "live" if live else "fixture", "passed": sum(item["passed"] for item in results), "total": len(results), "results": results}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run against the local cache and allow on-demand NBA ingestion.")
    args = parser.parse_args()
    print(json.dumps(run_evaluation(live=args.live), indent=2))

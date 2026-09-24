"""Derive a trace view (a span tree) from a saved harness run's events.

Runs already record every model request, MCP call and verification with
elapsed times, so traces need no separate store and cover all past runs.
"""

from __future__ import annotations

# Events without their own span become zero-length markers in the tree.
ERROR_MARKERS = {"game_unresolved", "run_error", "verification_failed"}
# Expected harness corrections: the run recovers from these.
WARNING_MARKERS = {"draft_rejected", "evidence_conflict", "revision_requested"}
SKIP = {"mcp_result_received"}  # superseded by mcp_call_completed
EVENT_FIELDS = {"sequence", "kind", "at", "elapsed_seconds"}


def _payload(event: dict) -> dict:
    return {k: v for k, v in event.items() if k not in EVENT_FIELDS}


def _tokens(usage: dict | None) -> dict | None:
    if not usage:
        return None
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}


def build_spans(record: dict) -> list[dict]:
    """Spans in start order; each names its parent. Times are seconds from run start.

    status is ok, warning (a check failed and the harness corrected course), error or running.
    """
    events = record.get("events", [])
    end_of_run = max((e.get("elapsed_seconds") or 0 for e in events), default=0)
    running = record.get("status") == "running"
    spans: list[dict] = []

    def add(name, kind, start, *, parent, inputs=None, outputs=None, attributes=None, status="ok"):
        span = {"span_id": f"s{len(spans)}", "parent_id": parent, "name": name, "type": kind,
                "start": start, "end": None, "status": status, "inputs": inputs, "outputs": outputs,
                "attributes": attributes or {}, "tokens": None}
        spans.append(span)
        return span

    def close(span, end, status=None):
        span["end"] = end if end is not None else span["start"]
        if status:
            span["status"] = status

    usage = record.get("usage") or {}
    root = add("NBA MCP Harness", "run", 0, parent=None, inputs={"question": record.get("question"),
               "request": record.get("request"), "conversation": record.get("conversation") or None},
               outputs=(record.get("result") or {}).get("analysis"),
               attributes={k: record.get(k) for k in ("run_id", "status", "stop_reason", "model", "configuration",
                                                       "game_id", "conversation_id", "parent_run_id", "openai_trace_id",
                                                       "version", "limits", "usage", "unresolved_issues")})
    root["tokens"] = _tokens(usage)
    stack = [root]  # open grouping spans: run, verification, investigation
    model = mcp = None

    for event in events:
        kind, at = event.get("kind"), event.get("elapsed_seconds") or 0
        parent = stack[-1]["span_id"]
        if kind in SKIP:
            continue
        if kind == "model_requested":
            if event.get("purpose") == "verification" and stack[-1]["type"] != "verify":
                stack.append(add("Verify claims", "verify", at, parent=parent))
                parent = stack[-1]["span_id"]
            name = "Fact-check model" if event.get("purpose") == "verification" else "Decision model"
            model = add(name, "llm", at, parent=parent, inputs={"input": event.get("input"), "tools": event.get("tools")},
                        attributes={"purpose": event.get("purpose"), "model": record.get("model")})
        elif kind in {"model_response", "model_error"} and model is not None:
            model["outputs"] = ({"text": event.get("text"), "items": event.get("items")} if kind == "model_response"
                                else {"error": event.get("error")})
            model["attributes"].update({k: event[k] for k in ("response_id", "status", "model", "usage_estimated", "error")
                                        if k in event})
            model["tokens"] = _tokens(event.get("usage"))
            close(model, at, "error" if kind == "model_error" or event.get("status") != "completed" else None)
            model = None
        elif kind == "mcp_call_started":
            mcp = add(f"MCP {event.get('name')}", "tool", at, parent=parent, inputs=event.get("arguments"),
                      attributes={"tool": event.get("name"), "call_id": event.get("call_id"), "attempt": event.get("attempt")})
        elif kind in {"mcp_call_completed", "mcp_call_failed"} and mcp is not None:
            mcp["outputs"] = event.get("result") if kind == "mcp_call_completed" else {"error": event.get("error")}
            if "progress" in event:
                mcp["attributes"]["progress"] = event["progress"]
            close(mcp, at, "error" if kind == "mcp_call_failed" else None)
            mcp = None
        elif kind == "tool_rejected":
            close(add(f"MCP {event.get('name')} (rejected)", "tool", at, parent=parent, inputs={"arguments": event.get("arguments")},
                      outputs={"error": event.get("error")}, status="error"), at)
        elif kind in {"verification", "verification_failed"} and stack[-1]["type"] == "verify":
            group = stack.pop()
            group["outputs"] = event.get("review") or {"error": event.get("reason")}
            group["attributes"]["draft_index"] = event.get("draft_index")
            findings = (event.get("review") or {}).get("findings", [])
            failed = kind == "verification_failed" or any(f.get("classification") != "supported" for f in findings)
            close(group, at, "warning" if failed else None)
            if kind == "verification_failed":
                close(add("verification_failed", "event", at, parent=group["parent_id"], outputs=_payload(event), status="error"), at)
        elif kind == "investigation_started":
            stack.append(add("Investigation", "investigation", at, parent=parent, inputs={"needs": event.get("needs")}))
        elif kind == "investigation_completed" and stack[-1]["type"] == "investigation":
            group = stack.pop()
            group["outputs"] = {"new_packets": event.get("new_packets")}
            close(group, at)
        else:
            outputs = _payload(event)
            if kind == "answer_drafted" and event.get("draft_index") is not None:
                drafts = record.get("drafts") or []
                if event["draft_index"] < len(drafts):
                    outputs = {**outputs, "draft": drafts[event["draft_index"]]}
            close(add(kind, "event", at, parent=parent, outputs=outputs,
                      status="error" if kind in ERROR_MARKERS else "warning" if kind in WARNING_MARKERS else "ok"), at)

    # Anything still open was interrupted (or is still running).
    for span in spans:
        if span["end"] is None:
            close(span, end_of_run, "running" if running else "error")
    root["status"] = "running" if running else ("ok" if record.get("status") == "completed" else "error")
    return spans


def summarize(record: dict, created_at=None) -> dict:
    usage = record.get("usage") or {}
    resolution = record.get("resolution") or {}
    return {
        "run_id": record["run_id"], "question": record.get("question"), "status": record.get("status"),
        "stop_reason": record.get("stop_reason"), "model": record.get("model"), "configuration": record.get("configuration"),
        "game_id": record.get("game_id"), "game_label": resolution.get("label"),
        "conversation_id": record.get("conversation_id"), "parent_run_id": record.get("parent_run_id"),
        "openai_trace_id": record.get("openai_trace_id"), "duration_seconds": record.get("elapsed_seconds"),
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "model_turns": usage.get("model_turns"), "tool_calls": usage.get("tool_calls"),
        "created_at": (created_at.isoformat() if hasattr(created_at, "isoformat") else created_at)
                      or next((e.get("at") for e in record.get("events", [])), None),
    }

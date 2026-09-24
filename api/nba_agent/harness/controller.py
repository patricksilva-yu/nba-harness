"""Bounded MCP selection, evidence, verification, investigation and stopping."""

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from importlib.metadata import version

from pydantic import ValidationError
from agents import trace
from agents.tracing import custom_span
from agents.tracing.util import gen_trace_id

from api.nba_agent.db import DEFAULT_DB, get_storage
from api.nba_agent.storage import StorageError
from api.nba_agent.storage.repositories import HarnessRunRepository
from .contracts import FOLLOW_UP_LIMIT, Answer, Configuration, Limits, Review, VERSION
from .mcp_client import MCPBoundary, ToolFailure, local_client
from .model import ResponsesModel


class StopRun(Exception):
    def __init__(self, reason):
        self.reason = reason


def clean(value):
    """Redact credential fields and credentials embedded in user/provider strings."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"authorization|api.?key|password|secret|cookie|connection_string", k, re.I)
                else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        for key in ("OPENAI_API_KEY", "POSTGRES_CONNECTION_STRING"):
            secret = os.getenv(key)
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?:postgres(?:ql)?|https?)://[^\s/@]+:[^\s/@]+@[^\s]+", "[REDACTED_URL]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


class FollowUpError(ValueError):
    """The requested parent run cannot anchor a follow-up question."""


CONVERSATION_TURNS = 5


def follow_up_context(repository, parent_run_id: str) -> dict:
    """Carry a completed run's game, verified ledger and recent turns into a follow-up.

    A conversation stays on one game. Prior answers are model context only;
    inherited packets keep their provenance and are cited like any ledger entry.
    """
    parent = repository.get(parent_run_id)
    if parent is None:
        raise FollowUpError("parent_run_not_found")
    if parent["status"] != "completed":
        raise FollowUpError("parent_run_not_completed")
    result = parent.get("result", {})
    analysis = result.get("analysis", {})
    turn = {"run_id": parent["run_id"], "question": parent["question"], "stop_reason": parent["stop_reason"],
            "headline": analysis.get("headline"), "claims": [c["text"] for c in analysis.get("claims", [])]}
    return {
        "parent_run_id": parent["run_id"],
        "conversation_id": parent.get("conversation_id") or parent["run_id"],
        "conversation": [*parent.get("conversation", []), turn][-CONVERSATION_TURNS:],
        "game_id": parent.get("game_id"), "resolution": parent.get("resolution") or {}, "cache": parent.get("cache"),
        "evidence": {pid: {**entry, "inherited_from": entry.get("inherited_from", parent["run_id"])}
                     for pid, entry in parent.get("evidence", {}).items()} if parent.get("game_id") else {},
    }


# Small, display-relevant fields for live progress. The complete event stays in
# the durable trace; model inputs, raw outputs and tool results are not streamed.
PUBLIC_FIELDS = ("name", "arguments", "attempt", "progress", "duration_seconds", "error", "reason", "draft_index",
                 "claim_count", "has_headline", "needs", "new_packets", "purpose", "claim_indices", "packet_id",
                 "parent_run_id", "inherited_packets", "game_id", "run_id", "conversation_id")


def public_event(event: dict) -> dict:
    view = {k: event[k] for k in ("sequence", "kind", "at", "elapsed_seconds") if k in event}
    view.update({k: event[k] for k in PUBLIC_FIELDS if k in event})
    kind = event["kind"]
    if kind == "mcp_discovered":
        view["tools"] = [tool.get("name") for tool in event.get("tools", [])]
    elif kind == "mcp_call_completed":
        result = event.get("result") or {}
        view["evidence"] = [{"packet_id": p.get("packet_id"), "type": p.get("type")}
                            for p in result.get("evidence_packets", []) if isinstance(p, dict)]
        if event.get("name") == "resolve_game":
            view["game"] = result.get("game") or {k: v for k, v in (result.get("summary") or {}).items()
                                                  if k in ("game_id", "label", "game_date")}
    elif kind == "verification":
        view["findings"] = event.get("review", {}).get("findings", [])
    elif kind == "revision_requested":
        view["action"] = event.get("feedback", {}).get("action")
    return view


def public_run(record: dict) -> dict:
    """A run as the UI renders it: the result without the raw trace, plus public events."""
    view = {k: v for k, v in (record.get("result") or {}).items() if k != "trace"}
    view.update({"analysis_run_id": record["run_id"], "question": record["question"], "status": record["status"],
                 "stop_reason": record.get("stop_reason"), "conversation_id": record.get("conversation_id"),
                 "parent_run_id": record.get("parent_run_id"), "game_id": record.get("game_id"),
                 "limits": record.get("limits"), "events": [public_event(e) for e in record.get("events", [])]})
    return view


class Harness:
    def __init__(self, question, game_id, season, season_type, configuration, limits, model, repository,
                 follow_up=None, on_event=None, openai_trace_id=None):
        self.model, self.repository, self.limits = model, repository, limits
        self.on_event = on_event
        self.started = time.monotonic()
        follow_up = follow_up or {}
        self.requested_game = follow_up.get("game_id") or game_id
        self.configuration = configuration
        opening = {"question": question, "game_id": self.requested_game, "season": season, "season_type": season_type}
        if follow_up:
            opening["conversation"] = follow_up["conversation"]
            opening["game_resolved"] = bool(follow_up.get("game_id"))
            opening["game_data_cached"] = follow_up.get("cache") is not None
            # Details already fetched (such as a run's plays) travel with their packets.
            opening["evidence_ledger"] = {pid: {"packet": entry["packet"], **({"detail": entry["detail"]} if entry.get("detail") else {})}
                                          for pid, entry in follow_up["evidence"].items()}
        self.history = [{"role": "user", "content": encode(clean(opening))}]
        self.record = {
            "run_id": "harness_" + uuid.uuid4().hex, "status": "running", "stop_reason": None,
            "openai_trace_id": openai_trace_id,
            "version": VERSION, "prompt_version": VERSION, "allowlist_version": VERSION,
            "mcp_server": "nba-analyst/stdio", "model": model.name, "configuration": configuration,
            "packages": {name: version(name) for name in ("openai", "fastmcp", "mcp")},
            "question": clean(question), "request": clean({"game_id": game_id, "season": season, "season_type": season_type}),
            "conversation_id": follow_up.get("conversation_id"), "parent_run_id": follow_up.get("parent_run_id"),
            "conversation": follow_up.get("conversation", []),
            "limits": limits.model_dump(), "game_id": follow_up.get("game_id"),
            "resolution": follow_up.get("resolution") or {}, "cache": follow_up.get("cache"),
            "events": [], "evidence": dict(follow_up.get("evidence", {})), "drafts": [], "reviews": [], "unresolved_issues": [],
            "usage": {"model_turns": 0, "tool_calls": 0, "verification_passes": 0, "investigation_passes": 0,
                      "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0 if limits.input_usd_per_million is not None else None},
        }
        self.record["conversation_id"] = self.record["conversation_id"] or self.record["run_id"]
        self.completed = set()
        self.failures = {}
        self.no_progress = 0
        self.draft = None
        self.answer = Answer(headline=None, claims=[], limitations=[])
        self.investigating = False
        self.gathering_allowed = True
        self.investigation_evidence = 0
        self.reviewed = []  # (draft, review) pairs, in order
        self.trace_enabled = openai_trace_id is not None
        self.repository.create(self.record)

    def event(self, kind, **data):
        self.record["elapsed_seconds"] = round(time.monotonic() - self.started, 4)
        event = clean({"sequence": len(self.record["events"]) + 1, "kind": kind,
                       "at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": self.record["elapsed_seconds"], **data})
        self.record["events"].append(event)
        self.repository.save(clean(self.record))
        # Observers see an event only after its checkpoint is durable.
        if self.on_event:
            self.on_event(public_event(event))

    def check(self):
        if time.monotonic() - self.started >= self.limits.seconds:
            raise StopRun("time_limit")
        if self.no_progress >= 3:
            raise StopRun("no_progress")

    async def bounded(self, awaitable):
        remaining = self.limits.seconds - (time.monotonic() - self.started)
        return await asyncio.wait_for(awaitable, timeout=max(.001, min(remaining, self.limits.operation_seconds)))

    def feedback(self, message):
        self.history.append({"role": "user", "content": encode({"harness_feedback": message})})

    def revision_context(self, feedback):
        """Give revisions one copy of the ledger instead of replaying bulky tool transcripts."""
        evidence = {pid: {"packet": entry["packet"],
                          **({"detail": entry["detail"]} if entry.get("detail") else {})}
                    for pid, entry in self.record["evidence"].items()}
        self.history = [{"role": "user", "content": encode(clean({
            "question": self.record["question"], "game_id": self.record["game_id"],
            "game_resolved": True, "game_data_cached": True,
            "conversation": self.record["conversation"],
            "evidence_ledger": evidence, "harness_feedback": feedback,
        }))}]

    async def model_turn(self, tools, *, review=False, history=None):
        self.check()
        usage = self.record["usage"]
        if usage["model_turns"] >= self.limits.model_turns:
            raise StopRun("iteration_limit")
        messages = history if history is not None else self.history
        # JSON bytes substantially overcount model tokens. Reserve roughly one
        # token per 2.6 bytes, then account for the fixed instructions separately.
        # The provider's actual usage is charged after every completed call.
        request_bytes = len(encode([messages, tools, Answer.model_json_schema(), Review.model_json_schema()]).encode())
        reserve_input = (request_bytes * 5 + 12) // 13 + 2048
        reserve_output = self.limits.output_tokens
        if usage["input_tokens"] + usage["output_tokens"] + reserve_input + reserve_output > self.limits.total_tokens:
            raise StopRun("token_limit")
        if self.limits.max_cost_usd is not None:
            reserve_cost = (reserve_input * self.limits.input_usd_per_million + reserve_output * self.limits.output_usd_per_million) / 1e6
            if usage["estimated_cost_usd"] + reserve_cost > self.limits.max_cost_usd:
                raise StopRun("cost_limit")
        usage["model_turns"] += 1
        self.event("model_requested", purpose="verification" if review else "decision",
                   input=[item for item in messages if item.get("type") != "reasoning"], tools=[t["name"] for t in tools])
        started = time.monotonic()
        try:
            with (custom_span("Fact-check model" if review else "Decision model",
                              data={"run_id": self.record["run_id"], "model": self.model.name,
                                    "purpose": "verification" if review else "decision"})
                  if self.trace_enabled else nullcontext()) as span:
                response = await self.bounded(self.model.respond(messages, tools, review=review,
                                                                  max_output_tokens=reserve_output))
                if span is not None:
                    span.span_data.data.update(response_id=response.get("id"), status=response.get("status"),
                                               usage=response.get("usage"),
                                               output_types=[item.get("type") for item in response.get("items", [])])
        except Exception as exc:
            # A timed out request may have been billed. Reserve worst-case usage;
            # do not replay unknown model outcomes automatically.
            self.account({"input_tokens": reserve_input, "output_tokens": reserve_output})
            self.event("model_error", error=type(exc).__name__, usage_estimated=True,
                       duration_seconds=time.monotonic() - started)
            raise StopRun("time_limit" if isinstance(exc, TimeoutError) else "error") from exc
        reported = response.get("usage")
        self.account(reported or {"input_tokens": reserve_input, "output_tokens": reserve_output})
        self.event("model_response", response_id=response.get("id"), status=response.get("status"),
                   model=response.get("model", self.model.name),
                   items=[item for item in response["items"] if item.get("type") != "reasoning"],
                   text=response["text"], usage=reported, usage_estimated=reported is None,
                   duration_seconds=time.monotonic() - started)
        self.check()
        if response.get("status") != "completed":
            raise StopRun("insufficient_evidence")
        if usage["input_tokens"] + usage["output_tokens"] > self.limits.total_tokens:
            raise StopRun("token_limit")
        if self.limits.max_cost_usd is not None and usage["estimated_cost_usd"] > self.limits.max_cost_usd:
            raise StopRun("cost_limit")
        return response

    def account(self, counts):
        usage = self.record["usage"]
        for key in ("input_tokens", "output_tokens"):
            usage[key] += counts[key]
        if self.limits.input_usd_per_million is not None:
            usage["estimated_cost_usd"] = (usage["input_tokens"] * self.limits.input_usd_per_million + usage["output_tokens"] * self.limits.output_usd_per_million) / 1e6

    def policy(self, name, arguments):
        if not self.gathering_allowed:
            raise ToolFailure("evidence_gathering_closed")
        game = self.record["game_id"]
        if name == "resolve_game":
            if game:
                raise ToolFailure("game_already_resolved")
            if arguments.get("game_id") != self.requested_game:
                raise ToolFailure("use_requested_game_id_or_null")
        else:
            if not game or arguments.get("game_id") != game:
                raise ToolFailure("resolve_game_first_or_wrong_game")
            if name in {"get_game_analysis_context", "get_game_window", "get_evidence_detail"} and self.record["cache"] is None:
                raise ToolFailure("ensure_game_data_first")
            if name == "get_evidence_detail" and arguments.get("packet_id") not in self.record["evidence"]:
                raise ToolFailure("unknown_evidence_packet")
        # Valid section names come from the discovered MCP schema, checked in MCPBoundary.validate.
        if name == "get_game_analysis_context" and not arguments.get("sections"):
            raise ToolFailure("select_explicit_sections")

    async def tool(self, boundary, call):
        self.check()
        name, raw = call.get("name"), call.get("arguments", "")
        try:
            arguments = json.loads(raw)
            if not isinstance(arguments, dict):
                raise ToolFailure("invalid_arguments")
            boundary.validate(name, arguments)
            self.policy(name, arguments)
            normalized = {**arguments}
            if isinstance(normalized.get("sections"), list):
                normalized["sections"] = sorted(set(normalized["sections"]))
            key = encode([name, normalized])
            if key in self.completed:
                raise ToolFailure("duplicate_call")
            if self.failures.get(key, 0) > self.limits.retries:
                raise ToolFailure("retry_limit")
        except (ValueError, ToolFailure) as exc:
            error = str(exc) if isinstance(exc, ToolFailure) else "invalid_arguments_json"
            self.no_progress += 1
            self.event("tool_rejected", name=name, arguments=raw, error=error)
            return {"error": error}
        for attempt in range(self.limits.retries + 1):
            self.check()
            if self.record["usage"]["tool_calls"] >= self.limits.tool_calls:
                raise StopRun("tool_limit")
            self.record["usage"]["tool_calls"] += 1
            self.event("mcp_call_started", name=name, arguments=arguments, call_id=call.get("call_id"), attempt=attempt + 1)
            started = time.monotonic()
            try:
                with (custom_span(f"MCP {name}", data={"run_id": self.record["run_id"],
                                                        "arguments": clean(arguments)})
                      if self.trace_enabled else nullcontext()) as span:
                    result = clean(await self.bounded(boundary.call(name, arguments)))
                    if span is not None:
                        span.span_data.data.update(summary=result.get("summary"),
                                                   packet_count=len(result.get("evidence_packets", [])))
                if len(encode(result).encode()) > 500_000:
                    raise ToolFailure("tool_result_too_large")
                self.event("mcp_result_received", name=name, arguments=arguments, result=result,
                           duration_seconds=time.monotonic() - started)
                progress = self.accept(name, arguments, result)
            except (ToolFailure, TimeoutError, OSError) as exc:
                self.failures[key] = self.failures.get(key, 0) + 1
                error = str(exc) if isinstance(exc, ToolFailure) else type(exc).__name__
                self.event("mcp_call_failed", name=name, call_id=call.get("call_id"), arguments=arguments,
                           error=error, duration_seconds=time.monotonic() - started)
                # Retry only read operations with a known transient failure.
                if isinstance(exc, (TimeoutError, OSError)) and name != "ensure_game_data" and self.failures[key] <= self.limits.retries:
                    self.event("retry", name=name, reason=error)
                    continue
                self.no_progress += 1
                return {"error": error}
            self.completed.add(key)
            self.no_progress = 0 if progress else self.no_progress + 1
            self.event("mcp_call_completed", name=name, arguments=arguments, result=result,
                       duration_seconds=time.monotonic() - started, progress=progress)
            return result
        return {"error": "retry_limit"}

    def accept(self, name, arguments, result):
        progress = False
        summary = result["summary"]
        if name == "resolve_game":
            game = summary.get("game_id")
            if not game:
                self.record["resolution"] = summary
                self.event("mcp_call_completed", name=name, arguments=arguments, result=result, progress=False)
                self.event("game_unresolved", result=result)
                raise StopRun("insufficient_evidence")
            if not isinstance(game, str) or (self.requested_game and game != self.requested_game):
                raise ToolFailure("wrong_game_result")
            self.record["game_id"], self.record["resolution"] = game, summary
            progress = True
        elif summary.get("game_id") != self.record["game_id"]:
            raise ToolFailure("wrong_game_result")
        if name == "ensure_game_data":
            progress = self.record["cache"] is None
            self.record["cache"] = summary
        packets = result.get("evidence_packets", [])
        if not isinstance(packets, list):
            raise ToolFailure("invalid_evidence_packets")
        for packet in packets:
            if not isinstance(packet, dict) or not all(packet.get(k) for k in ("packet_id", "type", "source", "confidence")):
                raise ToolFailure("invalid_evidence_packet")
            if not isinstance(packet["packet_id"], str):
                raise ToolFailure("invalid_packet_id")
            if not isinstance(packet["source"], dict) or not isinstance(packet["source"].get("provider"), str):
                raise ToolFailure("invalid_packet_source")
            if packet.get("game_id", self.record["game_id"]) != self.record["game_id"]:
                raise ToolFailure("wrong_game_packet")
        for packet in packets:
            packet_id = packet["packet_id"]
            prior = self.record["evidence"].get(packet_id)
            if prior and prior["packet"] != packet:
                self.event("evidence_conflict", packet_id=packet_id, prior=prior["packet"], incoming=packet)
                raise ToolFailure("conflicting_packet")
        for packet in packets:
            packet_id = packet["packet_id"]
            if packet_id in self.record["evidence"]:
                continue
            progress = True
            self.record["evidence"][packet_id] = {"packet": packet, "game_id": self.record["game_id"],
                "tool": name, "arguments": arguments, "received_at": datetime.now(timezone.utc).isoformat(),
                "result_event": len(self.record["events"])}
        if name == "get_evidence_detail":
            if summary.get("resolution_status") == "not_found_or_not_yet_persisted":
                raise ToolFailure("evidence_detail_unavailable")
            if summary.get("packet_id") != arguments["packet_id"]:
                raise ToolFailure("wrong_packet_result")
            progress = self.record["evidence"][arguments["packet_id"]].get("detail") != result
            self.record["evidence"][arguments["packet_id"]]["detail"] = result
        return progress

    async def verify(self, draft):
        self.record["usage"]["verification_passes"] += 1
        claims = draft.reviewable()
        cited = {pid for claim in claims for pid in claim.packet_ids}
        roles = ["claim"] * len(draft.claims) + ["headline"] * (draft.headline is not None)
        history = [{"role": "user", "content": encode({"question": self.record["question"],
            "claims": [{"claim_index": i, "role": role, **c.model_dump()} for i, (role, c) in enumerate(zip(roles, claims))],
            "evidence": {pid: self.record["evidence"][pid] for pid in cited}})}]
        with (custom_span("Verify claims", data={"run_id": self.record["run_id"],
                                                 "claim_count": len(claims)})
              if self.trace_enabled else nullcontext()) as span:
            response = await self.model_turn([], review=True, history=history)
            review = Review.model_validate_json(response["text"])
            if span is not None:
                span.span_data.data["classifications"] = [finding.classification for finding in review.findings]
        indices = [f.claim_index for f in review.findings]
        if sorted(indices) != list(range(len(claims))):
            raise ValueError("incomplete_verification")
        self.record["reviews"].append(review.model_dump())
        self.reviewed.append((draft, review))
        self.event("verification", draft_index=len(self.record["drafts"]) - 1, review=review.model_dump())
        return review

    async def execute(self, boundary):
        tools = await self.bounded(boundary.discover())
        self.event("mcp_discovered", tools=tools,
                   schema_hash=hashlib.sha256(encode(tools).encode()).hexdigest())
        while True:
            response = await self.model_turn(tools if self.gathering_allowed else [])
            calls = [item for item in response["items"] if item.get("type") == "function_call"]
            self.history.extend(response["items"])
            if calls:
                for call in calls:
                    result = await self.tool(boundary, call)
                    self.history.append({"type": "function_call_output", "call_id": call["call_id"], "output": encode(result)})
                continue
            try:
                draft = Answer.model_validate_json(response["text"])
            except ValidationError:
                self.event("draft_rejected", reason="invalid_answer_schema")
                self.feedback("Return the required structured answer schema.")
                self.no_progress += 1
                continue
            self.record["drafts"].append(draft.model_dump())
            self.event("answer_drafted", draft_index=len(self.record["drafts"]) - 1,
                       claim_count=len(draft.claims), has_headline=draft.headline is not None)
            if not draft.claims:
                self.answer = draft
                raise StopRun("insufficient_evidence")
            if draft.headline is None:
                self.event("draft_rejected", reason="missing_headline")
                self.feedback("Add a cited headline that summarizes the claims.")
                self.no_progress += 1
                continue
            missing = [i for i, c in enumerate(draft.reviewable()) if not c.packet_ids or any(pid not in self.record["evidence"] for pid in c.packet_ids)]
            if missing or not self.record["game_id"]:
                self.event("draft_rejected", reason="missing_evidence", claim_indices=missing)
                self.feedback({"missing_evidence_claims": missing, "headline_index": len(draft.claims),
                               "action": "Gather MCP evidence or remove unsupported claims."})
                self.no_progress += 1
                continue
            if self.configuration == "basic":
                self.answer = draft
                self.answer.limitations.append("Basic configuration: claim support has not been verified.")
                raise StopRun("answered_unverified")
            if self.investigating:
                added = len(self.record["evidence"]) - self.investigation_evidence
                self.event("investigation_completed", new_packets=added)
                self.investigating = False
            self.gathering_allowed = False
            if self.record["usage"]["verification_passes"] >= self.limits.verification_passes:
                raise StopRun("verification_limit")
            try:
                review = await self.verify(draft)
            except (ValidationError, ValueError):
                self.event("verification_failed", reason="invalid_verifier_output")
                self.no_progress += 1
                self.feedback("Verifier failed to return a complete valid review; submit a supported draft again.")
                continue
            failed = [f for f in review.findings if f.classification != "supported"]
            self.record["unresolved_issues"] = [f.model_dump() for f in failed]
            if not failed:
                self.answer = draft
                raise StopRun("supported")
            self.no_progress += 1
            feedback = {"review": review.model_dump(), "headline_index": len(draft.claims),
                        "action": "Revise, qualify or remove failed claims; then submit a new draft."}
            if self.configuration == "investigation" and any(f.evidence_need for f in failed):
                if self.record["usage"]["investigation_passes"] < self.limits.investigation_passes:
                    self.record["usage"]["investigation_passes"] += 1
                    self.investigating = True
                    self.gathering_allowed = True
                    self.investigation_evidence = len(self.record["evidence"])
                    feedback["action"] = "Use the smallest new MCP request to address these evidence needs, then revise the draft. Do not repeat prior calls."
                    self.event("investigation_started", needs=[f.evidence_need for f in failed])
            self.event("revision_requested", feedback=feedback)
            self.revision_context(feedback)

    def verified_follow_ups(self):
        """Final claims with only follow-ups that passed the last review, at most FOLLOW_UP_LIMIT.

        Unverified (basic) answers carry none: a follow-up could smuggle in a claim.
        """
        passed = set()
        if self.reviewed and self.reviewed[-1][0] is self.answer:
            passed = {f.claim_index for f in self.reviewed[-1][1].findings
                      if f.classification == "supported" and f.follow_up_ok}
        claims = []
        for index, claim in enumerate(self.answer.claims):
            keep = claim.follow_up and index in passed and sum(c.follow_up is not None for c in claims) < FOLLOW_UP_LIMIT
            claims.append(claim.model_copy(update={"follow_up": claim.follow_up if keep else None}))
        return claims

    def removed_claims(self):
        """Claims a review rejected that are absent from the final answer."""
        final = {claim.text for claim in self.answer.claims}
        removed = {}
        for draft, review in self.reviewed:
            for finding in review.findings:
                if finding.classification == "supported" or finding.claim_index >= len(draft.claims):
                    continue
                text = draft.claims[finding.claim_index].text
                if text not in final:
                    removed[text] = {"text": text, "classification": finding.classification, "reason": finding.reason}
        return list(removed.values())

    def finish(self, reason):
        if reason not in {"supported", "answered_unverified"}:
            self.answer = Answer(headline=None, claims=[], limitations=[*self.answer.limitations,
                f"The harness stopped with {reason}; it could not establish a supported answer."])
        claims = self.verified_follow_ups()
        headline = self.answer.headline.model_copy(update={"follow_up": None}) if self.answer.headline else None
        removed = self.removed_claims() if reason == "supported" else []
        citations = [{"packet_id": pid, "claim": claim.text} for claim in claims for pid in claim.packet_ids]
        packet_ids = list(dict.fromkeys([c["packet_id"] for c in citations] + (headline.packet_ids if headline else [])))
        analysis = {"headline": headline.text if headline else None, "headline_claim": headline.model_dump() if headline else None,
                    "summary": " ".join(c.text for c in claims),
                    "deciding_factors": [], "player_findings": [], "decisive_windows": [],
                    "limitations": self.answer.limitations, "citations": citations,
                    "claims": [c.model_dump() for c in claims], "removed_claims": removed}
        markdown = f"# {headline.text if headline else 'NBA postgame analysis'}\n\n" + "\n\n".join(c.text for c in claims)
        if self.answer.limitations:
            markdown += "\n\n## Limitations\n" + "\n".join("- " + x for x in self.answer.limitations)
        result = {"question": self.record["question"], "mode": "mcp_harness", "route": "mcp_harness",
            "openai_trace_id": self.record["openai_trace_id"],
            "configuration": self.configuration, "resolution": self.record["resolution"], "cache": self.record["cache"],
            "game_id": self.record["game_id"], "conversation_id": self.record["conversation_id"],
            "parent_run_id": self.record["parent_run_id"],
            "analysis": analysis, "answer_markdown": markdown, "packet_ids": packet_ids,
            "analysis_run_id": self.record["run_id"], "persisted": True, "stop_reason": reason,
            "evidence": [{"packet_id": pid, "payload": self.record["evidence"][pid]} for pid in packet_ids],
            "warnings": self.answer.limitations, "usage": self.record["usage"]}
        self.record["result"] = clean(result)
        self.record["status"] = "failed" if reason in {"error", "cancelled"} else "completed"
        self.record["stop_reason"] = reason
        self.event("run_stopped", reason=reason)
        return {**clean(result), "trace": clean(self.record)}


async def run_harness(question: str, game_id: str | None = None, season: str | None = None,
                      season_type: str = "Auto", configuration: Configuration = "investigation",
                      db_path: Path = DEFAULT_DB, *, limits: Limits | None = None, model=None,
                      mcp_client=None, repository=None, follow_up: dict | None = None, on_event=None) -> dict:
    """Every accepted run is persisted, including bounded failures and cancellation.

    `follow_up` comes from `follow_up_context`; `on_event` receives each durable
    event's public view as it happens.
    """
    if configuration not in {"basic", "verification", "investigation"}:
        raise ValueError("Unknown harness configuration")
    if follow_up and follow_up.get("game_id") and game_id and game_id != follow_up["game_id"]:
        raise FollowUpError("follow_up_game_mismatch")
    limits = limits or Limits.from_environment()
    owned_model = model is None
    model = model or ResponsesModel()
    trace_enabled = isinstance(model, ResponsesModel)
    repository = repository or HarnessRunRepository(get_storage(db_path))
    harness = None
    openai_trace_id = gen_trace_id() if trace_enabled else None
    try:
        harness = Harness(question, game_id, season, season_type, configuration, limits, model, repository,
                          follow_up=follow_up, on_event=on_event, openai_trace_id=openai_trace_id)
        with (trace("NBA MCP Harness", trace_id=openai_trace_id,
                    group_id=harness.record["conversation_id"],
                    metadata={"run_id": harness.record["run_id"],
                              "game_id": harness.record["game_id"],
                              "configuration": configuration}) if trace_enabled else nullcontext()):
            harness.event("run_started", run_id=harness.record["run_id"], conversation_id=harness.record["conversation_id"],
                          parent_run_id=harness.record["parent_run_id"], game_id=harness.record["game_id"],
                          inherited_packets=len(harness.record["evidence"]))
            reason = "error"
            try:
                async with asyncio.timeout(limits.seconds):
                    async with (mcp_client or local_client(db_path, limits.operation_seconds)) as client:
                        await harness.execute(MCPBoundary(client))
            except StopRun as exc:
                reason = exc.reason
            except asyncio.CancelledError:
                harness.finish("cancelled")
                raise
            except TimeoutError:
                reason = "time_limit"
            except StorageError:
                raise
            except Exception as exc:
                harness.event("run_error", error=type(exc).__name__)
            result = harness.finish(reason)
            if trace_enabled:
                with custom_span("Run outcome", data={"run_id": harness.record["run_id"],
                                                      "stop_reason": reason,
                                                      "usage": harness.record["usage"]}):
                    pass
            return result
    finally:
        if owned_model:
            await model.close()

"""Request models for the NBA analyst API."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=8000)
    mode: Literal["mcp_harness", "responses_tools", "deterministic", "local_agents_sdk_mcp", "remote_responses_mcp"] = "mcp_harness"
    harness_configuration: Literal["basic", "verification", "investigation"] = "investigation"
    game_id: str | None = None
    # A completed harness run to continue; follow-ups stay on that run's game.
    parent_run_id: str | None = Field(default=None, max_length=100)
    season: str | None = None
    season_type: str = "Auto"
    max_evidence: int = Field(default=4, ge=0, le=12)
    persist: bool = False


class IngestionRequest(BaseModel):
    game_id: str = Field(min_length=10, max_length=10)
    season: str | None = None
    season_type: str = "Playoffs"
    force_refresh: bool = False

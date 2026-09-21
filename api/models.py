"""Request models for the NBA analyst API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3)
    mode: str = "deterministic"
    game_id: str | None = None
    season: str | None = None
    season_type: str = "Auto"
    max_evidence: int = Field(default=4, ge=0, le=12)
    persist: bool = False


class IngestionRequest(BaseModel):
    game_id: str = Field(min_length=10, max_length=10)
    season: str | None = None
    season_type: str = "Playoffs"
    force_refresh: bool = False

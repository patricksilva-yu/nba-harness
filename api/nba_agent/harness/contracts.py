"""Versioned output and resource contracts; independent of model and transport."""

from typing import Literal
import os

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "mcp-harness-v3"
FOLLOW_UP_LIMIT = 3
ALLOWLIST = ("resolve_game", "ensure_game_data", "get_game_analysis_context", "get_game_window", "get_evidence_detail")
Configuration = Literal["basic", "verification", "investigation"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Claim(StrictModel):
    text: str
    packet_ids: list[str]
    # A question this claim invites; verified separately and dropped if it fails.
    follow_up: str | None


class Answer(StrictModel):
    # The headline is a claim: it cites packets and is verified like any other.
    headline: Claim | None
    claims: list[Claim]
    limitations: list[str]

    def reviewable(self) -> list[Claim]:
        """Claims in verifier index order; the headline, when present, is last."""
        return [*self.claims, *([self.headline] if self.headline else [])]


class Finding(StrictModel):
    claim_index: int
    classification: Literal["supported", "unsupported", "conflicting", "insufficient"]
    reason: str
    evidence_need: str
    # False when the claim's follow-up question asserts anything unverified.
    follow_up_ok: bool


class Review(StrictModel):
    findings: list[Finding]


class Limits(StrictModel):
    model_turns: int = Field(default=12, ge=1, le=30)
    tool_calls: int = Field(default=12, ge=1, le=40)
    verification_passes: int = Field(default=3, ge=0, le=6)
    investigation_passes: int = Field(default=2, ge=0, le=5)
    retries: int = Field(default=1, ge=0, le=2)
    seconds: float = Field(default=180, gt=0, le=600)
    operation_seconds: float = Field(default=45, gt=0, le=120)
    total_tokens: int = Field(default=200000, ge=1)
    output_tokens: int = Field(default=4000, ge=1, le=16000)
    max_cost_usd: float | None = Field(default=None, gt=0)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)

    @classmethod
    def from_environment(cls):
        return cls.model_validate({field: os.environ[f"NBA_HARNESS_{field.upper()}"]
                                   for field in cls.model_fields if os.getenv(f"NBA_HARNESS_{field.upper()}")})

    @model_validator(mode="after")
    def require_rates(self):
        rates = (self.input_usd_per_million, self.output_usd_per_million)
        if (self.max_cost_usd is not None or any(x is not None for x in rates)) and any(x is None for x in rates):
            raise ValueError("Cost accounting requires both explicit model token rates")
        return self

"""Agent protocol + AgentVote + MetaDecision + AgentContext schemas.

Pinned shapes consumed by every agent in polymarket_bot.agents and by the
EnsembleStrategy in polymarket_bot.strategies.ensemble. AgentContext is the
typed view of per-window state — agents do NOT parse raw payloads, the
ensemble strategy builds context from MarketEvents and hands it over.

Pydantic enforces output shape on every Anthropic response via
client.messages.parse(); a refusal or schema mismatch surfaces as None and
the ensemble's Tier-3 fallback (decision #6) takes over.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Side = Literal["UP", "DOWN"]
VoteSide = Literal["UP", "DOWN", "ABSTAIN"]

# Phase 18B observability tag. Every `AnthropicAdapter.parse` /
# `MetaDecider.decide` round-trip emits one of these so the ensemble
# log can attribute meta=None outcomes to a specific failure mode.
# Values defined in design/phase-18b-meta-observability.md.
MetaOutcome = Literal[
    "ok",
    "api_error",
    "refusal",
    "no_text",
    "validation_failed",
    "invariant_violated",
    "exception",
    "no_meta_call",
    "timeout",
]


class AgentContext(BaseModel):
    """Per-window snapshot fed to each specialist + meta-decider.

    Built once per fire-decision by EnsembleStrategy from the latest
    MarketEvents in the current window. Designed to be a stable shape that
    JSON-serialises deterministically (sort keys; no datetime objects) so
    the prompt cache stays warm across windows — only the field VALUES
    change, not the structure.
    """

    window_ts: int
    now_ts_utc_ns: int
    seconds_to_close: int

    spot_now: float
    spot_at_window_open: float
    spot_recent_60s: list[float] = Field(default_factory=list)

    oracle_last: float
    oracle_at_window_open: float
    oracle_age_s: float

    best_bid_up: float | None = None
    best_ask_up: float | None = None
    best_bid_down: float | None = None
    best_ask_down: float | None = None
    book_imbalance: float | None = None

    composite_pct: float


class AgentVote(BaseModel):
    """One specialist agent's verdict. Validated by pydantic on parse.

    ``rationale`` upper bound is generous (2000 chars) since the verdict
    fields (side + confidence) are what the meta-decider uses; the
    rationale is narrative and rarely the deciding signal. Anthropic's
    structured-output API doesn't enforce ``max_length`` anyway (see
    AnthropicAdapter._strict_object_schema), so the limit only serves
    as a sanity check after parsing. Audit 2026-05-10: 18 votes were
    rejected at the old 240-char limit (rationales 250-400 chars
    typical); each rejection silently dropped a vote and contributed
    to the 23% null-meta rate that broke gate-mode.
    """

    side: VoteSide
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=2000)


class MetaDecision(BaseModel):
    """Meta-decider's final action. ABSTAIN ⇒ ensemble does not fire.

    Same rationale-bound rationale as AgentVote: bumped 400 → 2000 to
    accommodate the meta-decider's slightly longer narrative + the
    same audit lesson.
    """

    action: Literal["FIRE", "ABSTAIN"]
    side: Side | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=2000)


@runtime_checkable
class Agent(Protocol):
    """Contract for the 3 specialist agents."""

    name: str
    model: str

    async def vote(self, ctx: AgentContext) -> AgentVote | None: ...


@runtime_checkable
class MetaAgent(Protocol):
    """Contract for the meta-decider.

    `votes` is keyed by specialist agent name ("orderbook", "oracle_gap",
    "momentum"). The dict may be missing entries for specialists that
    failed to vote (refusal / schema fail / budget cap); EnsembleStrategy
    only invokes the meta when at least 2 votes are present per
    decision #6's Tier-3 fallback rule.
    """

    name: str
    model: str

    async def decide(
        self, ctx: AgentContext, votes: dict[str, AgentVote]
    ) -> tuple[MetaDecision | None, MetaOutcome]: ...


# ---------------------------------------------------------------------------
# AnthropicAdapter dependency-injection types
# ---------------------------------------------------------------------------

ParseFn = Callable[..., Awaitable[tuple[BaseModel | None, "TokenUsage", MetaOutcome]]]
"""Async callable that takes Anthropic-API kwargs + returns (parsed, usage, outcome)."""


class TokenUsage(BaseModel):
    """Per-request token accounting — populated from Anthropic's usage block."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


__all__ = [
    "Agent",
    "AgentContext",
    "AgentVote",
    "MetaAgent",
    "MetaDecision",
    "MetaOutcome",
    "ParseFn",
    "Side",
    "TokenUsage",
    "VoteSide",
]

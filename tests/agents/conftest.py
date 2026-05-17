"""Shared fakes for tests/agents — FakeAdapter, helpers, sample contexts.

No real Anthropic API calls. FakeAdapter is constructed with a queue of
canned responses; each call to .parse() pops the next response. Tests can
also assert on the kwargs the adapter was called with via .calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from polymarket_bot.agents.budget import BudgetTracker
from polymarket_bot.agents.protocol import (
    AgentContext,
    AgentVote,
    MetaOutcome,
    TokenUsage,
)

# Phase 18B: the adapter contract is now a 3-tuple. The fake accepts
# either a 2-tuple (legacy — outcome auto-derived from `parsed is None`)
# or a 3-tuple (explicit — for tests asserting on a specific tag).
FakeResponse = (
    tuple[BaseModel | None, TokenUsage] | tuple[BaseModel | None, TokenUsage, MetaOutcome]
)


@dataclass
class FakeCall:
    model: str
    system: list[dict[str, object]]
    user: str
    output_format: type[BaseModel]
    thinking: dict[str, object] | None
    effort: str | None
    max_tokens: int


@dataclass
class FakeAdapter:
    """Mocks AnthropicAdapter.parse for unit tests.

    Construct with a list of (parsed_or_None, usage[, outcome]) tuples;
    each .parse() call pops the next entry. If a 2-tuple is supplied,
    outcome auto-derives as "ok" when parsed is set, "validation_failed"
    when parsed is None. Records every call's kwargs in .calls so tests
    can assert on the wire shape.
    """

    responses: list[FakeResponse] = field(default_factory=list)
    calls: list[FakeCall] = field(default_factory=list)
    budget: BudgetTracker = field(default_factory=lambda: BudgetTracker(hard_limit_usd=100.0))

    async def parse(
        self,
        *,
        model: str,
        system: list[dict[str, object]],
        user: str,
        output_format: type[BaseModel],
        thinking: dict[str, object] | None = None,
        effort: str | None = None,
        max_tokens: int = 1024,
    ) -> tuple[BaseModel | None, TokenUsage, MetaOutcome]:
        self.calls.append(
            FakeCall(
                model=model,
                system=system,
                user=user,
                output_format=output_format,
                thinking=thinking,
                effort=effort,
                max_tokens=max_tokens,
            )
        )
        if not self.responses:
            return None, TokenUsage(), "validation_failed"
        r = self.responses.pop(0)
        if len(r) == 3:
            return r[0], r[1], r[2]
        parsed, usage = r
        outcome: MetaOutcome = "ok" if parsed is not None else "validation_failed"
        return parsed, usage, outcome


def sample_context(**overrides: Any) -> AgentContext:
    """Build a sample AgentContext for tests; override any field via kwargs."""
    base = {
        "window_ts": 1_715_000_100,
        "now_ts_utc_ns": (1_715_000_100 + 280) * 1_000_000_000,
        "seconds_to_close": 20,
        "spot_now": 80_000.0,
        "spot_at_window_open": 79_900.0,
        "spot_recent_60s": [79_900.0, 79_950.0, 80_000.0],
        "oracle_last": 79_980.0,
        "oracle_at_window_open": 79_900.0,
        "oracle_age_s": 12.0,
        "best_bid_up": 0.55,
        "best_ask_up": 0.57,
        "best_bid_down": 0.43,
        "best_ask_down": 0.45,
        "book_imbalance": 0.15,
        "composite_pct": 0.30,
    }
    base.update(overrides)
    return AgentContext(**base)


def sample_vote(side: str = "UP", confidence: float = 0.7, rationale: str = "test") -> AgentVote:
    return AgentVote(side=side, confidence=confidence, rationale=rationale)  # type: ignore[arg-type]

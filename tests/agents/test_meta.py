"""Tests for polymarket_bot.agents.meta.MetaDecider."""

from __future__ import annotations

import json

from polymarket_bot.agents.meta import MetaDecider
from polymarket_bot.agents.protocol import (
    MetaDecision,
    TokenUsage,
)
from tests.agents.conftest import FakeAdapter, sample_context, sample_vote


def _meta_decision(action: str, side: str | None, confidence: float) -> MetaDecision:
    return MetaDecision(
        action=action,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        confidence=confidence,
        rationale="test",
    )


async def test_meta_uses_sonnet_with_adaptive_and_effort() -> None:
    adapter = FakeAdapter(responses=[(_meta_decision("FIRE", "UP", 0.7), TokenUsage())])
    meta = MetaDecider(adapter)
    assert meta.model == "claude-sonnet-4-6"

    decision = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote("UP", 0.7), "oracle_gap": sample_vote("UP", 0.8)},
    )

    assert isinstance(decision, MetaDecision)
    call = adapter.calls[0]
    assert call.model == "claude-sonnet-4-6"
    assert call.thinking == {"type": "adaptive"}
    assert call.effort == "medium"


async def test_meta_serialises_votes_with_agent_names() -> None:
    adapter = FakeAdapter(responses=[(_meta_decision("FIRE", "UP", 0.7), TokenUsage())])
    meta = MetaDecider(adapter)
    await meta.decide(
        sample_context(),
        {
            "orderbook": sample_vote("UP", 0.7, "imbalance"),
            "oracle_gap": sample_vote("ABSTAIN", 0.4, "tiny gap"),
        },
    )
    call = adapter.calls[0]
    payload = json.loads(call.user)
    assert "context" in payload
    assert "votes" in payload
    vote_agents = sorted(v["agent"] for v in payload["votes"])
    assert vote_agents == ["oracle_gap", "orderbook"]


async def test_meta_rejects_fire_without_side() -> None:
    """Pydantic accepts MetaDecision(FIRE, side=None) but the agent layer
    enforces the invariant that FIRE must have a side."""
    bad = MetaDecision(action="FIRE", side=None, confidence=0.7, rationale="oops")
    adapter = FakeAdapter(responses=[(bad, TokenUsage())])
    meta = MetaDecider(adapter)
    decision = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None  # invariant rejected


async def test_meta_rejects_abstain_with_side() -> None:
    bad = MetaDecision(action="ABSTAIN", side="UP", confidence=0.5, rationale="oops")
    adapter = FakeAdapter(responses=[(bad, TokenUsage())])
    meta = MetaDecider(adapter)
    decision = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None


async def test_meta_returns_none_on_adapter_failure() -> None:
    adapter = FakeAdapter(responses=[(None, TokenUsage())])
    meta = MetaDecider(adapter)
    decision = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None


async def test_meta_can_disable_thinking() -> None:
    adapter = FakeAdapter(responses=[(_meta_decision("ABSTAIN", None, 0.4), TokenUsage())])
    meta = MetaDecider(adapter, adaptive_thinking=False, effort=None)
    await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    call = adapter.calls[0]
    assert call.thinking is None
    assert call.effort is None

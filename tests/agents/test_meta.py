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


async def test_meta_uses_sonnet_with_effort_no_adaptive_thinking_by_default() -> None:
    """Adaptive thinking was disabled by default on 2026-05-10 14:38 UTC after
    audit showed 2/3 of gate-mode LLM votes timing out at 2.5s with adaptive
    thinking on. Sonnet-medium without adaptive completes in ~1-2s typically."""
    adapter = FakeAdapter(responses=[(_meta_decision("FIRE", "UP", 0.7), TokenUsage())])
    meta = MetaDecider(adapter)
    assert meta.model == "claude-sonnet-4-6"

    decision, outcome = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote("UP", 0.7), "oracle_gap": sample_vote("UP", 0.8)},
    )

    assert isinstance(decision, MetaDecision)
    assert outcome == "ok"
    call = adapter.calls[0]
    assert call.model == "claude-sonnet-4-6"
    assert call.thinking is None
    assert call.effort == "medium"


async def test_meta_can_enable_adaptive_thinking_explicitly() -> None:
    """Operator can opt back into adaptive thinking via the explicit flag if
    they're willing to take the latency hit (e.g. higher gate_llm_timeout_s)."""
    adapter = FakeAdapter(responses=[(_meta_decision("FIRE", "UP", 0.7), TokenUsage())])
    meta = MetaDecider(adapter, adaptive_thinking=True)
    await meta.decide(
        sample_context(),
        {"orderbook": sample_vote("UP", 0.7), "oracle_gap": sample_vote("UP", 0.8)},
    )
    assert adapter.calls[0].thinking == {"type": "adaptive"}


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
    enforces the invariant that FIRE must have a side.

    Phase 18B: the rejection tags outcome="invariant_violated" so the
    ensemble log can separate this class from API/parse failures.
    """
    bad = MetaDecision(action="FIRE", side=None, confidence=0.7, rationale="oops")
    adapter = FakeAdapter(responses=[(bad, TokenUsage())])
    meta = MetaDecider(adapter)
    decision, outcome = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None
    assert outcome == "invariant_violated"


async def test_meta_rejects_abstain_with_side() -> None:
    bad = MetaDecision(action="ABSTAIN", side="UP", confidence=0.5, rationale="oops")
    adapter = FakeAdapter(responses=[(bad, TokenUsage())])
    meta = MetaDecider(adapter)
    decision, outcome = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None
    assert outcome == "invariant_violated"


async def test_meta_returns_none_on_adapter_failure() -> None:
    """Phase 18B: meta propagates the adapter's outcome tag verbatim when
    the adapter returned None. Here the FakeAdapter auto-tags a None
    response as "validation_failed"; in production the tag could equally
    be "api_error", "refusal", "no_text"."""
    adapter = FakeAdapter(responses=[(None, TokenUsage())])
    meta = MetaDecider(adapter)
    decision, outcome = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None
    assert outcome == "validation_failed"


async def test_meta_propagates_explicit_api_error_outcome() -> None:
    """When the adapter returns an explicit `api_error` tag, meta surfaces
    it unchanged. Regression for Phase 18B: the wrapper's log must see the
    underlying failure class, not a coarsened "meta=None"."""
    adapter = FakeAdapter(responses=[(None, TokenUsage(), "api_error")])
    meta = MetaDecider(adapter)
    decision, outcome = await meta.decide(
        sample_context(),
        {"orderbook": sample_vote(), "oracle_gap": sample_vote()},
    )
    assert decision is None
    assert outcome == "api_error"


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

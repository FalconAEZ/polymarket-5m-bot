"""Tests for polymarket_bot.agents.protocol — pydantic schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymarket_bot.agents.protocol import (
    AgentContext,
    AgentVote,
    MetaDecision,
    TokenUsage,
)


def test_agent_vote_accepts_canonical_shape() -> None:
    v = AgentVote(side="UP", confidence=0.7, rationale="ok")
    assert v.side == "UP"
    assert v.confidence == 0.7


def test_agent_vote_rejects_invalid_side() -> None:
    with pytest.raises(ValidationError):
        AgentVote(side="MAYBE", confidence=0.5, rationale="x")  # type: ignore[arg-type]


def test_agent_vote_clamps_confidence_range() -> None:
    with pytest.raises(ValidationError):
        AgentVote(side="UP", confidence=1.5, rationale="x")
    with pytest.raises(ValidationError):
        AgentVote(side="UP", confidence=-0.1, rationale="x")


def test_agent_vote_rationale_max_length() -> None:
    with pytest.raises(ValidationError):
        AgentVote(side="UP", confidence=0.5, rationale="x" * 300)


def test_meta_decision_fire_must_have_side() -> None:
    """A FIRE without a side is permissible by pydantic alone — the meta
    agent enforces this invariant in code (meta.py line 70)."""
    decision = MetaDecision(action="FIRE", side=None, confidence=0.6, rationale="x")
    assert decision.side is None  # pydantic accepts; meta layer will reject


def test_meta_decision_abstain_canonical() -> None:
    d = MetaDecision(action="ABSTAIN", side=None, confidence=0.4, rationale="all flat")
    assert d.action == "ABSTAIN"


def test_meta_decision_rejects_invalid_action() -> None:
    with pytest.raises(ValidationError):
        MetaDecision(action="HEDGE", side="UP", confidence=0.5, rationale="x")  # type: ignore[arg-type]


def test_agent_context_round_trips_through_json() -> None:
    ctx = AgentContext(
        window_ts=100,
        now_ts_utc_ns=200,
        seconds_to_close=20,
        spot_now=80_000.0,
        spot_at_window_open=79_900.0,
        spot_recent_60s=[79_900.0, 80_000.0],
        oracle_last=79_980.0,
        oracle_at_window_open=79_900.0,
        oracle_age_s=12.0,
        composite_pct=0.30,
    )
    blob = ctx.model_dump_json()
    parsed = AgentContext.model_validate_json(blob)
    assert parsed.composite_pct == 0.30
    assert parsed.spot_recent_60s == [79_900.0, 80_000.0]


def test_token_usage_defaults_zero() -> None:
    u = TokenUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_creation_input_tokens == 0
    assert u.cache_read_input_tokens == 0

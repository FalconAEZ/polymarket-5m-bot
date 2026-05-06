"""Tests for the 3 specialist agents — orderbook, oracle_gap, momentum.

All three follow the same call shape; one parametrised test class covers
them. Verifies prompt loading, model defaulting, vote parsing, and
graceful None on adapter failure.
"""

from __future__ import annotations

import pytest

from polymarket_bot.agents.momentum import MomentumAgent
from polymarket_bot.agents.oracle_gap import OracleGapAgent
from polymarket_bot.agents.orderbook import OrderbookAgent
from polymarket_bot.agents.protocol import AgentVote, TokenUsage
from tests.agents.conftest import FakeAdapter, sample_context, sample_vote

SPECIALIST_CLASSES = [
    (OrderbookAgent, "orderbook"),
    (OracleGapAgent, "oracle_gap"),
    (MomentumAgent, "momentum"),
]


@pytest.mark.parametrize(("cls", "name"), SPECIALIST_CLASSES)
async def test_specialist_loads_prompt_and_calls_adapter(cls: type, name: str) -> None:
    adapter = FakeAdapter(responses=[(sample_vote("UP", 0.7, "test"), TokenUsage())])
    agent = cls(adapter)
    assert agent.name == name
    assert agent.model == "claude-haiku-4-5"

    vote = await agent.vote(sample_context())

    assert isinstance(vote, AgentVote)
    assert vote.side == "UP"
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call.model == "claude-haiku-4-5"
    assert call.output_format is AgentVote
    # System prompt must be cache-blocked (single text block with cache_control)
    assert len(call.system) == 1
    assert call.system[0]["type"] == "text"
    assert "cache_control" in call.system[0]
    # The user JSON must be the AgentContext serialised
    assert "spot_now" in call.user


@pytest.mark.parametrize(("cls", "name"), SPECIALIST_CLASSES)
async def test_specialist_returns_none_on_adapter_failure(cls: type, name: str) -> None:
    del name  # parametrise carrier; not used in this test
    adapter = FakeAdapter(responses=[(None, TokenUsage())])
    agent = cls(adapter)
    vote = await agent.vote(sample_context())
    assert vote is None


@pytest.mark.parametrize(("cls", "name"), SPECIALIST_CLASSES)
async def test_specialist_does_not_pass_thinking_or_effort(cls: type, name: str) -> None:
    del name  # parametrise carrier; not used in this test
    """Haiku 4.5 doesn't support effort or adaptive thinking — verify the
    specialists never opt into them by accident."""
    adapter = FakeAdapter(responses=[(sample_vote(), TokenUsage())])
    agent = cls(adapter)
    await agent.vote(sample_context())
    call = adapter.calls[0]
    assert call.thinking is None
    assert call.effort is None


@pytest.mark.parametrize(("cls", "name"), SPECIALIST_CLASSES)
async def test_specialist_prompt_file_is_loaded(cls: type, name: str) -> None:
    """The prompts/<name>.md file must exist and be non-empty (load at construct)."""
    adapter = FakeAdapter()
    # If the prompt file is missing or empty, construction raises. The fact
    # that this passes proves all 3 prompt files are committed and content-bearing.
    agent = cls(adapter)
    assert agent.name == name

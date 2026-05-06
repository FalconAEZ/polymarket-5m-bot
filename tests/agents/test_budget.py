"""Tests for polymarket_bot.agents.budget.BudgetTracker."""

from __future__ import annotations

import pytest

from polymarket_bot.agents.budget import (
    CACHE_WRITE_MULTIPLIER,
    PRICING_USD,
    BudgetExceeded,
    BudgetTracker,
)
from polymarket_bot.agents.protocol import TokenUsage


def test_records_haiku_cost_correctly() -> None:
    tracker = BudgetTracker(hard_limit_usd=10.0, alarm_at_usd=8.0)
    # 1M input + 1M output for Haiku at $1/$5 per 1M tokens
    tracker.record(
        "claude-haiku-4-5",
        TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )
    # 1*1 + 1*5 = $6
    assert tracker.spent_usd == pytest.approx(6.0, abs=1e-9)


def test_records_cache_reads_at_discount() -> None:
    tracker = BudgetTracker(hard_limit_usd=100.0)
    tracker.record(
        "claude-haiku-4-5",
        TokenUsage(cache_read_input_tokens=10_000_000),
    )
    # 10M * $0.10/1M = $1.00
    assert tracker.spent_usd == pytest.approx(1.0, abs=1e-9)


def test_records_cache_writes_at_premium() -> None:
    tracker = BudgetTracker(hard_limit_usd=100.0)
    tracker.record(
        "claude-haiku-4-5",
        TokenUsage(cache_creation_input_tokens=1_000_000),
    )
    # 1M * $1.00/1M * 1.25 (write multiplier) = $1.25
    assert tracker.spent_usd == pytest.approx(1.0 * CACHE_WRITE_MULTIPLIER, abs=1e-9)


def test_raises_when_hard_limit_exceeded() -> None:
    tracker = BudgetTracker(hard_limit_usd=1.0)
    with pytest.raises(BudgetExceeded):
        tracker.record(
            "claude-sonnet-4-6",
            TokenUsage(output_tokens=1_000_000),  # 1M * $15 = $15
        )
    # The over-limit charge IS still recorded before raising — caller should
    # treat BudgetExceeded as terminal.
    assert tracker.spent_usd == pytest.approx(15.0, abs=1e-9)


def test_alarms_once_at_threshold() -> None:
    tracker = BudgetTracker(hard_limit_usd=10.0, alarm_at_usd=5.0)
    # First record below alarm; not yet alarmed.
    tracker.record("claude-haiku-4-5", TokenUsage(input_tokens=1_000_000))  # $1
    assert not tracker.report()["alarmed"]
    # Second record crosses alarm threshold.
    tracker.record(
        "claude-sonnet-4-6", TokenUsage(input_tokens=2_000_000)
    )  # 2M * $3 = $6, total $7
    assert tracker.report()["alarmed"]


def test_unknown_model_raises_immediately() -> None:
    tracker = BudgetTracker(hard_limit_usd=10.0)
    with pytest.raises(ValueError, match="unknown model"):
        tracker.record("nonexistent-model", TokenUsage(input_tokens=100))


def test_pricing_table_includes_required_models() -> None:
    """Locked decisions #4, #5, #14: Anthropic-only; specialists Haiku, meta Sonnet."""
    assert "claude-haiku-4-5" in PRICING_USD
    assert "claude-sonnet-4-6" in PRICING_USD


def test_alarm_must_be_at_or_below_hard_limit() -> None:
    with pytest.raises(ValueError, match="alarm_at_usd"):
        BudgetTracker(hard_limit_usd=10.0, alarm_at_usd=15.0)


def test_remaining_usd_floors_at_zero() -> None:
    tracker = BudgetTracker(hard_limit_usd=5.0)
    # Force one big charge that will raise; but spent will reflect it.
    with pytest.raises(BudgetExceeded):
        tracker.record("claude-sonnet-4-6", TokenUsage(output_tokens=1_000_000))
    assert tracker.remaining_usd() == 0.0


def test_report_includes_per_model_token_breakdown() -> None:
    tracker = BudgetTracker(hard_limit_usd=100.0)
    tracker.record("claude-haiku-4-5", TokenUsage(input_tokens=100, output_tokens=50))
    tracker.record("claude-haiku-4-5", TokenUsage(cache_read_input_tokens=500))
    tracker.record("claude-sonnet-4-6", TokenUsage(input_tokens=200))
    report = tracker.report()
    assert report["calls"] == 3
    calls_by_model = report["calls_by_model"]
    assert isinstance(calls_by_model, dict)
    assert calls_by_model["claude-haiku-4-5"] == 2
    assert calls_by_model["claude-sonnet-4-6"] == 1
    tokens = report["tokens_by_model"]
    assert isinstance(tokens, dict)
    assert tokens["claude-haiku-4-5"]["input_tokens"] == 100
    assert tokens["claude-haiku-4-5"]["cache_read_input_tokens"] == 500

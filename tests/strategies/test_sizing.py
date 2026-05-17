"""Tests for polymarket_bot.strategies.sizing — half-Kelly position sizing.

Phase 16.B.3 — Kelly is one input to the unified confidence score, NOT the
final size. The router applies the $5-$30 lerp on top. These tests verify
the Kelly formula itself: edges, caps, degenerate cases.
"""

from __future__ import annotations

import pytest

from polymarket_bot.strategies.sizing import (
    KELLY_MAX_BANKROLL_PCT,
    kelly_suggested_size_usd,
)


def test_kelly_zero_when_no_edge() -> None:
    """p_win <= fill_price means no edge; Kelly must return 0."""
    assert kelly_suggested_size_usd(p_win=0.50, fill_price=0.50, bankroll_usd=1000.0) == 0.0
    assert kelly_suggested_size_usd(p_win=0.40, fill_price=0.50, bankroll_usd=1000.0) == 0.0


def test_kelly_zero_on_degenerate_p_win() -> None:
    """p_win = 1.0 is degenerate (no risk); return 0 rather than divide-by-zero."""
    assert kelly_suggested_size_usd(p_win=1.0, fill_price=0.50, bankroll_usd=1000.0) == 0.0


def test_kelly_zero_on_invalid_fill_price() -> None:
    assert kelly_suggested_size_usd(p_win=0.60, fill_price=0.0, bankroll_usd=1000.0) == 0.0
    assert kelly_suggested_size_usd(p_win=0.60, fill_price=-0.1, bankroll_usd=1000.0) == 0.0


def test_kelly_zero_on_none_inputs() -> None:
    assert kelly_suggested_size_usd(p_win=None, fill_price=0.50, bankroll_usd=1000.0) == 0.0
    assert kelly_suggested_size_usd(p_win=0.60, fill_price=None, bankroll_usd=1000.0) == 0.0


def test_kelly_positive_at_60_40_even_odds() -> None:
    """Sanity: p=0.6, fp=0.5 (50/50 odds) → small positive half-Kelly.

    Full Kelly: f* = (0.6 * 1 - 0.4) / 1 = 0.2 (20% of bankroll)
    Half-Kelly: 0.1 (10%) → but capped at 3% → 3%
    At $1000 bankroll → $30.
    """
    size = kelly_suggested_size_usd(p_win=0.60, fill_price=0.50, bankroll_usd=1000.0)
    assert size == 30.00  # 3% cap of $1000 bites here


def test_kelly_small_edge_below_cap() -> None:
    """Sanity: a 1pp edge (51% vs 50%) → much smaller suggestion.

    Full Kelly: f* = (0.51 * 1 - 0.49) / 1 = 0.02 (2%)
    Half-Kelly: 1%; at $1000 → $10.
    """
    size = kelly_suggested_size_usd(p_win=0.51, fill_price=0.50, bankroll_usd=1000.0)
    assert 9.0 <= size <= 11.0


def test_kelly_capped_at_3pct_bankroll() -> None:
    """Even a huge edge (90/40) caps at 3% of bankroll."""
    size = kelly_suggested_size_usd(p_win=0.90, fill_price=0.40, bankroll_usd=1000.0)
    cap = round(KELLY_MAX_BANKROLL_PCT * 1000.0, 2)
    assert size == cap


def test_kelly_scales_with_bankroll() -> None:
    """At fixed edge, doubling bankroll doubles Kelly suggestion (up to cap)."""
    a = kelly_suggested_size_usd(p_win=0.51, fill_price=0.50, bankroll_usd=1000.0)
    b = kelly_suggested_size_usd(p_win=0.51, fill_price=0.50, bankroll_usd=2000.0)
    assert b == pytest.approx(2 * a, rel=0.01)


def test_kelly_full_fraction_doubles_half() -> None:
    """fraction=1.0 (full Kelly) gives 2x the suggestion of fraction=0.5 (default)."""
    half = kelly_suggested_size_usd(p_win=0.51, fill_price=0.50, bankroll_usd=1000.0, fraction=0.5)
    full = kelly_suggested_size_usd(p_win=0.51, fill_price=0.50, bankroll_usd=1000.0, fraction=1.0)
    assert full == pytest.approx(2 * half, rel=0.01)


def test_kelly_skewed_payoff_high_p_low_price() -> None:
    """At low fill_price (cheap UP token, near-cert win): cap holds.

    p=0.6, fp=0.10 → b = 9 (huge payoff). f* = (0.6*9 - 0.4)/9 = 0.556 (55.6%).
    Half-Kelly = 27.8% → CAPPED at 3% = $30.
    """
    size = kelly_suggested_size_usd(p_win=0.60, fill_price=0.10, bankroll_usd=1000.0)
    assert size == 30.0


def test_kelly_high_price_no_edge_or_negative() -> None:
    """p=0.55, fp=0.60 (no edge — fill_price > p_win)."""
    assert kelly_suggested_size_usd(p_win=0.55, fill_price=0.60, bankroll_usd=1000.0) == 0.0

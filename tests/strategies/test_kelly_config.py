"""Tests for polymarket_bot.strategies.kelly_config.KellyConfig.

Five tests mirror the test surface in
pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf §9.1. The math is pure
(no MarketEvent setup), so each test is a direct assertion on the
clamp-and-floor pipeline.
"""

from __future__ import annotations

import math

import pytest

from polymarket_bot.strategies.kelly_config import KellyConfig


def test_kelly_f_zero_when_no_edge() -> None:
    """p_win == price → no edge → f* = 0."""
    cfg = KellyConfig()
    assert cfg.kelly_f(p_win=0.30, price=0.30) == 0.0
    # Below price too: still zero, no negative bet.
    assert cfg.kelly_f(p_win=0.20, price=0.30) == 0.0


def test_kelly_f_classic() -> None:
    """p_win=0.55 at price=0.30 → f* = (0.55-0.30)/(1-0.30) ≈ 0.357."""
    cfg = KellyConfig()
    f = cfg.kelly_f(p_win=0.55, price=0.30)
    assert math.isclose(f, 0.25 / 0.70, rel_tol=1e-9), f"got {f}"


def test_bet_clamps_to_max_abs() -> None:
    """bankroll=$10,000 + huge edge → bet floored by max_bet_abs ($500)."""
    cfg = KellyConfig(kelly_mult=1.0, max_bet_pct=0.5, max_bet_abs=500.0)
    # p_win=0.95 at price=0.30 → f*≈0.929; bankroll x mult x f ≈ $9,286.
    # max_bet_pct cap = $5,000; max_bet_abs = $500 (the binding clamp).
    bet = cfg.bet_size(bankroll=10_000.0, p_win=0.95, price=0.30)
    assert bet == 500.0, f"expected max_bet_abs floor at 500, got {bet}"


def test_bet_clamps_to_max_pct() -> None:
    """bankroll=$1,000 + f*=0.5 → multxfxbankroll = $50 but max_bet_pct
    cap is 10% = $100. The 10% cap is non-binding here; instead the
    test verifies the cap is enforced when it would otherwise bind."""
    cfg = KellyConfig(kelly_mult=1.0, max_bet_pct=0.10, max_bet_abs=10_000.0)
    # Synthesise an edge where bankroll x kelly_mult x f exceeds 10%.
    # p_win=0.80 at price=0.30 → f* ≈ 0.714; bankroll x 1.0 x 0.714 = $714.
    # max_bet_pct cap = 0.10 x $1000 = $100 (the binding clamp).
    bet = cfg.bet_size(bankroll=1_000.0, p_win=0.80, price=0.30)
    assert bet == 100.0, f"expected max_bet_pct=10% x $1000 = $100, got {bet}"


def test_bet_below_min_returns_zero() -> None:
    """Tiny edge x tiny bankroll → clamped bet < min_bet_abs → 0."""
    cfg = KellyConfig(kelly_mult=0.10, min_bet_abs=1.0)
    # p_win=0.31 at price=0.30 → f* ≈ 0.0143; bankroll x 0.10 x f ≈ $0.14.
    bet = cfg.bet_size(bankroll=100.0, p_win=0.31, price=0.30)
    assert bet == 0.0, f"expected 0 (below $1 min), got {bet}"
    # Sanity: last_kelly_f is still cached for the rationale builder.
    assert cfg.last_kelly_f > 0.0


# ---------- constructor validation ----------


def test_kelly_config_rejects_invalid_multiplier() -> None:
    with pytest.raises(ValueError, match="kelly_mult"):
        KellyConfig(kelly_mult=0.0)
    with pytest.raises(ValueError, match="kelly_mult"):
        KellyConfig(kelly_mult=1.5)


def test_kelly_config_rejects_invalid_max_bet_pct() -> None:
    with pytest.raises(ValueError, match="max_bet_pct"):
        KellyConfig(max_bet_pct=0.0)
    with pytest.raises(ValueError, match="max_bet_pct"):
        KellyConfig(max_bet_pct=0.75)


def test_kelly_config_rejects_invalid_max_bet_abs() -> None:
    with pytest.raises(ValueError, match="max_bet_abs"):
        KellyConfig(max_bet_abs=0.0)

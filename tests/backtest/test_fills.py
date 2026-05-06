"""Tests for polymarket_bot.backtest.fills.FillSimulator + realised_pnl_usd.

Cover: asset_id mismatch, missing book side, limit-too-low rejection,
limit-just-right fill, fee math, impact scaling with size + depth, P&L
under win and loss outcomes.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.fills import (
    DEFAULT_FEE_BPS,
    FillSimulator,
    realised_pnl_usd,
)
from polymarket_bot.backtest.types import BookUpdate, Decision, Fill

TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def _decision(asset_id: str = TOKEN_UP, price_limit: float = 0.55, size: float = 5.0) -> Decision:
    return Decision(
        ts_utc_ns=1_000_000_000,
        asset_id=asset_id,
        side="BUY",
        size_usd=size,
        price_limit=price_limit,
        ttl_s=20,
        rationale="test",
    )


def _book(
    asset_id: str = TOKEN_UP,
    best_ask: float | None = 0.50,
    ask_size_top: float | None = 10_000.0,  # $5K notional at 0.50
) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=1_000_000_000,
        asset_id=asset_id,
        side="UP",
        best_bid=0.49 if best_ask is not None else None,
        best_ask=best_ask,
        bid_size_top=ask_size_top,
        ask_size_top=ask_size_top,
    )


def test_returns_none_when_asset_id_mismatches() -> None:
    sim = FillSimulator()
    fill = sim.attempt_fill(_decision(asset_id=TOKEN_UP), _book(asset_id=TOKEN_DOWN))
    assert fill is None


def test_returns_none_when_book_has_no_ask() -> None:
    sim = FillSimulator()
    fill = sim.attempt_fill(_decision(), _book(best_ask=None))
    assert fill is None


def test_returns_none_when_limit_below_effective_ask() -> None:
    sim = FillSimulator()
    # limit 0.40 < best_ask 0.50 → no fill regardless of impact.
    fill = sim.attempt_fill(_decision(price_limit=0.40), _book(best_ask=0.50))
    assert fill is None


def test_fills_when_limit_above_ask_plus_impact() -> None:
    sim = FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.0)
    fill = sim.attempt_fill(_decision(price_limit=0.55), _book(best_ask=0.50))
    assert isinstance(fill, Fill)
    assert fill.asset_id == TOKEN_UP
    assert fill.price_filled == 0.50
    # size = $5 / 0.50 = 10 shares
    assert fill.size_filled == pytest.approx(10.0)
    assert fill.fee_usd == 0.0


def test_fee_bps_applied_correctly() -> None:
    sim = FillSimulator(fee_bps=2.0, impact_per_5usd_per_5k=0.0)
    fill = sim.attempt_fill(_decision(size=5.0), _book(best_ask=0.50))
    # 2 bps of $5 = $0.001
    assert isinstance(fill, Fill)
    assert fill.fee_usd == pytest.approx(0.001, abs=1e-9)


def test_default_fee_matches_design_doc() -> None:
    assert DEFAULT_FEE_BPS == 2.0


def test_impact_scales_with_trade_size() -> None:
    """A $50 trade against $5K depth should impact 10x more than the $5 reference."""
    sim = FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.001)
    # depth = ask_size_top * best_ask = 10_000 * 0.50 = $5K — reference depth.
    # $5 trade → impact 0.001; $50 trade → impact 0.01.
    fill_small = sim.attempt_fill(
        _decision(size=5.0, price_limit=0.60), _book(best_ask=0.50, ask_size_top=10_000.0)
    )
    fill_big = sim.attempt_fill(
        _decision(size=50.0, price_limit=0.60), _book(best_ask=0.50, ask_size_top=10_000.0)
    )
    assert isinstance(fill_small, Fill)
    assert isinstance(fill_big, Fill)
    # fill_small.price_filled ≈ 0.50 + 0.001 = 0.501
    # fill_big.price_filled   ≈ 0.50 + 0.010 = 0.510
    assert fill_small.price_filled == pytest.approx(0.501, abs=1e-6)
    assert fill_big.price_filled == pytest.approx(0.510, abs=1e-6)


def test_impact_scales_inversely_with_depth() -> None:
    """Half the depth should double the impact for the same trade."""
    sim = FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.001)
    # depth = 5_000 * 0.50 = $2.5K → half reference depth.
    fill = sim.attempt_fill(
        _decision(size=5.0, price_limit=0.60), _book(best_ask=0.50, ask_size_top=5_000.0)
    )
    assert isinstance(fill, Fill)
    # impact = 0.001 * (1) * (5000 / 2500) = 0.002
    assert fill.price_filled == pytest.approx(0.502, abs=1e-6)


def test_returns_none_when_limit_just_below_effective_after_impact() -> None:
    """Limit 0.5005 with $5/$2.5K depth ⇒ effective 0.502 ⇒ no fill."""
    sim = FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.001)
    fill = sim.attempt_fill(
        _decision(size=5.0, price_limit=0.5005),
        _book(best_ask=0.50, ask_size_top=5_000.0),
    )
    assert fill is None


def test_constructor_rejects_negative_fee() -> None:
    with pytest.raises(ValueError, match="fee_bps"):
        FillSimulator(fee_bps=-0.1)


def test_realised_pnl_winning_side_pays_one_per_share_minus_cost_minus_fee() -> None:
    fill = Fill(
        ts_utc_ns=0,
        asset_id=TOKEN_UP,
        size_filled=10.0,
        price_filled=0.50,
        fee_usd=0.001,
    )
    pnl = realised_pnl_usd(fill, resolution_side_winning=True)
    # payout = 10.0 (winning side, $1/share); cost = 10*0.50 = 5.00; fee = 0.001
    # net = 10.0 - 5.0 - 0.001 = 4.999
    assert pnl == pytest.approx(4.999, abs=1e-9)


def test_realised_pnl_losing_side_loses_cost_plus_fee() -> None:
    fill = Fill(
        ts_utc_ns=0,
        asset_id=TOKEN_UP,
        size_filled=10.0,
        price_filled=0.50,
        fee_usd=0.001,
    )
    pnl = realised_pnl_usd(fill, resolution_side_winning=False)
    assert pnl == pytest.approx(-5.001, abs=1e-9)

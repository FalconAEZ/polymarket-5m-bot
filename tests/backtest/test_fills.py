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


def test_taker_refuses_floor_ask_when_depth_unknown() -> None:
    """Audit 2026-05-10 windows 1778388600 + 1778389500: best_ask was at
    Polymarket's $0.01 minimum tick and ask_size_top was None (the WS
    price_change / best_bid_ask events do not carry depth). The simulator
    over-filled $5 at the floor price, producing 454 shares and a phantom
    $449 win when UP later won. The defensive guard refuses the fill;
    the strategy's fired record gets fill=None and pnl=0."""
    sim = FillSimulator()  # default floor_best_ask=0.02
    book = _book(best_ask=0.01, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.03), book, is_taker=True)
    assert fill is None


def test_taker_allows_floor_ask_when_depth_is_known() -> None:
    """When ask_size_top is known, the impact model can do its job —
    no need to refuse on price alone. A $5 buy against $0.50 of top
    depth at $0.01 fills with substantial impact."""
    sim = FillSimulator(impact_per_5usd_per_5k=0.001, max_impact_usd=0.05)
    book = _book(best_ask=0.01, ask_size_top=50.0)  # $0.50 of depth
    # price_limit must clear best_ask + impact; impact is capped at 0.05
    fill = sim.attempt_fill(_decision(price_limit=0.10), book, is_taker=True)
    assert fill is not None


def test_taker_allows_above_floor_even_when_depth_unknown() -> None:
    """The guard only rejects when BOTH best_ask is at the floor AND
    depth is unknown. A book with best_ask above the floor is fine."""
    sim = FillSimulator()
    book = _book(best_ask=0.50, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.55), book, is_taker=True)
    assert fill is not None


def test_maker_refuses_floor_ask_when_depth_unknown() -> None:
    """Audit 2026-05-10 window 1778390700: bot fired DOWN at
    price_limit=$0.03 with best_ask=$0.01 + ask_size_top=None at
    decision time (taker guard correctly refused). Order rested. The
    LATER book that triggered the maker fill ALSO had ask=$0.03 +
    ask_size_top=None (a price_change event). Without the maker-side
    guard, the simulator filled the full $5 at $0.03, producing
    166.67 shares and a phantom $161.67 win when DOWN won."""
    sim = FillSimulator()  # default floor_best_ask=0.02
    later_book = _book(best_ask=0.02, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.03), later_book, is_taker=False)
    assert fill is None


def test_maker_allows_floor_ask_when_depth_is_known() -> None:
    """When the later book carries depth info, the maker fill is
    fine — we know the seller volume that's about to cross our bid."""
    sim = FillSimulator()
    later_book = _book(best_ask=0.02, ask_size_top=100.0)
    fill = sim.attempt_fill(_decision(price_limit=0.03), later_book, is_taker=False)
    assert fill is not None


def test_maker_allows_above_floor_even_when_depth_unknown() -> None:
    """Maker guard only rejects at-or-below the floor. A later book
    with best_ask comfortably above the floor is fine."""
    sim = FillSimulator()
    later_book = _book(best_ask=0.40, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.55), later_book, is_taker=False)
    assert fill is not None


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


def test_taker_refuses_at_0_03_when_depth_unknown() -> None:
    """Audit 2026-05-10: phantom maker fills happened at $0.03 (just
    above the original 0.02 floor). Bumped DEFAULT_FLOOR_BEST_ASK to
    0.05 to catch the $0.03 case. A taker fill at 0.03 with no depth
    must now be refused."""
    sim = FillSimulator()  # default floor_best_ask=0.05
    book = _book(best_ask=0.03, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.05), book, is_taker=True)
    assert fill is None


def test_maker_refuses_at_0_03_when_depth_unknown() -> None:
    """Window 1778415300 case: bot fired DOWN at price_limit=$0.03;
    taker guard refused at fired-time; order rested; later book at
    ask=$0.03 with ask_size_top=None should now refuse the maker fill
    too (with the bumped 0.05 floor)."""
    sim = FillSimulator()
    later_book = _book(best_ask=0.03, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.03), later_book, is_taker=False)
    assert fill is None


def test_size_guard_refuses_overfill_when_depth_unknown() -> None:
    """Even if best_ask is above the price floor, refuse when the
    would-be fill size exceeds the depth-less max. A $5 stake at
    $0.08 would produce 62.5 shares — over the 50-share cap."""
    sim = FillSimulator()
    book = _book(best_ask=0.08, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.10, size=5.0), book, is_taker=True)
    assert fill is None


def test_size_guard_allows_when_depth_known() -> None:
    """Size guard ONLY engages when ask_size_top is None. With known
    depth the impact model handles it (and the guard does nothing)."""
    sim = FillSimulator()
    book = _book(best_ask=0.08, ask_size_top=200.0)  # $16 of depth
    fill = sim.attempt_fill(_decision(price_limit=0.10, size=5.0), book, is_taker=True)
    assert fill is not None


def test_size_guard_allows_normal_trade_above_floor() -> None:
    """Normal trade ($5 stake at $0.20 ask = 25 shares) with no depth
    info should still fill — under both the price floor and the size cap."""
    sim = FillSimulator()
    book = _book(best_ask=0.20, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.25, size=5.0), book, is_taker=True)
    assert fill is not None
    # Sanity-check the size came out as expected (cost / fill_price).
    assert 24 < fill.size_filled < 26


# --------------------------------------------------------------------------
# Phase T 2026-05-21 — size-guard now price-conditional (gated to <0.10)
# --------------------------------------------------------------------------


def test_no_depth_at_mid_price_now_fills_above_old_cap() -> None:
    """Phase T fix — At fill_price=0.45 (well above the 0.10 size-guard
    threshold), a $90 bet that produces 200 shares (> 50-share old cap)
    must now FILL when ask_size_top is unknown. Previously this case was
    refused by the price-blind size cap. Spot_aware_v2_1 with Kelly + $3k
    bankroll routinely produces this size."""
    sim = FillSimulator()
    book = _book(best_ask=0.45, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.46, size=90.0), book, is_taker=True)
    assert fill is not None, "mid-price fill with unknown depth must now succeed"
    # Sanity: $90 / ~$0.45 ≈ 200 shares — above the old 50-cap.
    assert fill.size_filled > 100, f"expected large size, got {fill.size_filled}"


def test_no_depth_near_floor_still_refused_by_price_guard() -> None:
    """Phase T fix preserves the Phase 11.A defense at floor prices.
    fill_price=0.04 hits the price-floor guard (<=0.05) regardless of
    size or depth. Wide_fire-era phantom fills at $0.01-$0.04 still
    correctly refused."""
    sim = FillSimulator()
    book = _book(best_ask=0.04, ask_size_top=None)
    fill = sim.attempt_fill(_decision(price_limit=0.05, size=5.0), book, is_taker=True)
    assert fill is None, "floor-price fill with unknown depth must refuse"


def test_no_depth_below_size_guard_threshold_still_refused_by_size() -> None:
    """Phase T fix scopes size-cap to fill_price<0.10. At fill_price=0.08
    (above 0.05 floor, below 0.10 size-guard threshold), a $5 bet that
    produces 62 shares (> 50-cap) MUST still be refused. This validates
    the size-cap defense is preserved in the price zone where it was
    designed to operate."""
    sim = FillSimulator()
    book = _book(best_ask=0.08, ask_size_top=None)
    # $5 / $0.08 = 62.5 shares — above the 50-cap, below 0.10 price.
    fill = sim.attempt_fill(_decision(price_limit=0.09, size=5.0), book, is_taker=True)
    assert fill is None, "size-cap below 0.10 threshold must still refuse"


def test_size_guard_max_price_constructor_override() -> None:
    """Phase T fix — operator can pass size_guard_max_price=1.0 to
    restore the original price-blind size-cap behavior if needed for
    backward compatibility. Validates the param is wired."""
    sim_old = FillSimulator(size_guard_max_price=1.0)
    book = _book(best_ask=0.45, ask_size_top=None)
    # Same mid-price case as the new-default test above — with size_guard
    # set to 1.0, the cap applies at all prices, so this is refused.
    fill = sim_old.attempt_fill(_decision(price_limit=0.46, size=90.0), book, is_taker=True)
    assert fill is None, "size_guard_max_price=1.0 must restore price-blind cap"

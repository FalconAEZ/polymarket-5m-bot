"""Tests for polymarket_bot.strategies.spot_aware_v2.SpotAwareStrategyV2.

Driven by design/spot_aware_v2_tier_restricted.md. v2 differs from v1
in three structural ways:
  1. Reject tier 50-70% explicitly (rejected_tiers).
  2. NO p_win=0.54 fallback -- priors miss = no fire.
  3. Re-enforce delta_min/max + EV gate (no aggressive bypass possible).

We mirror the v1 happy-path test + add v2-specific rejection tests.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.spot_aware_priors import (
    SpotAwarePriors,
    load_priors,
)
from polymarket_bot.strategies.spot_aware_v2 import (
    SpotAwareStrategyV2,
    _rationale_v2,
)

WINDOW_TS = 1_715_000_100
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def _open(window_ts: int = WINDOW_TS) -> WindowBoundary:
    return WindowBoundary(
        ts_utc_ns=window_ts * 1_000_000_000,
        window_ts=window_ts,
        kind="open",
    )


def _close(window_ts: int = WINDOW_TS) -> WindowBoundary:
    return WindowBoundary(
        ts_utc_ns=(window_ts + 300) * 1_000_000_000,
        window_ts=window_ts,
        kind="close",
    )


def _book(side: str, asset_id: str, ask: float = 0.45, ts_offset_s: int = 30) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        asset_id=asset_id,
        side=side,  # type: ignore[arg-type]
        best_bid=max(0.01, ask - 0.02),
        best_ask=ask,
        bid_size_top=100.0,
        ask_size_top=100.0,
    )


def _spot(price: float, ts_offset_s: int = 0, source: str = "binance") -> SpotTick:
    return SpotTick(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        source=source,  # type: ignore[arg-type]
        price=price,
    )


def _priors() -> SpotAwarePriors:
    return load_priors()


async def _run_window_to_decision(
    strat: SpotAwareStrategyV2,
    *,
    open_spot: float,
    end_spot: float,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    """Drive a single window with the given open/end spot prices and asks.
    Returns the decision (if any) emitted at the moving spot tick."""
    await strat.on_event(_open())
    # Establish open spot first (open_spot is captured at first SpotTick after open).
    await strat.on_event(_spot(open_spot, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=ask_up, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=ask_down, ts_offset_s=2))
    # Move spot -- triggers _maybe_fire.
    return await strat.on_event(_spot(end_spot, ts_offset_s=30))


# ---------- happy path ----------


async def test_v2_fires_on_priors_hit_in_30_50_with_positive_ev() -> None:
    """tier 0.45, |Δ|=10 bps, priors hit, EV > 0.005 → fires."""
    strat = SpotAwareStrategyV2(priors=_priors())
    # 10 bps move on $80,000 spot ≈ $80 move
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.45
    )
    assert decision is not None
    assert decision.side == "BUY"
    assert "strategy=spot_aware_v2" in decision.rationale
    assert "side=UP" in decision.rationale  # spot went up


# ---------- v2-specific rejections ----------


async def test_v2_rejects_tier_50_70_explicitly() -> None:
    """ask=0.55 falls in [0.50, 0.70) → rejected even with priors hit."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.55
    )
    assert decision is None


async def test_v2_rejects_tier_85_plus_via_belt_and_braces() -> None:
    """ask=0.90 falls in [0.85, 1.01) → rejected by v2's explicit list
    (also already excluded by the priors table itself, hence
    belt-and-braces)."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.90
    )
    assert decision is None


async def test_v2_rejects_priors_miss_no_fallback() -> None:
    """tier 0.40 (admitted) + |Δ|=3 bps (BELOW priors min of 5) →
    priors lookup returns None → v2 returns None (no fallback)."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_024.0, ask_up=0.40
    )
    assert decision is None


async def test_v2_rejects_low_delta() -> None:
    """|Δ|=3 bps < delta_min_bps=5 → returns None."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_024.0, ask_up=0.40
    )
    assert decision is None


async def test_v2_rejects_zero_delta() -> None:
    """Δ=0 exactly → alignment undefined → returns None."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_000.0, ask_up=0.40
    )
    assert decision is None


async def test_v2_does_not_accept_aggressive_mode_kwarg() -> None:
    """v2 has no aggressive_mode argument; passing it raises TypeError."""
    with pytest.raises(TypeError):
        SpotAwareStrategyV2(priors=_priors(), aggressive_mode=True)  # type: ignore[call-arg]


async def test_v2_rationale_marks_strategy_v2() -> None:
    """Emitted rationale must include strategy=spot_aware_v2 marker."""
    rat = _rationale_v2(d_bps=12.5, p_win=0.54, ev=0.025, ttl_s=20, side="UP")
    assert "strategy=spot_aware_v2" in rat
    assert "mode=tier_restricted" in rat
    assert "delta_bps=+12.50" in rat
    assert "side=UP" in rat


# ---------- defensive ----------


async def test_v2_fire_once_per_window() -> None:
    """Once a decision fires for a window, no further decisions in same window."""
    strat = SpotAwareStrategyV2(priors=_priors())
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.45, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45, ts_offset_s=2))
    first = await strat.on_event(_spot(80_080.0, ts_offset_s=30))
    assert first is not None
    second = await strat.on_event(_spot(80_120.0, ts_offset_s=60))
    assert second is None


async def test_v2_resets_fire_flag_on_new_window() -> None:
    """After window-close + window-open, the fire flag resets."""
    strat = SpotAwareStrategyV2(priors=_priors())
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.45, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45, ts_offset_s=2))
    first = await strat.on_event(_spot(80_080.0, ts_offset_s=30))
    assert first is not None
    # New window
    next_window = WINDOW_TS + 300
    await strat.on_event(
        WindowBoundary(
            ts_utc_ns=next_window * 1_000_000_000,
            window_ts=next_window,
            kind="open",
        )
    )
    await strat.on_event(
        SpotTick(
            ts_utc_ns=next_window * 1_000_000_000 + 1_000_000_000,
            source="binance",
            price=80_000.0,
        )
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=next_window * 1_000_000_000 + 2_000_000_000,
            asset_id=TOKEN_UP,
            side="UP",
            best_bid=0.43,
            best_ask=0.45,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=next_window * 1_000_000_000 + 2_000_000_000,
            asset_id=TOKEN_DOWN,
            side="DOWN",
            best_bid=0.43,
            best_ask=0.45,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    second = await strat.on_event(
        SpotTick(
            ts_utc_ns=next_window * 1_000_000_000 + 30_000_000_000,
            source="binance",
            price=80_080.0,
        )
    )
    assert second is not None


# ---------- constructor validation ----------


def test_v2_rejects_invalid_delta_min() -> None:
    with pytest.raises(ValueError, match="delta_min_bps must be > 0"):
        SpotAwareStrategyV2(priors=_priors(), delta_min_bps=0)


def test_v2_rejects_invalid_rejected_tier_band() -> None:
    with pytest.raises(ValueError, match="rejected_tiers"):
        SpotAwareStrategyV2(priors=_priors(), rejected_tiers=((0.7, 0.5),))  # lo>=hi


def test_v2_default_rejected_tiers_includes_50_70() -> None:
    """Default rejected_tiers includes (0.50, 0.70) per the design."""
    strat = SpotAwareStrategyV2(priors=_priors())
    assert (0.50, 0.70) in strat._rejected_tiers

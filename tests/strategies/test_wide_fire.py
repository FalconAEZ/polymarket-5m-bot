"""Tests for polymarket_bot.strategies.wide_fire.WideFireStrategy.

Per design/phase-5-llm-ensemble.md (Phase 5.0). WideFireStrategy is the
"max volume" base for EnsembleWrapper — it intentionally has NO filters
beyond the bare minimum (spot moved, asset known, ask known, ttl OK).
The LLM ensemble's meta-decider is the actual gate when this is wrapped.

Tests cover:
  1. Fires on tiny spot moves (ev/priors/tier all bypassed)
  2. Fires on tiers v2 would reject (50-70%, 85+, <15%)
  3. Refuses to fire on flat-spot (Δ=0 — alignment undefined)
  4. Honors optional delta_min_bps floor (default 0)
  5. One-fire-per-window invariant
  6. Resets fire flag on window-open
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.wide_fire import WideFireStrategy

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


def _spot(price: float, ts_offset_s: int = 0) -> SpotTick:
    return SpotTick(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        source="binance",
        price=price,
    )


async def _drive(
    strat: WideFireStrategy,
    *,
    open_spot: float,
    end_spot: float,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    await strat.on_event(_open())
    await strat.on_event(_spot(open_spot, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=ask_up, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=ask_down, ts_offset_s=2))
    return await strat.on_event(_spot(end_spot, ts_offset_s=30))


# ----------------------------------------------------------------------
# Fires under conditions v2 would reject
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wide_fire_fires_on_tiny_delta() -> None:
    """0.5 bps move (way below v2's delta_min=5) → fires."""
    strat = WideFireStrategy()
    decision = await _drive(strat, open_spot=80_000.0, end_spot=80_004.0)  # 0.5bps
    assert decision is not None
    assert "side=UP" in decision.rationale
    assert "strategy=wide_fire" in decision.rationale


@pytest.mark.asyncio
async def test_wide_fire_fires_on_50_70_tier() -> None:
    """ask=0.55 (in v2's reject band) → wide_fire fires anyway."""
    strat = WideFireStrategy()
    decision = await _drive(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.55)
    assert decision is not None
    assert "side=UP" in decision.rationale


@pytest.mark.asyncio
async def test_wide_fire_fires_on_85_plus_tier() -> None:
    """ask=0.92 (in v2's belt-and-braces 85+ reject band) → fires anyway."""
    strat = WideFireStrategy()
    decision = await _drive(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.92)
    assert decision is not None


@pytest.mark.asyncio
async def test_wide_fire_fires_on_under_15_tier() -> None:
    """ask=0.10 (below v1's tier admit floor) → fires anyway."""
    strat = WideFireStrategy()
    decision = await _drive(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.10)
    assert decision is not None


@pytest.mark.asyncio
async def test_wide_fire_refuses_flat_spot() -> None:
    """Δ=0 exactly → alignment undefined → returns None (the only refusal)."""
    strat = WideFireStrategy()
    decision = await _drive(strat, open_spot=80_000.0, end_spot=80_000.0)
    assert decision is None


# ----------------------------------------------------------------------
# Optional delta floor
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wide_fire_honors_delta_min_when_set() -> None:
    """delta_min_bps=2 → fires on >=2bps but not on <2bps."""
    strat = WideFireStrategy(delta_min_bps=2.0)
    # 1bp: BLOCKED
    above = await _drive(strat, open_spot=80_000.0, end_spot=80_008.0)  # 1bp
    assert above is None
    # 5bp: FIRES (need a fresh window)
    strat2 = WideFireStrategy(delta_min_bps=2.0)
    big = await _drive(strat2, open_spot=80_000.0, end_spot=80_040.0)  # 5bp
    assert big is not None


# ----------------------------------------------------------------------
# Invariants
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wide_fire_only_fires_once_per_window() -> None:
    """A second moving spot tick in the same window does NOT re-fire."""
    strat = WideFireStrategy()
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.45, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45, ts_offset_s=2))
    first = await strat.on_event(_spot(80_004.0, ts_offset_s=30))
    assert first is not None
    second = await strat.on_event(_spot(80_010.0, ts_offset_s=60))
    assert second is None


@pytest.mark.asyncio
async def test_wide_fire_resets_fire_flag_on_new_window() -> None:
    """After window close+open, the flag resets so we fire again."""
    strat = WideFireStrategy()
    # Window 1
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.45, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45, ts_offset_s=2))
    first = await strat.on_event(_spot(80_004.0, ts_offset_s=30))
    assert first is not None
    # Window 2
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
            ts_utc_ns=next_window * 1_000_000_000 + 30 * 1_000_000_000,
            source="binance",
            price=80_010.0,
        )
    )
    assert second is not None


# ----------------------------------------------------------------------
# Constructor validation
# ----------------------------------------------------------------------


def test_wide_fire_rejects_negative_delta_min() -> None:
    with pytest.raises(ValueError, match="delta_min_bps"):
        WideFireStrategy(delta_min_bps=-1.0)


def test_wide_fire_rejects_invalid_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_low_s"):
        WideFireStrategy(ttl_low_s=-5)
    with pytest.raises(ValueError, match="ttl_low_s"):
        WideFireStrategy(ttl_low_s=60, ttl_high_s=10)

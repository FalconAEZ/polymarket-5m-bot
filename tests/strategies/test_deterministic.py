"""Tests for polymarket_bot.strategies.deterministic.DeterministicStrategy.

Drive the strategy with synthetic MarketEvent sequences (no Parquet, no
network) and assert on the Decision output. Cover: composite formula,
threshold gate, TTL gate, fire-once-per-window, side selection, asset_id
lookup, defensive guards.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    OracleUpdate,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.deterministic import (
    DEFAULT_THRESHOLD_PCT,
    DeterministicStrategy,
    composite_pct,
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


def _book(side: str, asset_id: str, ask: float = 0.51, ts_offset_s: int = 0) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        asset_id=asset_id,
        side=side,  # type: ignore[arg-type]
        best_bid=ask - 0.02,
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


def _oracle(price: float, ts_offset_s: int = 0) -> OracleUpdate:
    return OracleUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        price=price,
        round_id=1,
        updated_at_s=WINDOW_TS + ts_offset_s,
    )


def test_composite_pct_returns_percentage_points() -> None:
    # +1% spot vs window open, 0% gap → composite = 0.5*1.0 + 0.5*0 = 0.5pp
    sig = composite_pct(spot_now=60_600.0, window_open_spot=60_000.0, oracle_last=60_600.0)
    assert sig == pytest.approx(0.5, abs=1e-6)


def test_composite_pct_handles_zero_safely() -> None:
    assert composite_pct(spot_now=1.0, window_open_spot=0.0, oracle_last=1.0) == 0.0
    assert composite_pct(spot_now=1.0, window_open_spot=1.0, oracle_last=0.0) == 0.0


def test_composite_pct_negative_when_below_open() -> None:
    sig = composite_pct(spot_now=59_400.0, window_open_spot=60_000.0, oracle_last=59_400.0)
    assert sig < 0


async def test_no_fire_before_window_open_event() -> None:
    s = DeterministicStrategy()
    # Spot + oracle + book seen, but no WindowBoundary(open).
    assert await s.on_event(_spot(60_000.0)) is None
    assert await s.on_event(_oracle(60_000.0)) is None
    assert await s.on_event(_book("UP", TOKEN_UP)) is None
    assert await s.on_event(_spot(61_000.0, ts_offset_s=290)) is None


async def test_no_fire_when_signal_below_threshold() -> None:
    s = DeterministicStrategy(threshold_pct=0.6)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP))
    await s.on_event(_book("DOWN", TOKEN_DOWN))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))  # window-open spot
    # +0.05% spot, 0% gap → composite ~0.025pp << 0.6pp threshold
    await s.on_event(_oracle(60_030.0, ts_offset_s=270))
    assert await s.on_event(_spot(60_030.0, ts_offset_s=275)) is None


async def test_no_fire_outside_ttl_window() -> None:
    """Composite over threshold but TTL not yet in [10, 30]."""
    s = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP))
    await s.on_event(_book("DOWN", TOKEN_DOWN))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=10))
    # ts_offset_s=100 → ttl = 300 - 100 = 200s, way outside [10, 30]
    decision = await s.on_event(_spot(60_900.0, ts_offset_s=100))
    assert decision is None


async def test_fires_when_threshold_and_ttl_satisfied_up_side() -> None:
    s = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.46))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    # ts_offset_s=275 → ttl = 25s, within [10, 30]; spot +1% vs open and +1% gap.
    decision = await s.on_event(_spot(60_600.0, ts_offset_s=275))
    assert isinstance(decision, Decision)
    assert decision.asset_id == TOKEN_UP
    assert decision.side == "BUY"
    assert decision.size_usd == 5.0
    assert decision.price_limit == 0.55
    assert 10 <= decision.ttl_s <= 30
    assert "side=UP" in decision.rationale


async def test_fires_down_when_signal_negative() -> None:
    s = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.46))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    decision = await s.on_event(_spot(59_400.0, ts_offset_s=275))  # -1% from open
    assert isinstance(decision, Decision)
    assert decision.asset_id == TOKEN_DOWN
    assert decision.price_limit == 0.46
    assert "side=DOWN" in decision.rationale


async def test_fires_at_most_once_per_window() -> None:
    s = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.46))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    first = await s.on_event(_spot(60_600.0, ts_offset_s=275))
    second = await s.on_event(_spot(60_900.0, ts_offset_s=280))  # also above threshold
    assert isinstance(first, Decision)
    assert second is None


async def test_new_window_resets_fire_state() -> None:
    s = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.46))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    first = await s.on_event(_spot(60_600.0, ts_offset_s=275))
    assert isinstance(first, Decision)
    # Next window opens.
    await s.on_event(
        WindowBoundary(
            ts_utc_ns=(WINDOW_TS + 300) * 1_000_000_000,
            window_ts=WINDOW_TS + 300,
            kind="open",
        )
    )
    # state resets — but spot and oracle persist. Need to satisfy threshold again
    # in the new window relative to its own open.
    await s.on_event(_oracle(60_300.0, ts_offset_s=300 + 270))
    second = await s.on_event(_spot(61_300.0, ts_offset_s=300 + 275))
    assert isinstance(second, Decision)


async def test_no_fire_without_book_update_yet() -> None:
    """Asset_id is sourced from BookUpdate. Without one, we can't decide which token."""
    s = DeterministicStrategy(threshold_pct=0.5)
    await s.on_event(_open())
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    decision = await s.on_event(_spot(60_600.0, ts_offset_s=275))
    assert decision is None  # no asset_id → can't fire


async def test_reset_clears_state() -> None:
    s = DeterministicStrategy()
    await s.on_event(_open())
    await s.on_event(_spot(60_000.0))
    s.reset()
    # After reset, we shouldn't fire even with a normally-firing sequence
    # because window-open state was wiped.
    await s.on_event(_book("UP", TOKEN_UP))
    await s.on_event(_oracle(60_000.0, ts_offset_s=270))
    decision = await s.on_event(_spot(60_600.0, ts_offset_s=275))
    assert decision is None


def test_constructor_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold_pct"):
        DeterministicStrategy(threshold_pct=0.0)
    with pytest.raises(ValueError, match="threshold_pct"):
        DeterministicStrategy(threshold_pct=-0.5)


def test_constructor_rejects_invalid_ttl() -> None:
    with pytest.raises(ValueError, match="ttl"):
        DeterministicStrategy(ttl_low_s=20, ttl_high_s=10)
    with pytest.raises(ValueError, match="ttl"):
        DeterministicStrategy(ttl_low_s=-1, ttl_high_s=30)


def test_default_threshold_matches_locked_decision_six() -> None:
    """Decision #6 says threshold = 0.6. The default constant must match."""
    assert DEFAULT_THRESHOLD_PCT == 0.6

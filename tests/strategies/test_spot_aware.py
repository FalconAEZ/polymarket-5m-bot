"""Tests for polymarket_bot.strategies.spot_aware.SpotAwareStrategy.

Driven by design/spot_aware_strategy.md §3-§6. Synthetic MarketEvent
sequences only — no Parquet, no network. Cover: Δ_bps formula, alignment
classification, threshold gates, tier filter, EV check, prior lookup,
fire-once-per-window, side selection, defensive guards.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.spot_aware import (
    DEFAULT_DELTA_MAX_BPS,
    DEFAULT_DELTA_MIN_BPS,
    DEFAULT_EV_MIN_DOLLARS,
    DEFAULT_FEE_PCT,
    DEFAULT_SIZE_USD,
    SpotAwareStrategy,
    delta_bps,
)
from polymarket_bot.strategies.spot_aware_priors import (
    SpotAwarePriors,
    load_priors,
)

WINDOW_TS = 1_715_000_100
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


# ---------- builders ----------


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


def _book(side: str, asset_id: str, ask: float = 0.55, ts_offset_s: int = 30) -> BookUpdate:
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


# ---------- delta_bps formula ----------


def test_delta_bps_zero_when_unchanged() -> None:
    assert delta_bps(spot_now=60_000.0, window_open_spot=60_000.0) == pytest.approx(0.0)


def test_delta_bps_positive_when_up() -> None:
    # +60 USD on $60_000 = 10bps
    assert delta_bps(spot_now=60_060.0, window_open_spot=60_000.0) == pytest.approx(10.0)


def test_delta_bps_negative_when_down() -> None:
    # -120 USD on $60_000 = -20bps
    assert delta_bps(spot_now=59_880.0, window_open_spot=60_000.0) == pytest.approx(-20.0)


def test_delta_bps_handles_zero_open() -> None:
    assert delta_bps(spot_now=1.0, window_open_spot=0.0) == 0.0


# ---------- priors loader ----------


def test_priors_loader_reads_json() -> None:
    p = load_priors()
    assert p.version == "v1"
    # Sweet-spot bucket from §6
    assert p.lookup(price=0.55, abs_delta_bps=8.0) == pytest.approx(0.74, abs=0.001)


def test_priors_loader_returns_none_for_explicit_rejection_tier() -> None:
    # 0.85-1.00 tier is rejected by config
    p = load_priors()
    assert p.lookup(price=0.92, abs_delta_bps=8.0) is None


def test_priors_loader_returns_none_for_unmodelled_low_tier() -> None:
    # <0.15 has no prior in v1
    p = load_priors()
    assert p.lookup(price=0.10, abs_delta_bps=8.0) is None


def test_priors_loader_returns_none_outside_delta_buckets() -> None:
    p = load_priors()
    # Below min
    assert p.lookup(price=0.55, abs_delta_bps=2.0) is None
    # Above max
    assert p.lookup(price=0.55, abs_delta_bps=80.0) is None


# ---------- defensive guards ----------


async def test_no_fire_before_window_open_event() -> None:
    s = SpotAwareStrategy(priors=_priors())
    assert await s.on_event(_spot(60_000.0)) is None
    assert await s.on_event(_book("UP", TOKEN_UP)) is None
    assert await s.on_event(_spot(60_100.0, ts_offset_s=30)) is None


async def test_no_fire_without_books_seen() -> None:
    s = SpotAwareStrategy(priors=_priors())
    await s.on_event(_open())
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    # +12bps move but no book updates yet
    decision = await s.on_event(_spot(60_072.0, ts_offset_s=30))
    assert decision is None


async def test_no_fire_without_window_open_spot() -> None:
    """Strategy needs a window-open spot reference."""
    s = SpotAwareStrategy(priors=_priors())
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.50))
    # No window-open spot tick before this one — strategy can't compute Δ_bps
    # Pre-fill last spot only mid-window
    decision = await s.on_event(_spot(60_072.0, ts_offset_s=30))
    # First spot tick after window_open seeded as window_open_spot, so Δ=0
    # → no fire (below threshold)
    assert decision is None


# ---------- Δ_min threshold ----------


async def test_no_fire_when_delta_below_min() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=8.0, delta_max_bps=DEFAULT_DELTA_MAX_BPS)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.50))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))  # window-open spot
    # +30 USD = +5bps, below 8bps min
    decision = await s.on_event(_spot(60_030.0, ts_offset_s=30))
    assert decision is None


async def test_no_fire_when_delta_above_max() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=DEFAULT_DELTA_MIN_BPS, delta_max_bps=50.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.50))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    # +6_000 USD = +100bps, above 50bps max
    decision = await s.on_event(_spot(66_000.0, ts_offset_s=30))
    assert decision is None


# ---------- alignment ----------


async def test_fires_up_side_on_positive_delta() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.50))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))  # +10bps
    assert decision is not None
    assert decision.asset_id == TOKEN_UP
    assert "side=UP" in decision.rationale


async def test_fires_down_side_on_negative_delta() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.45))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.55))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(59_940.0, ts_offset_s=30))  # -10bps
    assert decision is not None
    assert decision.asset_id == TOKEN_DOWN
    assert "side=DOWN" in decision.rationale


# ---------- price-tier filter ----------


async def test_no_fire_when_price_in_85_100_tier() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    # UP side at 0.92 — squarely in the rejected 85-100% tier
    await s.on_event(_book("UP", TOKEN_UP, ask=0.92))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.05))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    # Aligned UP+up but tier 85-100 rejected
    assert decision is None


async def test_no_fire_when_price_below_15pct_tier() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.10))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.85))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    # Aligned UP+up but tier <0.15 has no prior — refuse to fire
    assert decision is None


# ---------- EV check ----------


async def test_no_fire_when_ev_negative() -> None:
    """p_win * $1 - (price + fees) ≤ 0.005 ⇒ no fire."""
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    # Tier 0.70-0.85, bucket 5-10bps → p_win=0.80. With ask=0.80 and fees
    # 0.5%, EV = 0.80 - (0.80 + 0.005) = -0.005 ≤ 0.005 floor → no fire.
    await s.on_event(_book("UP", TOKEN_UP, ask=0.80))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.20))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_048.0, ts_offset_s=30))  # +8bps
    assert decision is None


async def test_fires_when_ev_positive() -> None:
    """p_win * $1 - (price + fees) > 0.005 ⇒ fire."""
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    # 0.50-0.70 tier, +5..10bps bucket → p_win=0.74. With ask=0.55 and fees
    # 0.5%, EV = 0.74 - 0.555 = 0.185, well above 0.005 floor.
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    assert decision is not None


# ---------- fire-once-per-window ----------


async def test_fire_once_per_window() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    d1 = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    d2 = await s.on_event(_spot(60_120.0, ts_offset_s=60))
    assert d1 is not None
    assert d2 is None


async def test_fires_again_in_next_window() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    d1 = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    assert d1 is not None
    # New window
    next_ts = WINDOW_TS + 300
    await s.on_event(_close())
    await s.on_event(_open(window_ts=next_ts))
    await s.on_event(SpotTick(ts_utc_ns=next_ts * 1_000_000_000, source="binance", price=60_120.0))
    next_book_up = BookUpdate(
        ts_utc_ns=next_ts * 1_000_000_000,
        asset_id=TOKEN_UP,
        side="UP",
        best_bid=0.53,
        best_ask=0.55,
        bid_size_top=100.0,
        ask_size_top=100.0,
    )
    next_book_dn = BookUpdate(
        ts_utc_ns=next_ts * 1_000_000_000,
        asset_id=TOKEN_DOWN,
        side="DOWN",
        best_bid=0.43,
        best_ask=0.45,
        bid_size_top=100.0,
        ask_size_top=100.0,
    )
    await s.on_event(next_book_up)
    await s.on_event(next_book_dn)
    d2 = await s.on_event(
        SpotTick(
            ts_utc_ns=(next_ts + 30) * 1_000_000_000,
            source="binance",
            price=60_180.0,
        )
    )
    assert d2 is not None


# ---------- decision shape ----------


async def test_decision_carries_size_and_ttl() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0, size_usd=DEFAULT_SIZE_USD)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    assert decision is not None
    assert isinstance(decision, Decision)
    assert decision.size_usd == DEFAULT_SIZE_USD
    assert decision.side == "BUY"
    assert 10 <= decision.ttl_s <= 30
    # price_limit = best_ask + DEFAULT_LIMIT_BUFFER_USD (1¢) so the fill
    # simulator's self-impact estimate doesn't reject the trade.
    assert decision.price_limit == pytest.approx(0.55 + 0.01)


async def test_decision_rationale_carries_metrics() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    assert decision is not None
    rat = decision.rationale
    # Markers consumed by run_paper.py / dashboard
    assert "strategy=spot_aware" in rat
    assert "delta_bps=" in rat
    assert "p_win=" in rat
    assert "ev=" in rat
    assert "side=UP" in rat


# ---------- reset ----------


async def test_reset_clears_state() -> None:
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    await s.on_event(_spot(60_060.0, ts_offset_s=30))
    s.reset()
    # After reset, no boundary, so no fire
    decision = await s.on_event(_spot(60_120.0, ts_offset_s=60))
    assert decision is None


# ---------- defaults ----------


# ---------- aggressive mode ----------


async def test_aggressive_mode_fires_on_sub_5bps_move() -> None:
    """Aggressive mode bypasses Δ_min and uses fallback p_win for sub-5bps."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    # +18 USD on $60k = +3 bps, well below the 5bps prior bucket lower bound
    decision = await s.on_event(_spot(60_018.0, ts_offset_s=30))
    assert decision is not None
    assert decision.asset_id == TOKEN_UP
    # Fallback p_win is 0.54
    assert "p_win=0.540" in decision.rationale
    assert "mode=aggressive" in decision.rationale


async def test_aggressive_mode_fires_above_50bps() -> None:
    """Aggressive mode bypasses Δ_max too — fallback used for >50bps."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    # +600 USD on $60k = +100 bps, way above design Δ_max of 50bps
    decision = await s.on_event(_spot(60_600.0, ts_offset_s=30))
    assert decision is not None
    assert "p_win=0.540" in decision.rationale


async def test_aggressive_mode_still_rejects_85_100_tier() -> None:
    """The scout-validated tier discipline survives aggressive mode."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    # UP side at 0.92 — squarely in the rejected 85-100% tier
    await s.on_event(_book("UP", TOKEN_UP, ask=0.92))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.05))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_018.0, ts_offset_s=30))  # +3bps
    # Aligned UP+up but tier 85-100 still rejected even in aggressive mode
    assert decision is None


async def test_aggressive_mode_still_rejects_below_15pct_tier() -> None:
    """The conservative-by-default <15% tier skip survives aggressive mode."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.10))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.85))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_018.0, ts_offset_s=30))
    assert decision is None


async def test_aggressive_mode_does_not_fire_on_pure_flat() -> None:
    """Δ=0 exactly is undefined alignment — refuse to fire even in aggressive mode."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_000.0, ts_offset_s=30))  # Δ=0 exactly
    assert decision is None


async def test_aggressive_mode_uses_real_prior_when_available() -> None:
    """When (Δ, tier) DOES match a real prior, aggressive mode uses it."""
    s = SpotAwareStrategy(priors=_priors(), aggressive_mode=True)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    decision = await s.on_event(_spot(60_060.0, ts_offset_s=30))  # +10bps
    assert decision is not None
    # The 0.50-0.70:10-20 prior is 0.81, NOT the 0.54 fallback
    assert "p_win=0.810" in decision.rationale


async def test_price_limit_pads_ask_for_simulator_slippage() -> None:
    """Strategy adds limit_buffer to ask so sim's self-impact doesn't reject."""
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0, limit_buffer_usd=0.02)
    await s.on_event(_open())
    await s.on_event(_book("UP", TOKEN_UP, ask=0.55))
    await s.on_event(_book("DOWN", TOKEN_DOWN, ask=0.45))
    await s.on_event(_spot(60_000.0, ts_offset_s=0))
    d = await s.on_event(_spot(60_060.0, ts_offset_s=30))
    assert d is not None
    assert d.price_limit == pytest.approx(0.57)  # 0.55 + 0.02 buffer


async def test_price_limit_caps_at_99c() -> None:
    """Limit + buffer would push past 0.99 — clamp to 0.99 to prevent
    pathological fills above 1.00."""
    s = SpotAwareStrategy(priors=_priors(), delta_min_bps=5.0, limit_buffer_usd=0.10)
    await s.on_event(_open())
    # Aggressive mode + tier 0.70-0.85 — pick a high but not-rejected ask.
    s2 = SpotAwareStrategy(
        priors=_priors(), delta_min_bps=5.0, limit_buffer_usd=0.20, aggressive_mode=True
    )
    await s2.on_event(_open())
    await s2.on_event(_book("UP", TOKEN_UP, ask=0.84))
    await s2.on_event(_book("DOWN", TOKEN_DOWN, ask=0.16))
    await s2.on_event(_spot(60_000.0, ts_offset_s=0))
    d = await s2.on_event(_spot(60_060.0, ts_offset_s=30))
    assert d is not None
    # 0.84 + 0.20 = 1.04, clamped to 0.99
    assert d.price_limit == pytest.approx(0.99)


def test_defaults_match_design_doc() -> None:
    """Sanity-check the locked defaults against design/spot_aware_strategy.md §3-§5."""
    assert DEFAULT_DELTA_MIN_BPS == 8.0
    assert DEFAULT_DELTA_MAX_BPS == 50.0
    assert DEFAULT_SIZE_USD == 5.0  # locked decision #9
    assert DEFAULT_FEE_PCT == 0.005
    assert DEFAULT_EV_MIN_DOLLARS == 0.005

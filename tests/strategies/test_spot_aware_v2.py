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
    OracleUpdate,
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


async def test_v2_caps_price_limit_below_reject_band_when_buffer_would_breach() -> None:
    """Audit 2026-05-10 found 11/299 historical fires leaked into the
    50-70% reject band: ask=0.49 + buffer 0.02 → uncapped limit 0.51 →
    taker effective_ask up to 0.50 (impact cap 1¢) AND maker fill at
    limit=0.51 — both BREACH the band the strategy claimed to reject.
    Net -$15.01 / 36.4% WR. The fix caps price_limit one tick below the
    band's lower bound so neither fill path can land inside.

    With ask=0.49 and the default 50-70% reject band: uncapped limit
    would be 0.51, capped limit must be 0.499. The fire still happens
    (this is a 30-50% tier fire by the ask) but with a tighter limit.
    Asserts the cap is in effect."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.49
    )
    assert decision is not None, "ask=0.49 + 10bps move should still fire (tier 30-50)"
    assert decision.price_limit < 0.50, (
        f"price_limit must be capped below the 50-70% reject band lower bound; "
        f"got {decision.price_limit}"
    )
    assert decision.price_limit >= 0.49, (
        f"cap should be just below the band, not below the ask; " f"got {decision.price_limit}"
    )


def _oracle(price: float, ts_offset_s: int = 1) -> OracleUpdate:
    return OracleUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        price=price,
        round_id=ts_offset_s,
        updated_at_s=WINDOW_TS + ts_offset_s,
    )


async def _drive_with_oracle(
    strat: SpotAwareStrategyV2,
    *,
    open_spot: float,
    end_spot: float,
    oracle_at_fire: float | None,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    """Drive a window where an OracleUpdate (price=oracle_at_fire) is
    delivered before the firing spot tick. Used to exercise the
    spot-vs-oracle gap filter."""
    await strat.on_event(_open())
    await strat.on_event(_spot(open_spot, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=ask_up, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=ask_down, ts_offset_s=2))
    if oracle_at_fire is not None:
        await strat.on_event(_oracle(oracle_at_fire, ts_offset_s=10))
    return await strat.on_event(_spot(end_spot, ts_offset_s=30))


async def test_v2_oracle_gap_disabled_by_default_preserves_legacy_behavior() -> None:
    """Default oracle_gap_min_bps=0 → filter is off. Even with a wildly
    misaligned oracle reading, the fire still happens (legacy v2)."""
    strat = SpotAwareStrategyV2(priors=_priors())  # default oracle_gap_min_bps=0
    # Spot rises (UP-aligned) but oracle is way ABOVE spot, so gap is
    # negative (misaligned for an UP fire). With the filter ON this
    # would abstain; with the default-OFF, it fires.
    decision = await _drive_with_oracle(
        strat,
        open_spot=80_000.0,
        end_spot=80_080.0,  # UP fire
        oracle_at_fire=80_500.0,  # oracle far above spot → gap negative
        ask_up=0.45,
    )
    assert decision is not None
    assert "side=UP" in decision.rationale


async def test_v2_oracle_gap_aligned_passes_when_enabled() -> None:
    """Enable the filter at min=1 bps. Spot 80_120, oracle 80_080 →
    gap = +5 bps, aligned with UP fire. Pass."""
    strat = SpotAwareStrategyV2(priors=_priors(), oracle_gap_min_bps=1.0)
    decision = await _drive_with_oracle(
        strat,
        open_spot=80_000.0,
        end_spot=80_120.0,  # +15bps UP move
        oracle_at_fire=80_080.0,  # spot is +5bps above oracle → aligned with UP
        ask_up=0.45,
    )
    assert decision is not None
    assert "side=UP" in decision.rationale


async def test_v2_oracle_gap_misaligned_blocks_when_enabled() -> None:
    """Filter on; spot rose (UP fire) but oracle is ABOVE spot at fire
    time → gap is negative (oracle expects downward correction). Filter
    blocks the fire."""
    strat = SpotAwareStrategyV2(priors=_priors(), oracle_gap_min_bps=1.0)
    decision = await _drive_with_oracle(
        strat,
        open_spot=80_000.0,
        end_spot=80_080.0,  # UP fire
        oracle_at_fire=80_500.0,  # oracle above spot → gap is negative
        ask_up=0.45,
    )
    assert decision is None


async def test_v2_oracle_gap_aligned_but_too_small_blocks() -> None:
    """Aligned but |gap| < threshold → block. Strategy fires on a 10bps
    delta (open=80_000, end=80_080) but the oracle is at 80_079 → gap
    at fire time is (80_080-80_079)/80_079*10_000 ≈ 0.125 bps. Filter
    set at 1 bps → blocks."""
    strat = SpotAwareStrategyV2(priors=_priors(), oracle_gap_min_bps=1.0)
    decision = await _drive_with_oracle(
        strat,
        open_spot=80_000.0,
        end_spot=80_080.0,  # UP fire (10bps delta vs open)
        oracle_at_fire=80_079.0,  # spot is +0.125 bps above oracle
        ask_up=0.45,
    )
    assert decision is None


async def test_v2_oracle_gap_no_oracle_reading_falls_through() -> None:
    """Cold-start: filter is enabled but no OracleUpdate has arrived
    yet. Strategy must fall through to v2's normal logic (don't penalise
    the bot for not having an oracle reading yet)."""
    strat = SpotAwareStrategyV2(priors=_priors(), oracle_gap_min_bps=1.0)
    decision = await _drive_with_oracle(
        strat,
        open_spot=80_000.0,
        end_spot=80_080.0,
        oracle_at_fire=None,  # no OracleUpdate emitted
        ask_up=0.45,
    )
    assert decision is not None


async def test_v2_oracle_gap_constructor_rejects_negative() -> None:
    with pytest.raises(ValueError, match="oracle_gap_min_bps"):
        SpotAwareStrategyV2(priors=_priors(), oracle_gap_min_bps=-1.0)


async def test_v2_does_not_cap_price_limit_when_safely_below_band() -> None:
    """Sanity: when ask=0.45 + buffer 0.02 yields uncapped limit 0.47,
    well below the 50-70% band, the cap is a no-op and the original
    price_limit is preserved."""
    strat = SpotAwareStrategyV2(priors=_priors())
    decision = await _run_window_to_decision(
        strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.45
    )
    assert decision is not None
    # ask 0.45 + default limit_buffer 0.02 = 0.47, not near the band.
    assert (
        abs(decision.price_limit - 0.47) < 0.001
    ), f"price_limit should equal ask+buffer (0.47); got {decision.price_limit}"


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

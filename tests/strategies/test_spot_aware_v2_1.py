"""Tests for polymarket_bot.strategies.spot_aware_v2_1.SpotAwareStrategyV2_1.

Spec §9.2-9.4 — 13 tests across filters (CH1-CH4), Kelly + rationale
(CH5-CH6), and multi-fire (CH7-CH8). Pattern mirrors
test_spot_aware_v2.py.

A NOTE on CH3 tests + priors: v2.1's tier-relax CH3 lifts the
`delta_min` floor for tiers in `tier_relax_delta`. However, v2's
internal priors-table hit (no-fallback) remains required, and the
shipped priors table starts at `|Δ|=5`. To exercise CH3 in isolation
at |Δ|<5, the relevant tests use a stub priors that always returns
a value. Production "winning cell" firing requires a separate priors
data extension; see design/spot_aware_v2_1.md CH3.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.kelly_config import KellyConfig
from polymarket_bot.strategies.spot_aware_priors import SpotAwarePriors, load_priors
from polymarket_bot.strategies.spot_aware_v2_1 import (
    SpotAwareStrategyV2_1,
    _parse_ev,
    _parse_p_win,
    _rewrite_rationale_v2_1,
)

WINDOW_TS = 1_715_000_100
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


# ---------- fixtures ----------


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


def _book(side: str, asset_id: str, *, ask: float = 0.45, ts_offset_s: int = 30) -> BookUpdate:
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


class _StubPriors:
    """Test-only priors that always returns ``p_win`` regardless of
    bucket. Lets CH3's floor relaxation be tested at |Δ|<5 without
    waiting for the priors data extension. Mirrors SpotAwarePriors's
    duck-typed interface (`lookup` + ``fee_estimate_pct``)."""

    def __init__(self, p_win: float = 0.55, fee_estimate_pct: float = 0.005) -> None:
        self.fee_estimate_pct = fee_estimate_pct
        self._p_win = p_win

    def lookup(self, *, price: float, abs_delta_bps: float) -> float | None:
        return self._p_win


def _real_priors() -> SpotAwarePriors:
    return load_priors()


def _bankroll(value: float = 1000.0):
    def _getter() -> float:
        return value

    return _getter


async def _drive_simple_window(
    strat: SpotAwareStrategyV2_1,
    *,
    open_spot: float,
    end_spot: float,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    """Single qualifying tick through one window. Mirrors v2 helper."""
    await strat.on_event(_open())
    await strat.on_event(_spot(open_spot, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=ask_up, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=ask_down, ts_offset_s=2))
    return await strat.on_event(_spot(end_spot, ts_offset_s=30))


# ---------- §9.2 v2.1 filters (CH1-CH4) ----------


async def test_v2_1_name_marker() -> None:
    """The strategy's `name` attribute is the production telemetry tag."""
    strat = SpotAwareStrategyV2_1(priors=_real_priors(), bankroll_getter=_bankroll())
    assert strat.name == "spot_aware_v2_1"


async def test_v2_1_rejects_delta_zero() -> None:
    """CH1 — Δ=0 → None (no skew at fire time)."""
    strat = SpotAwareStrategyV2_1(priors=_real_priors(), bankroll_getter=_bankroll())
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_000.0, ask_up=0.40)
    assert decision is None


async def test_v2_1_rejects_ev_in_bad_bucket() -> None:
    """CH2 — EV ∈ [0.02, 0.05) → None.

    Construction: stub priors with p_win=0.42 + price 0.40 + fee 0.005
    → ev = 0.42 - (0.40 + 0.005) - (limit buffer) ... Use stub priors
    that returns p_win=0.40 directly so the strategy's ev calc lands in
    [0.02, 0.05). With ask=0.35, limit_buffer=0.02 → price_limit=0.37;
    ev = 0.40 - (0.37 + 0.005) = 0.025 — inside the bad bucket. Tier
    0.35 is admitted (15-30%; in tier_relax) and priors stub hits.
    """
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.40), bankroll_getter=_bankroll())
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_120.0, ask_up=0.35)
    # Decision must be None — CH2 blocks the bad-bucket EV.
    assert decision is None


async def test_v2_1_allows_30_50_with_low_delta() -> None:
    """CH3 — tier 30-50% x |Δ|=2 bps → Decision (floor relaxed).

    Uses stub priors so the priors-table miss doesn't conflate with CH3.
    Production firing on this cell needs the priors data extension (see
    design doc honest-pushback). With p_win=0.55 + price 0.40 → ev =
    0.55 - (0.42 + 0.005) = 0.125, comfortably above the bad bucket
    and above the EV gate.
    """
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.55), bankroll_getter=_bankroll())
    # 2 bps move on $80,000 → $16; end_spot=80_016 → Δ=+2 bps.
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None, "tier 30-50% x |Δ|=2 must fire under CH3 floor relax"
    assert "side=UP" in decision.rationale


async def test_v2_1_requires_5bps_for_70_85() -> None:
    """CH3 — tier 70-85% x |Δ|=2 bps → None (floor not relaxed)."""
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.80), bankroll_getter=_bankroll())
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.75)
    assert decision is None, "tier 70-85% is NOT in tier_relax; the 5 bps floor must still bind"


async def test_v2_1_inherits_tier_50_70_reject() -> None:
    """v2 inheritance — tier 50-70% always rejected, regardless of Δ."""
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.65), bankroll_getter=_bankroll())
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.55)
    assert decision is None


# ---------- CH3 priors-fallback (real priors) ----------


async def test_v2_1_real_priors_fallback_fires_winning_cell() -> None:
    """CH3 priors-fallback — with the SHIPPED priors table (which starts
    at |Δ|=5) and the default fallback p_win=0.48, tier 30-50% x |Δ|=2
    must fire on production-grade inputs. This closes the design doc
    honest-pushback: v2.1 can now exploit Phase G's winning cell out of
    the box (Conservative scenario)."""
    strat = SpotAwareStrategyV2_1(
        priors=_real_priors(),
        bankroll_getter=_bankroll(1000.0),
    )
    # 2 bps move on $80,000 → end_spot=80_016. ask=0.40 in tier 30-50%.
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None, (
        "real priors + fallback p_win=0.48 must fire tier 30-50% x |Δ|=2 " "(Phase G winning cell)"
    )
    assert (
        "p_win=0.480" in decision.rationale
    ), f"fallback p_win=0.48 must surface in rationale; got {decision.rationale!r}"


async def test_v2_1_real_priors_fallback_disabled_does_not_fire() -> None:
    """When fallback is disabled (None), real priors miss at |Δ|=2 →
    v2.1 abstains — preserves spec-literal CH3 semantics for operators
    who want the priors-data path."""
    strat = SpotAwareStrategyV2_1(
        priors=_real_priors(),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_p_win_fallback=None,
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is None


async def test_v2_1_fallback_only_applies_to_tier_relax_tiers() -> None:
    """Fallback is surgical: tier 70-85% x |Δ|=2 still misses + abstains
    even with fallback enabled (because tier 70-85% is NOT in tier_relax).
    Preserves v2's no-fallback semantics outside the CH3 cell."""
    strat = SpotAwareStrategyV2_1(
        priors=_real_priors(),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_p_win_fallback=0.80,  # would fire if applied
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.75)
    assert decision is None


async def test_v2_1_fallback_does_not_override_real_hits() -> None:
    """When real priors HIT (|Δ|≥5), the fallback never replaces them.
    Sanity that the wrapper is transparent for in-table queries."""
    strat = SpotAwareStrategyV2_1(
        priors=_real_priors(),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_p_win_fallback=0.99,  # would dominate Kelly if applied
    )
    # |Δ|=10 hits the real priors table; fallback must NOT replace it.
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.40)
    assert decision is not None
    # The rationale p_win comes from REAL priors, not the 0.99 fallback.
    assert (
        "p_win=0.99" not in decision.rationale
    ), f"fallback p_win must not override real priors hit; got {decision.rationale!r}"


# ---------- §9.3 Kelly + rationale ----------


async def test_v2_1_kelly_sizes_replace_default() -> None:
    """CH5/CH6 — Decision.size_usd is the Kelly bet, NOT v2's flat
    default. Bankroll=$1000, p_win=0.55, price=0.40, kelly_mult=0.10
    → f* = (0.55-0.40)/(1-0.40) = 0.25; bet = 1000 x 0.10 x 0.25 = $25.
    Confirms the size differs from v2's DEFAULT_SIZE_USD."""
    from polymarket_bot.strategies.spot_aware import DEFAULT_SIZE_USD

    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        kelly=KellyConfig(kelly_mult=0.10),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.40)
    assert decision is not None
    assert (
        decision.size_usd != DEFAULT_SIZE_USD
    ), f"Kelly bet should override v2's default; got {decision.size_usd}"
    # v2's default limit_buffer is 0.02 so price_limit=0.42; f*=(0.55-0.42)/0.58≈0.224
    # bet = 1000*0.10*0.224 ≈ $22.4. Sanity-check the magnitude.
    assert 1.0 <= decision.size_usd <= 50.0, f"unexpected Kelly bet ${decision.size_usd}"


async def test_v2_1_rationale_self_tags() -> None:
    """CH8 — rationale carries `strategy=spot_aware_v2_1`, NOT v2's
    marker. Avoids the v3 inheritance bug (defense L1)."""
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.55), bankroll_getter=_bankroll(1000.0))
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.40)
    assert decision is not None
    assert "strategy=spot_aware_v2_1" in decision.rationale
    assert "strategy=spot_aware_v2 " not in decision.rationale
    assert "mode=kelly_multi" in decision.rationale
    assert "mode=tier_restricted" not in decision.rationale


async def test_v2_1_rationale_includes_kelly_metadata() -> None:
    """Spec §7.1: rationale must include kelly_f= bet_usd= bankroll=
    fire_n= tokens for the dashboard + audit tooling."""
    strat = SpotAwareStrategyV2_1(priors=_StubPriors(p_win=0.55), bankroll_getter=_bankroll(1000.0))
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.40)
    assert decision is not None
    for token in ("kelly_f=", "bet_usd=", "bankroll=", "fire_n=1/2"):
        assert (
            token in decision.rationale
        ), f"missing rationale token {token!r}; got {decision.rationale!r}"


async def test_v2_1_no_fire_when_bankroll_too_low() -> None:
    """CH4 — Kelly bet under `min_bet_abs` → None (abstain rather than
    fire a phantom-size record)."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1.0),  # $1 bankroll → bet floor blocks
        kelly=KellyConfig(kelly_mult=0.10, min_bet_abs=1.0),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.40)
    assert decision is None


# ---------- §9.4 Multi-fire (CH7) ----------


async def test_multi_fire_two_per_window() -> None:
    """Two qualifying ticks in the same window → 2 Decisions when
    cap=2. Counter increments; second fire's `fire_n=2/2`."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        multi_fire_cap=2,
    )
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.40, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.40, ts_offset_s=2))
    first = await strat.on_event(_spot(80_080.0, ts_offset_s=30))
    second = await strat.on_event(_spot(80_160.0, ts_offset_s=60))
    assert first is not None
    assert second is not None
    assert "fire_n=1/2" in first.rationale
    assert "fire_n=2/2" in second.rationale


async def test_multi_fire_blocked_at_cap() -> None:
    """Third qualifying tick → None (cap reached)."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        multi_fire_cap=2,
    )
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.40, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.40, ts_offset_s=2))
    a = await strat.on_event(_spot(80_080.0, ts_offset_s=30))
    b = await strat.on_event(_spot(80_160.0, ts_offset_s=60))
    c = await strat.on_event(_spot(80_240.0, ts_offset_s=90))
    assert a is not None
    assert b is not None
    assert c is None, "third fire must be blocked by the multi-fire cap"


async def test_multi_fire_resets_on_window_boundary() -> None:
    """`WindowBoundary(kind='open')` resets the per-window counter so
    a fresh window starts at fire_n=1 again."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        multi_fire_cap=2,
    )
    await strat.on_event(_open())
    await strat.on_event(_spot(80_000.0, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=0.40, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=0.40, ts_offset_s=2))
    first = await strat.on_event(_spot(80_080.0, ts_offset_s=30))
    assert first is not None
    # Cross to a new window.
    next_ts = WINDOW_TS + 300
    await strat.on_event(_close())
    await strat.on_event(
        WindowBoundary(
            ts_utc_ns=next_ts * 1_000_000_000,
            window_ts=next_ts,
            kind="open",
        )
    )
    # Seed the new window. ts_offset_s computed from the NEW window's
    # open, so we feed events at next_ts + offset.
    next_open_ns = next_ts * 1_000_000_000
    await strat.on_event(
        SpotTick(ts_utc_ns=next_open_ns + 1_000_000_000, source="binance", price=80_000.0)
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=next_open_ns + 2_000_000_000,
            asset_id=TOKEN_UP,
            side="UP",
            best_bid=0.38,
            best_ask=0.40,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=next_open_ns + 2_000_000_000,
            asset_id=TOKEN_DOWN,
            side="DOWN",
            best_bid=0.38,
            best_ask=0.40,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    new_window_first = await strat.on_event(
        SpotTick(ts_utc_ns=next_open_ns + 30_000_000_000, source="binance", price=80_080.0)
    )
    assert new_window_first is not None
    assert "fire_n=1/2" in new_window_first.rationale


# ---------- helpers tested directly ----------


def test_parse_ev_and_p_win() -> None:
    """Rationale parsers tolerate v2's exact format + odd whitespace."""
    rat = (
        "strategy=spot_aware_v2 mode=tier_restricted delta_bps=+5.02 "
        "p_win=0.400 ev=+0.1650 ttl=30s side=UP"
    )
    assert _parse_p_win(rat) == 0.400
    assert _parse_ev(rat) == 0.1650
    # Negative EV format
    rat2 = rat.replace("+0.1650", "-0.0125")
    assert _parse_ev(rat2) == -0.0125
    # Missing field returns None
    assert _parse_p_win("strategy=other") is None
    assert _parse_ev("strategy=other") is None


def test_rewrite_rationale_self_tags_and_appends() -> None:
    """The rewrite swaps strategy + mode markers and appends Kelly tokens."""
    rat = (
        "strategy=spot_aware_v2 mode=tier_restricted delta_bps=+5.02 "
        "p_win=0.500 ev=+0.0500 ttl=30s side=UP"
    )
    out = _rewrite_rationale_v2_1(
        rat, kelly_f=0.25, bet_usd=22.40, bankroll=1006.01, fire_n=1, cap=2
    )
    assert "strategy=spot_aware_v2_1" in out
    assert "strategy=spot_aware_v2 " not in out  # the bare v2 marker must be gone
    assert "mode=kelly_multi" in out
    assert "mode=tier_restricted" not in out
    assert "kelly_f=0.250" in out
    assert "bet_usd=22.40" in out
    assert "bankroll=1006.01" in out
    assert "fire_n=1/2" in out


# ---------- constructor validation ----------


def test_v2_1_rejects_invalid_multi_fire_cap() -> None:
    with pytest.raises(ValueError, match="multi_fire_cap"):
        SpotAwareStrategyV2_1(priors=_real_priors(), bankroll_getter=_bankroll(), multi_fire_cap=0)


def test_v2_1_rejects_invalid_ev_bucket() -> None:
    with pytest.raises(ValueError, match="ev_bad_bucket"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            ev_bad_bucket=(0.05, 0.02),
        )


# ---------- H.2.12 path A: per-tier side block ----------


async def test_v2_1_block_up_in_tier_70_85_abstains() -> None:
    """Path A — when SPOT_AWARE_BLOCK_UP_IN_TIERS includes '70-85%', an
    UP candidate in that tier MUST abstain even if all other gates
    pass. Uses ask=0.72 + p_win=0.85 so EV=0.105 is comfortably above
    the gate — proves path A is the abstaining cause, not the EV
    filter."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        block_up_in_tiers=("70-85%",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72)
    assert decision is None, "block_up_in_tiers must reject UP fire in 70-85%"


async def test_v2_1_block_up_does_not_apply_to_other_tiers() -> None:
    """Path A is surgical: blocking UP in 70-85% must NOT affect UP
    fires in other tiers (e.g., 30-50%)."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        block_up_in_tiers=("70-85%",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.45)
    assert decision is not None, "tier 30-50% UP must still fire when only 70-85% is blocked"


async def test_v2_1_block_up_does_not_block_down_in_same_tier() -> None:
    """Path A is direction-specific: blocking UP in tier 70-85% must NOT
    affect DOWN fires in the same tier. Tier 70-85% DOWN-only is the
    intent."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        block_up_in_tiers=("70-85%",),
    )
    # Spot FALLS → bot bets DOWN. ask_down in tier 70-85% (=0.72) keeps
    # EV well above gate.
    decision = await _drive_simple_window(
        strat, open_spot=80_000.0, end_spot=79_920.0, ask_down=0.72
    )
    assert decision is not None
    assert "side=DOWN" in decision.rationale


async def test_v2_1_block_down_symmetric() -> None:
    """Symmetric block_down_in_tiers: a DOWN candidate in a blocked tier
    must abstain. (Reserved for future tier 15-30% analysis.)"""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        block_down_in_tiers=("70-85%",),
    )
    decision = await _drive_simple_window(
        strat, open_spot=80_000.0, end_spot=79_920.0, ask_down=0.72
    )
    assert decision is None


async def test_v2_1_empty_block_tuples_are_noop() -> None:
    """Default empty tuples must not affect any firing decisions."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        block_up_in_tiers=(),
        block_down_in_tiers=(),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72)
    assert decision is not None
    assert "side=UP" in decision.rationale


def test_v2_1_rejects_invalid_p_win_fallback() -> None:
    """Fallback must be in (0, 1) or None — outside that range raises."""
    with pytest.raises(ValueError, match="tier_relax_p_win_fallback"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            tier_relax_p_win_fallback=1.5,
        )
    with pytest.raises(ValueError, match="tier_relax_p_win_fallback"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            tier_relax_p_win_fallback=0.0,
        )


# ---------- Phase J.1: CH3 price floor in tier_relax ----------


async def test_v2_1_blocks_below_price_floor_in_tier_relax() -> None:
    """J.1 — A CH3 cell fire with price_limit < floor MUST abstain.
    Construction: stub priors p_win=0.55 + ask=0.25 (tier 15-30%);
    v2's default limit_buffer=0.02 → price_limit=0.27. With floor=0.30,
    27 < 30 → block. Reset _fired_for_window per spec."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_price_floor=0.30,
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.25)
    assert decision is None, "CH3 fire with price_limit<floor must abstain"


async def test_v2_1_does_not_block_at_or_above_price_floor() -> None:
    """J.1 — A CH3 cell fire with price_limit ≥ floor MUST fire through.
    Construction: stub priors p_win=0.55 + ask=0.43 (tier 30-50%);
    v2's default limit_buffer=0.02 → price_limit=0.45 ≥ 0.42 floor."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_price_floor=0.42,
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.43)
    assert decision is not None, "CH3 fire with price_limit≥floor must fire"
    assert "side=UP" in decision.rationale


async def test_v2_1_price_floor_does_not_apply_outside_tier_relax() -> None:
    """J.1 — The floor is SURGICAL to tier_relax cells. Tier 70-85% (NOT
    in tier_relax) ignores the floor and fires on its own gates.
    Construction: stub p_win=0.85 + ask=0.72 (tier 70-85%); v2's
    limit_buffer=0.02 → price_limit=0.74. Floor=0.90 would block IF
    applied, but tier 70-85% is outside scope — fire proceeds."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_price_floor=0.90,  # would block if applied
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72)
    assert decision is not None, "tier 70-85% must ignore the tier_relax floor"


async def test_v2_1_price_floor_zero_is_disabled() -> None:
    """J.1 — Setting floor=0.0 is the explicit kill-switch: every CH3
    cell fire passes the floor check regardless of price_limit. Mirrors
    the SPOT_AWARE_TIER_RELAX_PRICE_FLOOR=0 operator override path."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        tier_relax_price_floor=0.0,  # kill-switch
    )
    # ask=0.18 → price_limit=0.20; floor=0 means no block.
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.18)
    assert decision is not None, "floor=0.0 must disable the J.1 check entirely"


def test_v2_1_rejects_invalid_price_floor() -> None:
    """J.1 — Floor must be in [0.0, 1.0). Out-of-range raises."""
    with pytest.raises(ValueError, match="tier_relax_price_floor"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            tier_relax_price_floor=1.0,
        )
    with pytest.raises(ValueError, match="tier_relax_price_floor"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            tier_relax_price_floor=-0.1,
        )


# ---------- Phase J.2: hour-of-day blocklist ----------


import datetime as _dt  # noqa: E402  (test helper; grouped with J.2 fixtures)


async def _drive_window_at(
    strat: SpotAwareStrategyV2_1,
    *,
    window_ts: int,
    open_spot: float,
    end_spot: float,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    """Drive one window where the timestamp is controlled by the caller
    (so hour-of-day tests can put the fire at a chosen UTC hour)."""
    open_ns = window_ts * 1_000_000_000
    await strat.on_event(WindowBoundary(ts_utc_ns=open_ns, window_ts=window_ts, kind="open"))
    await strat.on_event(
        SpotTick(ts_utc_ns=open_ns + 1_000_000_000, source="binance", price=open_spot)
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=open_ns + 2_000_000_000,
            asset_id=TOKEN_UP,
            side="UP",
            best_bid=max(0.01, ask_up - 0.02),
            best_ask=ask_up,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    await strat.on_event(
        BookUpdate(
            ts_utc_ns=open_ns + 2_000_000_000,
            asset_id=TOKEN_DOWN,
            side="DOWN",
            best_bid=max(0.01, ask_down - 0.02),
            best_ask=ask_down,
            bid_size_top=100.0,
            ask_size_top=100.0,
        )
    )
    return await strat.on_event(
        SpotTick(ts_utc_ns=open_ns + 30_000_000_000, source="binance", price=end_spot)
    )


def _ts_at_utc_hour(hour: int) -> int:
    """Return a unix seconds timestamp whose UTC hour is the given hour."""
    return int(_dt.datetime(2026, 5, 13, hour, 0, 0, tzinfo=_dt.UTC).timestamp())


async def test_v2_1_blocks_at_blocklist_hour_for_blocked_tier() -> None:
    """J.2 — A fire at UTC 23:00 in tier 70-85% with that tier in the
    blocklist MUST abstain. Construction: stub p_win=0.85 + ask=0.72
    (tier 70-85%) — EV is well above gate; the blocklist is the cause
    of abstain."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        hour_blocklist_utc=(23,),
        hour_blocklist_tiers=("70-85%",),
    )
    ts_23 = _ts_at_utc_hour(23)
    decision = await _drive_window_at(
        strat, window_ts=ts_23, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72
    )
    assert decision is None, "23Z x 70-85% with blocklist active must abstain"


async def test_v2_1_does_not_block_outside_blocklist_hour() -> None:
    """J.2 — At UTC 12:00 (NOT in blocklist), the same fire fires through.
    Same tier as the blocked test; only hour differs."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        hour_blocklist_utc=(23,),
        hour_blocklist_tiers=("70-85%",),
    )
    ts_12 = _ts_at_utc_hour(12)
    decision = await _drive_window_at(
        strat, window_ts=ts_12, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72
    )
    assert decision is not None, "12Z x 70-85% must fire (hour not blocked)"
    assert "side=UP" in decision.rationale


async def test_v2_1_does_not_block_at_blocklist_hour_for_other_tier() -> None:
    """J.2 — At UTC 23:00 but in tier 30-50% (NOT in blocklist), the
    fire fires through. Blocklist is scoped to 70-85% only.

    Disables the J.1 floor so the price (0.45) doesn't get caught by
    that filter — isolates the hour-blocklist behavior."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(1000.0),
        hour_blocklist_utc=(23,),
        hour_blocklist_tiers=("70-85%",),
        tier_relax_price_floor=0.0,
    )
    ts_23 = _ts_at_utc_hour(23)
    decision = await _drive_window_at(
        strat, window_ts=ts_23, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.45
    )
    assert decision is not None, "23Z x 30-50% must fire (tier not blocked)"
    assert "side=UP" in decision.rationale


async def test_v2_1_empty_hour_blocklist_is_noop() -> None:
    """J.2 — With both blocklists empty (default), every fire passes
    through regardless of hour. Even at 23Z, a 70-85% fire fires."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.85),
        bankroll_getter=_bankroll(1000.0),
        # defaults: both tuples empty
    )
    ts_23 = _ts_at_utc_hour(23)
    decision = await _drive_window_at(
        strat, window_ts=ts_23, open_spot=80_000.0, end_spot=80_080.0, ask_up=0.72
    )
    assert decision is not None, "empty blocklist must be noop"


def test_v2_1_empty_tier_scope_is_rejected_at_init() -> None:
    """J.2 — Setting hours without tier scope is a misconfiguration:
    block-all-tiers at an hour is not supported. Init must raise.
    Also covers out-of-range hour validation."""
    with pytest.raises(ValueError, match="hour_blocklist_tiers"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            hour_blocklist_utc=(23,),
            hour_blocklist_tiers=(),
        )
    with pytest.raises(ValueError, match="hour_blocklist_utc"):
        SpotAwareStrategyV2_1(
            priors=_real_priors(),
            bankroll_getter=_bankroll(),
            hour_blocklist_utc=(24,),
            hour_blocklist_tiers=("70-85%",),
        )

"""Tests for polymarket_bot.strategies.spot_aware_v3.SpotAwareStrategyV3.

Per design/regime_detector.md §"Wrapping v2 strategy" + the validation
gate (a) at runbooks/gate-evidence/regime-classifier-validation.txt.
v3 inherits all of v2's behavior; the only new logic is a regime gate
applied AFTER v2 decides to fire. Three behaviors to cover:

  1. v3 fires when v2 would AND regime classifier says "trending".
  2. v3 abstains when v2 would fire BUT regime is "chop" / "mixed".
  3. v3 abstains when regime is "unknown" (cold-start buffer).

Plus a 4th: re-evaluation. v2 sets a per-window fire flag inside
_maybe_fire so it never fires twice. v3 has to clear that flag when
it gates AFTER the fact, so a regime that flips mid-window can still
let v2 re-fire on a later tick.
"""

from __future__ import annotations

import pytest

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.regime_detector import Regime, RegimeDetector
from polymarket_bot.strategies.spot_aware_priors import (
    SpotAwarePriors,
    load_priors,
)
from polymarket_bot.strategies.spot_aware_v3 import SpotAwareStrategyV3


class _FixedRegimeDetector(RegimeDetector):
    """Test stub: returns a hard-coded regime regardless of buffer
    contents. Decouples the v3-wrapper tests (does v3 gate correctly?)
    from the detector's classify() math (already covered in
    test_regime_detector.py)."""

    def __init__(self, regime: Regime) -> None:
        super().__init__()
        self._fixed = regime

    def classify(self, now_ns: int) -> Regime:  # type: ignore[override]
        return self._fixed


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


def _spot(price: float, ts_offset_s: int = 0, source: str = "binance") -> SpotTick:
    return SpotTick(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        source=source,  # type: ignore[arg-type]
        price=price,
    )


def _priors() -> SpotAwarePriors:
    return load_priors()


async def _drive_v3_to_decision(
    strat: SpotAwareStrategyV3,
    *,
    open_spot: float = 80_000.0,
    end_spot: float = 80_080.0,
    ask_up: float = 0.45,
    ask_down: float = 0.45,
) -> Decision | None:
    """Drive v3 through one window. Caller is expected to have pre-seeded
    the regime detector buffer to the desired classification BEFORE
    calling this; we don't pump enough spot ticks here to fill the buffer
    organically."""
    await strat.on_event(_open())
    await strat.on_event(_spot(open_spot, ts_offset_s=1))
    await strat.on_event(_book("UP", TOKEN_UP, ask=ask_up, ts_offset_s=2))
    await strat.on_event(_book("DOWN", TOKEN_DOWN, ask=ask_down, ts_offset_s=2))
    return await strat.on_event(_spot(end_spot, ts_offset_s=30))


# ----------------------------------------------------------------------
# Test 1 — v3 fires when v2 would AND regime is trending
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_fires_when_v2_fires_and_regime_trending() -> None:
    """Underlying v2 decides to fire (tier 30-50%, |Δ|=10bps, EV positive)
    AND the regime detector says 'trending' → v3 lets the fire through."""
    strat = SpotAwareStrategyV3(priors=_priors(), regime_detector=_FixedRegimeDetector("trending"))
    decision = await _drive_v3_to_decision(strat)
    assert decision is not None
    assert "strategy=spot_aware_v2" in decision.rationale  # v3 inherits v2 marker
    assert "side=UP" in decision.rationale


# ----------------------------------------------------------------------
# Test 2 — v3 abstains when v2 would fire BUT regime is chop
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_abstains_when_regime_chop() -> None:
    """Same v2-firing setup as test 1, but the regime detector says
    'chop'. v3 must drop the decision."""
    strat = SpotAwareStrategyV3(priors=_priors(), regime_detector=_FixedRegimeDetector("chop"))
    decision = await _drive_v3_to_decision(strat)
    assert decision is None


@pytest.mark.asyncio
async def test_v3_abstains_when_regime_mixed() -> None:
    """Same v2-firing setup, regime classifier returns 'mixed'
    (between thresholds). v3 abstains — only 'trending' is allowed."""
    strat = SpotAwareStrategyV3(priors=_priors(), regime_detector=_FixedRegimeDetector("mixed"))
    decision = await _drive_v3_to_decision(strat)
    assert decision is None


# ----------------------------------------------------------------------
# Test 3 — v3 abstains when regime is unknown (cold-start)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_abstains_when_regime_unknown_cold_start() -> None:
    """Default detector with no pre-seeded ticks (cold-start). Driving
    a window only adds 2 ticks (_spot calls in _drive_v3_to_decision),
    well below min_samples=10. classify() returns 'unknown'; v3 abstains."""
    strat = SpotAwareStrategyV3(priors=_priors())  # default fresh detector
    decision = await _drive_v3_to_decision(strat)
    assert decision is None


# ----------------------------------------------------------------------
# Test 4 — gating doesn't permanently block re-evaluation in the same
# window. v2's _fired_for_window flag is cleared when v3 abstains, so a
# later tick (after the regime potentially changes) can fire.
# ----------------------------------------------------------------------


class _MutableRegimeDetector(RegimeDetector):
    """Test stub whose returned regime can be flipped between calls.
    Used to simulate a regime change mid-window."""

    def __init__(self, initial: Regime) -> None:
        super().__init__()
        self.regime: Regime = initial

    def classify(self, now_ns: int) -> Regime:  # type: ignore[override]
        return self.regime


@pytest.mark.asyncio
async def test_v3_clears_v2_fire_flag_when_abstaining_so_window_can_retry() -> None:
    """v2 sets a per-window _fired_for_window flag inside its
    _maybe_fire path. If v3 simply returned None after the gate, the
    flag would stay set and a later same-window tick (with a flipped
    regime) couldn't re-fire. v3 has to clear the flag when gating
    AFTER v2 commits. This test forces a chop→trending flip mid-window
    and asserts the second tick fires."""
    detector = _MutableRegimeDetector("chop")
    strat = SpotAwareStrategyV3(priors=_priors(), regime_detector=detector)

    first = await _drive_v3_to_decision(strat)
    assert first is None, "chop regime → v3 abstains on first tick"

    # Flip the regime mid-window and feed another tick at ts_offset_s=60
    detector.regime = "trending"
    second = await strat.on_event(_spot(80_120.0, ts_offset_s=60))
    assert second is not None, (
        "v3 should let v2 re-fire on a later tick once regime flips to "
        "trending — meaning the per-window fire-flag must have been cleared "
        "when v3 abstained on the first tick"
    )


# ----------------------------------------------------------------------
# Test 5 — v3's name marker
# ----------------------------------------------------------------------


def test_v3_name_marker() -> None:
    strat = SpotAwareStrategyV3(priors=_priors())
    assert strat.name == "spot_aware_v3"


def test_v3_exposes_regime_detector_for_observability() -> None:
    detector = RegimeDetector()
    strat = SpotAwareStrategyV3(priors=_priors(), regime_detector=detector)
    assert strat.regime_detector is detector

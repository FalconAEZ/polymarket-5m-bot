"""Tests for polymarket_bot.strategies.market_mode_detector.

Phase P Session 3 — covers the public surface per design/P.1 §8 test budget:
  1. __init__ validation
  2. push_bar buffer accumulation
  3. latest() UNKNOWN when buffer < 30 bars
  4. latest() UP under synthetic uptrend
  5. latest() DOWN under synthetic downtrend
  6. latest() CHOPPY under compressed flat
  7. latest() MIXED otherwise
  8. exception in classifier → UNKNOWN
  9. `ta` missing → no-op stub returning UNKNOWN
 10. confidence ∈ [0, 1] for every label
 11. MmdBinanceKlinePoller.poll_once happy path
 12. MmdBinanceKlinePoller.poll_once HTTP error propagates
 13. MmdBinanceKlinePoller.poll_once malformed JSON raises
 14. MmdBinanceKlinePoller.run polls, then stops cleanly when event set
 15. MmdBinanceKlinePoller.run survives a single poll exception

Plus 4 strategy-side tests (mmd_getter integration) — they live here
rather than test_spot_aware_v2_1.py so all MMD coverage is in one file.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from polymarket_bot.strategies.market_mode_detector import (
    MarketModeDetector,
    MmdBinanceKlinePoller,
    MmdReading,
    _unknown_reading,
)
from polymarket_bot.strategies.spot_aware_v2_1 import SpotAwareStrategyV2_1

# Re-use the v2_1 test fixtures for the strategy-side tests.
from tests.strategies.test_spot_aware_v2_1 import (
    _bankroll,
    _drive_simple_window,
    _StubPriors,
)

# ────────────────────────────────────────────────────────────────────────────
# MarketModeDetector — construction + buffer
# ────────────────────────────────────────────────────────────────────────────


def test_mmd_init_defaults_ok() -> None:
    m = MarketModeDetector()
    assert m.lookback_min == 60
    assert m.bar_count() == 0


def test_mmd_init_validates_lookback_min() -> None:
    with pytest.raises(ValueError, match=r"lookback_min must be >= 30"):
        MarketModeDetector(lookback_min=29)


def test_mmd_init_validates_adx_thresholds() -> None:
    with pytest.raises(ValueError, match=r"adx_weak_threshold must be <"):
        MarketModeDetector(adx_weak_threshold=30.0, adx_strong_threshold=25.0)


def test_mmd_init_validates_positive_bps_thresholds() -> None:
    with pytest.raises(ValueError, match=r"bb_compressed_bps must be > 0"):
        MarketModeDetector(bb_compressed_bps=0.0)
    with pytest.raises(ValueError, match=r"momentum_threshold_bps must be > 0"):
        MarketModeDetector(momentum_threshold_bps=-1.0)


def test_mmd_push_bar_accumulates_to_lookback() -> None:
    m = MarketModeDetector(lookback_min=30)
    for i in range(40):
        m.push_bar(open_=100.0, high=101.0, low=99.0, close=100.5, volume=1.0, ts_ns=i)
    # deque maxlen caps at lookback_min
    assert m.bar_count() == 30


def test_mmd_clear_buffer_empties() -> None:
    m = MarketModeDetector(lookback_min=30)
    for i in range(5):
        m.push_bar(open_=1.0, high=1.0, low=1.0, close=1.0, volume=0.0, ts_ns=i)
    assert m.bar_count() == 5
    m.clear_buffer()
    assert m.bar_count() == 0


# ────────────────────────────────────────────────────────────────────────────
# MarketModeDetector — latest() label production
# ────────────────────────────────────────────────────────────────────────────


def _fill_bars(m: MarketModeDetector, closes: list[float], *, jitter: float = 0.0) -> None:
    for i, c in enumerate(closes):
        m.push_bar(
            open_=c - jitter,
            high=c + jitter,
            low=c - jitter,
            close=c,
            volume=1.0,
            ts_ns=i * 60_000_000_000,
        )


def test_mmd_latest_unknown_when_buffer_under_30() -> None:
    m = MarketModeDetector()
    for i in range(20):
        m.push_bar(open_=100.0, high=100.0, low=100.0, close=100.0, volume=0.0, ts_ns=i)
    r = m.latest()
    assert r.label == "UNKNOWN"
    assert r.confidence == 0.0
    assert r.bar_count == 20


def test_mmd_latest_up_on_synthetic_uptrend() -> None:
    """Linearly rising close (+0.1% per bar for 60 bars) is a strong uptrend."""
    m = MarketModeDetector()
    closes = [100.0 + i * 0.1 for i in range(60)]  # +0.1 per bar = ~10% over 60 bars
    _fill_bars(m, closes, jitter=0.05)
    r = m.latest()
    assert r.label == "UP", f"expected UP got {r}"
    assert 0.0 <= r.confidence <= 1.0
    assert r.momentum_bps > 0  # positive momentum
    assert r.bar_count == 60


def test_mmd_latest_down_on_synthetic_downtrend() -> None:
    """Linearly falling close (-0.1% per bar for 60 bars)."""
    m = MarketModeDetector()
    closes = [110.0 - i * 0.1 for i in range(60)]
    _fill_bars(m, closes, jitter=0.05)
    r = m.latest()
    assert r.label == "DOWN", f"expected DOWN got {r}"
    assert 0.0 <= r.confidence <= 1.0
    assert r.momentum_bps < 0


def test_mmd_latest_choppy_on_compressed_flat() -> None:
    """Very tight oscillation (±0.005% amplitude) for 60 bars: ADX low + BB compressed."""
    m = MarketModeDetector(bb_compressed_bps=50.0)  # widen the chop threshold slightly
    closes = [100.0 + (0.005 if i % 2 == 0 else -0.005) for i in range(60)]
    _fill_bars(m, closes, jitter=0.001)
    r = m.latest()
    assert r.label == "CHOPPY", f"expected CHOPPY got {r}"
    assert r.adx < 20.0


def test_mmd_latest_mixed_when_neither_trend_nor_chop() -> None:
    """Moderate noise around a flat midline — neither trending nor compressed."""
    m = MarketModeDetector()
    # ADX moderate, BB-width above the chop threshold.
    closes = []
    for i in range(60):
        # quasi-random walk with no overall drift
        closes.append(100.0 + (1.5 if i % 6 < 3 else -1.5))
    _fill_bars(m, closes, jitter=0.3)
    r = m.latest()
    assert r.label == "MIXED", f"expected MIXED got {r}"
    assert r.confidence == 0.5


def test_mmd_latest_confidence_always_in_unit_interval() -> None:
    """Confidence is clamped to [0, 1] for every label."""
    m = MarketModeDetector()
    # Extreme uptrend to push ADX to ~100
    closes = [100.0 + i * 1.0 for i in range(60)]
    _fill_bars(m, closes, jitter=0.5)
    r = m.latest()
    assert 0.0 <= r.confidence <= 1.0


def test_mmd_latest_returns_unknown_on_classifier_exception() -> None:
    """Patch the ta import surface to raise; latest() returns UNKNOWN."""
    m = MarketModeDetector()
    _fill_bars(m, [100.0 + i * 0.1 for i in range(60)])
    with patch(
        "polymarket_bot.strategies.market_mode_detector.MarketModeDetector._classify",
        side_effect=RuntimeError("synthetic indicator failure"),
    ):
        r = m.latest()
    assert r.label == "UNKNOWN"
    assert r.confidence == 0.0


def test_mmd_no_op_stub_when_ta_missing() -> None:
    """If `ta` failed to import at construction, latest() always returns UNKNOWN."""
    m = MarketModeDetector()
    m._ta_available = False  # simulate the import-time fallback
    _fill_bars(m, [100.0 + i * 0.1 for i in range(60)])
    r = m.latest()
    assert r.label == "UNKNOWN"
    assert r.bar_count == 60


def test_mmd_unknown_reading_helper() -> None:
    r = _unknown_reading(sampled_at_ns=123, bar_count=7)
    assert r.label == "UNKNOWN"
    assert r.confidence == 0.0
    assert r.adx == 0.0
    assert r.bar_count == 7
    assert r.sampled_at_ns == 123


# ────────────────────────────────────────────────────────────────────────────
# MmdBinanceKlinePoller — async behavior
# ────────────────────────────────────────────────────────────────────────────


def _fake_klines_payload(n: int = 60) -> list[list[object]]:
    """Binance kline schema: [open_time_ms, open, high, low, close, volume, ...]."""
    rows: list[list[object]] = []
    base_ts = 1_700_000_000_000
    for i in range(n):
        rows.append(
            [
                base_ts + i * 60_000,
                f"{100.0 + i * 0.1:.4f}",
                f"{100.5 + i * 0.1:.4f}",
                f"{99.5 + i * 0.1:.4f}",
                f"{100.2 + i * 0.1:.4f}",
                "1.0",
            ]
        )
    return rows


@pytest.mark.asyncio
async def test_poller_poll_once_happy_path() -> None:
    m = MarketModeDetector(lookback_min=60)
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = _fake_klines_payload(60)
    response.raise_for_status = MagicMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    poller = MmdBinanceKlinePoller(m, client=client)
    n = await poller.poll_once()
    assert n == 60
    assert m.bar_count() == 60
    client.get.assert_awaited_once()
    # verify the query used the symbol + 1m interval
    call_args = client.get.await_args
    assert call_args.kwargs["params"]["symbol"] == "BTCUSDT"
    assert call_args.kwargs["params"]["interval"] == "1m"


@pytest.mark.asyncio
async def test_poller_poll_once_http_error_propagates() -> None:
    m = MarketModeDetector(lookback_min=30)
    client = AsyncMock(spec=httpx.AsyncClient)
    err = httpx.HTTPStatusError(
        "429 too many requests",
        request=MagicMock(),
        response=MagicMock(status_code=429),
    )
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status = MagicMock(side_effect=err)
    client.get = AsyncMock(return_value=response)
    poller = MmdBinanceKlinePoller(m, client=client)
    with pytest.raises(httpx.HTTPStatusError):
        await poller.poll_once()


@pytest.mark.asyncio
async def test_poller_poll_once_rejects_malformed_payload() -> None:
    m = MarketModeDetector(lookback_min=30)
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = {"unexpected": "dict"}
    response.raise_for_status = MagicMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    poller = MmdBinanceKlinePoller(m, client=client)
    with pytest.raises(ValueError, match=r"unexpected klines response shape"):
        await poller.poll_once()


@pytest.mark.asyncio
async def test_poller_run_polls_then_stops() -> None:
    m = MarketModeDetector(lookback_min=30)
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = _fake_klines_payload(30)
    response.raise_for_status = MagicMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    client.aclose = AsyncMock(return_value=None)
    poller = MmdBinanceKlinePoller(m, client=client, poll_interval_s=1.0)
    stop = asyncio.Event()

    async def stop_after_one_poll() -> None:
        # Allow one poll iteration, then signal stop.
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(poller.run(stop=stop), stop_after_one_poll())
    # The poller drained at least one poll.
    assert client.get.await_count >= 1
    assert m.bar_count() == 30
    assert poller.consecutive_failures == 0


@pytest.mark.asyncio
async def test_poller_run_survives_a_single_poll_exception() -> None:
    m = MarketModeDetector(lookback_min=30)
    client = AsyncMock(spec=httpx.AsyncClient)
    # First call raises, subsequent calls return valid data.
    good_response = MagicMock(spec=httpx.Response)
    good_response.json.return_value = _fake_klines_payload(30)
    good_response.raise_for_status = MagicMock(return_value=None)
    bad_response = MagicMock(spec=httpx.Response)
    bad_response.raise_for_status = MagicMock(side_effect=RuntimeError("boom"))
    call_n = {"i": 0}

    async def get_side_effect(*args: object, **kwargs: object) -> MagicMock:
        call_n["i"] += 1
        return bad_response if call_n["i"] == 1 else good_response

    client.get = AsyncMock(side_effect=get_side_effect)
    client.aclose = AsyncMock(return_value=None)
    poller = MmdBinanceKlinePoller(m, client=client, poll_interval_s=0.05)
    stop = asyncio.Event()

    async def driver() -> None:
        # Wait until the buffer recovers (poller's second poll succeeded),
        # then stop. Hard cap at ~2s so the test doesn't hang.
        for _ in range(40):
            if m.bar_count() > 0:
                break
            await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(poller.run(stop=stop), driver())
    assert m.bar_count() == 30
    assert call_n["i"] >= 2  # at least one failure + one success
    assert poller.consecutive_failures == 0  # reset on recovery


# ────────────────────────────────────────────────────────────────────────────
# Strategy plumbing: mmd_getter on SpotAwareStrategyV2_1
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeReading:
    label: str
    confidence: float


async def test_strategy_mmd_getter_none_path_unchanged() -> None:
    """Without an MMD getter the strategy fires exactly as J.1.6 did."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=None,
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=" not in decision.rationale


async def test_strategy_shadow_annotates_but_never_abstains() -> None:
    """mmd_mode=shadow + abstain={CHOPPY} + getter→CHOPPY: fires anyway."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="CHOPPY", confidence=0.7),
        mmd_mode="shadow",
        mmd_labels_to_abstain=("CHOPPY",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=CHOPPY" in decision.rationale
    assert "mmd_conf=0.70" in decision.rationale


async def test_strategy_gate_abstains_on_configured_label() -> None:
    """mmd_mode=gate + abstain={CHOPPY} + getter→CHOPPY: returns None (abstain)."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="CHOPPY", confidence=0.7),
        mmd_mode="gate",
        mmd_labels_to_abstain=("CHOPPY",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is None


async def test_strategy_gate_fires_on_unblocked_label() -> None:
    """mmd_mode=gate + abstain={CHOPPY} + getter→MIXED: fires + annotates."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="MIXED", confidence=0.5),
        mmd_mode="gate",
        mmd_labels_to_abstain=("CHOPPY",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=MIXED" in decision.rationale


async def test_strategy_gate_treats_unknown_as_passthrough() -> None:
    """UNKNOWN must never gate, even when listed in abstain set + gate mode."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="UNKNOWN", confidence=0.0),
        mmd_mode="gate",
        mmd_labels_to_abstain=("UNKNOWN", "CHOPPY"),  # try to gate UNKNOWN
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=UNKNOWN" in decision.rationale


async def test_strategy_getter_exception_treated_as_unknown() -> None:
    """If the MMD getter raises, the strategy treats it as UNKNOWN + still fires."""

    def boom() -> object:
        raise RuntimeError("synthetic getter crash")

    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=boom,
        mmd_mode="gate",
        mmd_labels_to_abstain=("CHOPPY",),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=UNKNOWN" in decision.rationale


async def test_strategy_init_rejects_invalid_mmd_mode() -> None:
    with pytest.raises(ValueError, match=r"mmd_mode must be one of"):
        SpotAwareStrategyV2_1(
            priors=_StubPriors(p_win=0.55),
            bankroll_getter=_bankroll(),
            mmd_mode="bogus",
        )


async def test_strategy_set_mmd_getter_rebinds() -> None:
    """set_mmd_getter swaps the getter post-construction (run_paper wires this)."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=None,
    )
    strat.set_mmd_getter(lambda: _FakeReading(label="MIXED", confidence=0.5))
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=MIXED" in decision.rationale
    # Now unwire it.
    strat.set_mmd_getter(None)
    decision2 = await _drive_simple_window(
        strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40
    )
    assert decision2 is not None
    assert "mmd=" not in decision2.rationale


# ────────────────────────────────────────────────────────────────────────────
# Phase Q aggressive: MMD_ABSTAIN_BY_SIDE side-specific gate
# ────────────────────────────────────────────────────────────────────────────


async def test_strategy_side_gate_abstains_matching_label_and_side() -> None:
    """MMD_ABSTAIN_BY_SIDE=(MIXED,UP): abstain UP-side fires in MIXED regime."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="MIXED", confidence=0.5),
        mmd_mode="gate",
        mmd_labels_to_abstain=(),
        mmd_abstain_by_side=(("MIXED", "UP"),),
    )
    # UP-side fire in MIXED → should abstain (side gate matches)
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is None


async def test_strategy_side_gate_allows_unmatched_side() -> None:
    """MMD_ABSTAIN_BY_SIDE=(MIXED,UP): DOWN-side fires in MIXED still fire."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="MIXED", confidence=0.5),
        mmd_mode="gate",
        mmd_abstain_by_side=(("MIXED", "UP"),),
    )
    # DOWN-side fire in MIXED → side gate does NOT match → fire
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=79_984.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=MIXED" in decision.rationale
    # `Decision.side` is BUY/SELL (order side); bet direction is in the rationale.
    assert "side=DOWN" in decision.rationale


async def test_strategy_side_gate_allows_unmatched_label() -> None:
    """MMD_ABSTAIN_BY_SIDE=(MIXED,UP): UP-side fires in DOWN regime still fire."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="DOWN", confidence=0.7),
        mmd_mode="gate",
        mmd_abstain_by_side=(("MIXED", "UP"),),
    )
    # UP-side fire in DOWN-label → side gate does not match
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None
    assert "mmd=DOWN" in decision.rationale


async def test_strategy_side_gate_unknown_label_passes_through() -> None:
    """UNKNOWN always passes through, even if side gate would otherwise match."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="UNKNOWN", confidence=0.0),
        mmd_mode="gate",
        mmd_abstain_by_side=(("UNKNOWN", "UP"),),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None  # UNKNOWN is pass-through; never abstains
    assert "mmd=UNKNOWN" in decision.rationale


async def test_strategy_side_gate_shadow_mode_never_abstains() -> None:
    """Side gate is ONLY active in gate mode; shadow ignores it."""
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="MIXED", confidence=0.5),
        mmd_mode="shadow",  # not gate
        mmd_abstain_by_side=(("MIXED", "UP"),),
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is not None  # shadow mode never abstains
    assert "mmd=MIXED" in decision.rationale


async def test_strategy_side_gate_init_rejects_bad_format() -> None:
    """Init must reject side-gate entries that aren't (label, 'UP'|'DOWN') tuples."""
    with pytest.raises(ValueError, match=r"mmd_abstain_by_side"):
        SpotAwareStrategyV2_1(
            priors=_StubPriors(p_win=0.55),
            bankroll_getter=_bankroll(),
            mmd_abstain_by_side=(("MIXED", "WRONG_SIDE"),),
        )


async def test_strategy_side_gate_combined_with_label_abstain() -> None:
    """Both gates run: label abstain takes effect first; side gate is secondary."""
    # In MIXED-UP: side gate abstains. In CHOPPY-anything: label abstain.
    strat = SpotAwareStrategyV2_1(
        priors=_StubPriors(p_win=0.55),
        bankroll_getter=_bankroll(),
        mmd_getter=lambda: _FakeReading(label="CHOPPY", confidence=0.7),
        mmd_mode="gate",
        mmd_labels_to_abstain=("CHOPPY",),  # label abstain
        mmd_abstain_by_side=(("MIXED", "UP"),),  # side abstain
    )
    decision = await _drive_simple_window(strat, open_spot=80_000.0, end_spot=80_016.0, ask_up=0.40)
    assert decision is None  # CHOPPY label triggers label-abstain


async def test_mmd_reading_dataclass_is_frozen() -> None:
    r = MmdReading(
        label="MIXED",
        confidence=0.5,
        adx=22.0,
        bb_width_bps=45.0,
        momentum_bps=3.0,
        sampled_at_ns=1,
        bar_count=60,
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        r.label = "UP"  # type: ignore[misc]

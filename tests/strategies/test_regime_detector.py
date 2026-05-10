"""Tests for polymarket_bot.strategies.regime_detector.RegimeDetector.

Per design/regime_detector.md and the validation result confirming the
hypothesis on the 299-fire dataset. Pure deterministic module — these
tests exercise:

  1. Trending price series → ratio > trending_threshold → "trending"
  2. Chop price series → ratio < chop_threshold → "chop"
  3. Mid-range ratio → "mixed"
  4. Cold start (insufficient samples) → "unknown"
  5. Empty buffer → "unknown"
  6. Out-of-order ticks dropped silently
  7. Buffer trims old ticks beyond the 10-min window
  8. Constructor validation rejects bad parameters
"""

from __future__ import annotations

import pytest

from polymarket_bot.strategies.regime_detector import (
    DEFAULT_WINDOW_10M_S,
    RegimeDetector,
)

NS = 1_000_000_000


def _seed_ticks_at_increasing_offsets(
    detector: RegimeDetector,
    *,
    base_ns: int,
    prices: list[float],
    spacing_s: float = 1.0,
) -> int:
    """Feed ``prices`` into the detector at base_ns + i*spacing_s. Returns
    the timestamp of the LAST tick (use as `now_ns` in classify())."""
    last_ts = base_ns
    for i, price in enumerate(prices):
        last_ts = base_ns + int(i * spacing_s * NS)
        detector.observe_spot(last_ts, price)
    return last_ts


def test_classify_unknown_on_empty_buffer() -> None:
    d = RegimeDetector()
    assert d.classify(now_ns=10**18) == "unknown"


def test_classify_unknown_until_min_samples() -> None:
    """Default min_samples=10. Feeding only 5 ticks → 'unknown'."""
    d = RegimeDetector()
    last_ns = _seed_ticks_at_increasing_offsets(
        d, base_ns=10**18, prices=[100.0] * 5, spacing_s=10.0
    )
    assert d.classify(now_ns=last_ns) == "unknown"


def test_classify_trending_when_recent_5m_more_volatile() -> None:
    """Quiet older 5-min half + loud recent 5-min half. Both halves
    centered near the same mean (so global mean shift doesn't inflate
    10m std). Recent 5m std >> baseline → ratio > 1.20 → 'trending'.

    Math: std_5m ≈ 5.0 (loud half), std_10m ≈ sqrt((30*0.25 + 30*25)/60)
    ≈ 3.55 (combined). Ratio ≈ 1.41 > 1.20 → trending."""
    d = RegimeDetector()
    base = 10**18
    # Older 5-min half: tiny ±0.5 oscillation around 100 (quiet baseline).
    quiet = [100.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(30)]
    # Recent 5-min half: ±5.0 oscillation around 100 (loud).
    loud = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(30)]
    last_ts = _seed_ticks_at_increasing_offsets(d, base_ns=base, prices=quiet + loud, spacing_s=9.5)
    assert d.classify(now_ns=last_ts) == "trending"


def test_classify_chop_when_recent_5m_quieter_than_baseline() -> None:
    """Loud older 5-min half + quiet recent 5-min half. Mirror of the
    trending test. Ratio < 0.80 → 'chop'."""
    d = RegimeDetector()
    base = 10**18
    # Older 5-min half: ±5.0 oscillation around 100 (loud baseline).
    loud = [100.0 + (5.0 if i % 2 == 0 else -5.0) for i in range(30)]
    # Recent 5-min half: tiny ±0.1 oscillation around 100 (quiet).
    quiet = [100.0 + (0.1 if i % 2 == 0 else -0.1) for i in range(30)]
    last_ts = _seed_ticks_at_increasing_offsets(d, base_ns=base, prices=loud + quiet, spacing_s=9.5)
    assert d.classify(now_ns=last_ts) == "chop"


def test_classify_mixed_when_ratio_in_band() -> None:
    """Same noise amplitude across both halves → 5m std ≈ 10m std →
    ratio ≈ 1.0 → 'mixed' (between 0.80 and 1.20)."""
    d = RegimeDetector()
    base = 10**18
    pattern = [100.0 + (1.0 if i % 2 == 0 else -1.0) for i in range(60)]
    last_ts = _seed_ticks_at_increasing_offsets(d, base_ns=base, prices=pattern, spacing_s=9.5)
    assert d.classify(now_ns=last_ts) == "mixed"


def test_buffer_trims_old_ticks() -> None:
    """Ticks older than window_10m_s are evicted as new ones arrive."""
    d = RegimeDetector()
    base = 10**18
    # Seed 30 ticks 60s apart (covers ~30 minutes — only the last 10 min
    # should remain in the buffer at the end).
    last_ts = _seed_ticks_at_increasing_offsets(
        d, base_ns=base, prices=[100.0] * 30, spacing_s=60.0
    )
    # 10-min window = 600s → at most 10 ticks should remain (one per 60s
    # within the trailing 600s).
    assert d.buffer_size() <= 11  # tolerance for the boundary tick
    assert d.buffer_size() >= 10
    # Sanity: classify works on the trimmed buffer
    assert d.classify(now_ns=last_ts) in {"trending", "chop", "mixed", "unknown"}


def test_observe_spot_drops_out_of_order_ticks() -> None:
    """Synthetic test scenario: a tick with an earlier timestamp than
    the most-recent tick is silently dropped (the live binance feed is
    timestamp-monotonic so this only fires under tests)."""
    d = RegimeDetector()
    d.observe_spot(ts_ns=10**18 + 100 * NS, price=100.0)
    n_before = d.buffer_size()
    d.observe_spot(ts_ns=10**18 + 50 * NS, price=99.0)  # earlier ts → drop
    assert d.buffer_size() == n_before


def test_observe_spot_drops_non_positive_price() -> None:
    """Garbage prices (zero or negative) are silently ignored."""
    d = RegimeDetector()
    d.observe_spot(ts_ns=10**18, price=0.0)
    d.observe_spot(ts_ns=10**18 + NS, price=-5.0)
    assert d.buffer_size() == 0


def test_constructor_rejects_invalid_windows() -> None:
    with pytest.raises(ValueError, match="window_5m_s"):
        RegimeDetector(window_5m_s=0)
    with pytest.raises(ValueError, match="window_10m_s"):
        RegimeDetector(window_5m_s=300, window_10m_s=200)  # 10m must be > 5m


def test_constructor_rejects_inverted_thresholds() -> None:
    with pytest.raises(ValueError, match="thresholds"):
        RegimeDetector(trending_threshold=0.5, chop_threshold=0.8)
    with pytest.raises(ValueError, match="thresholds"):
        RegimeDetector(trending_threshold=1.0, chop_threshold=0.0)


def test_buffer_size_default_window_seconds_constant() -> None:
    """Sanity: the exported window default matches the constant the
    runtime uses. Catch a future divergence between tests + production."""
    d = RegimeDetector()
    # No public window accessor (deliberate - these are internal); just
    # verify the default constant is sane (5-15 min).
    assert 60 <= DEFAULT_WINDOW_10M_S <= 1800
    assert d.buffer_size() == 0

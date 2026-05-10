"""RegimeDetector — classifies BTC spot regime via 5m/10m realised-vol ratio.

Per design/regime_detector.md §"The classifier" + the validation
finding at runbooks/gate-evidence/regime-classifier-validation.txt
(2026-05-10): on the 299-fire dataset, trending bucket WR = 70.59%
vs chop = 47.40% (+23.19pp); per-trade pnl +$1.75 vs -$0.22.

Pure deterministic. No I/O, no async. Memory-cheap rolling buffer
(~600 ticks at 1Hz = ~5KB). Writes the decision, doesn't make it —
SpotAwareStrategyV3 owns the gate logic on top.

Implementation notes:
  - The design doc spec writes the metric as
    realized_vol_x = std(prices) / mean(prices), then ratio = vol_5m/vol_10m.
    On short-horizon BTC ticks the means are effectively equal so the
    ratio collapses to std_5m / std_10m. The validation script used the
    collapsed form and confirmed the hypothesis; the production detector
    matches the validated form for consistency.
  - Out-of-order ticks are silently dropped (the live binance feed is
    timestamp-monotonic, so this is a defensive guard, not a hot path).
  - Cold-start: classify() returns "unknown" until both windows have
    >= min_samples ticks. v3 strategy abstains while unknown.
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import Literal

DEFAULT_WINDOW_5M_S: int = 300
DEFAULT_WINDOW_10M_S: int = 600
DEFAULT_TRENDING_THRESHOLD: float = 1.20
DEFAULT_CHOP_THRESHOLD: float = 0.80
# Minimum samples required in each window before classify() returns
# anything other than "unknown". 10 is a soft floor — pstdev on fewer
# than ~5 samples is unreliable; 10 gives some breathing room.
DEFAULT_MIN_SAMPLES: int = 10

Regime = Literal["trending", "chop", "mixed", "unknown"]


class RegimeDetector:
    """Classifies the current spot regime as trending / chop / mixed
    based on the 5m/10m realised volatility ratio.

    Usage:
        detector = RegimeDetector()
        # On every SpotTick:
        detector.observe_spot(tick.ts_utc_ns, tick.price)
        # When v3 strategy is about to fire:
        regime = detector.classify(now_ns)
        if regime != "trending":
            return None  # abstain
    """

    def __init__(
        self,
        *,
        window_5m_s: int = DEFAULT_WINDOW_5M_S,
        window_10m_s: int = DEFAULT_WINDOW_10M_S,
        trending_threshold: float = DEFAULT_TRENDING_THRESHOLD,
        chop_threshold: float = DEFAULT_CHOP_THRESHOLD,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> None:
        if window_5m_s <= 0:
            raise ValueError(f"window_5m_s must be > 0; got {window_5m_s}")
        if window_10m_s <= window_5m_s:
            raise ValueError(f"window_10m_s ({window_10m_s}) must be > window_5m_s ({window_5m_s})")
        if not 0.0 < chop_threshold < trending_threshold:
            raise ValueError(
                "thresholds must satisfy 0 < chop_threshold < trending_threshold; "
                f"got chop={chop_threshold} trending={trending_threshold}"
            )
        if min_samples < 2:
            raise ValueError(f"min_samples must be >= 2; got {min_samples}")
        self._window_5m_ns: int = window_5m_s * 1_000_000_000
        self._window_10m_ns: int = window_10m_s * 1_000_000_000
        self._trending_threshold = trending_threshold
        self._chop_threshold = chop_threshold
        self._min_samples = min_samples
        self._ticks: deque[tuple[int, float]] = deque()

    def observe_spot(self, ts_ns: int, price: float) -> None:
        """Append a tick. Out-of-order or non-positive-price ticks are
        dropped. Trims any tick older than the 10-min window so memory
        stays bounded."""
        if price <= 0:
            return
        if self._ticks and ts_ns < self._ticks[-1][0]:
            return  # out-of-order; binance feed is monotonic so this
            # only fires under test scenarios with synthetic clocks
        self._ticks.append((ts_ns, price))
        cutoff = ts_ns - self._window_10m_ns
        while self._ticks and self._ticks[0][0] < cutoff:
            self._ticks.popleft()

    def classify(self, now_ns: int) -> Regime:
        """Return the regime label at now_ns. 'unknown' if either window
        has fewer than min_samples ticks (cold-start). Pure read."""
        if not self._ticks:
            return "unknown"
        cutoff_5m = now_ns - self._window_5m_ns
        cutoff_10m = now_ns - self._window_10m_ns
        prices_5m: list[float] = []
        prices_10m: list[float] = []
        for ts, price in self._ticks:
            if ts < cutoff_10m:
                continue
            prices_10m.append(price)
            if ts >= cutoff_5m:
                prices_5m.append(price)
        if len(prices_5m) < self._min_samples or len(prices_10m) < self._min_samples:
            return "unknown"
        std_5m = statistics.pstdev(prices_5m)
        std_10m = statistics.pstdev(prices_10m)
        if std_10m == 0:
            return "unknown"
        ratio = std_5m / std_10m
        if ratio > self._trending_threshold:
            return "trending"
        if ratio < self._chop_threshold:
            return "chop"
        return "mixed"

    def buffer_size(self) -> int:
        """Read-only accessor used by tests + the v3 wrapper for
        observability. Counts ticks currently retained in the rolling
        buffer (i.e., within the last `window_10m_s` seconds)."""
        return len(self._ticks)

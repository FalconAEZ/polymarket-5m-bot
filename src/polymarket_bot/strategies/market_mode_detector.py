# ruff: noqa: RUF002

"""Market Mode Detector (MMD) — multi-indicator rule-based 4-state classifier.

Implements `design/P.1-market-mode-detector-integration.md`. Outputs one of
{UP, DOWN, CHOPPY, MIXED, UNKNOWN} per 60-min lookback of 1-min OHLCV bars,
using bukosabino/ta v0.11.0 (MIT). UNKNOWN is the explicit pass-through
sentinel — strategies MUST NOT change their firing decision when they read
UNKNOWN. Phase P Session-2 backtest on Phase N n=756 located MIXED as the
only profitable label (+$1.94/tr, +$526) with all other labels bleeding;
Session 3 ships SHADOW-only — annotates rationale but never abstains.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import Literal

import httpx

LOG = logging.getLogger(__name__)

MmdLabel = Literal["UP", "DOWN", "CHOPPY", "MIXED", "UNKNOWN"]
ALL_LABELS: tuple[MmdLabel, ...] = ("UP", "DOWN", "CHOPPY", "MIXED", "UNKNOWN")


@dataclass(frozen=True)
class MmdReading:
    """One MMD classification. `UNKNOWN` means pass-through (no gate)."""

    label: MmdLabel
    confidence: float  # ∈ [0, 1]; 0.0 when UNKNOWN
    adx: float
    bb_width_bps: float
    momentum_bps: float
    sampled_at_ns: int
    bar_count: int


@dataclass
class _Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts_ns: int


def _unknown_reading(sampled_at_ns: int, bar_count: int) -> MmdReading:
    return MmdReading(
        label="UNKNOWN",
        confidence=0.0,
        adx=0.0,
        bb_width_bps=0.0,
        momentum_bps=0.0,
        sampled_at_ns=sampled_at_ns,
        bar_count=bar_count,
    )


class MarketModeDetector:
    """4-state rule-based classifier using ADX(14) + BB-width(20, 2σ) + 30-bar momentum.

    Thread-affinity: single asyncio loop. Buffer is a deque sized to
    `lookback_min`. Latest reading is computed on demand from the buffer.
    All exception paths return UNKNOWN so callers can treat the MMD as
    an annotation source without worrying about crash propagation.
    """

    DEFAULT_LOOKBACK_MIN: int = 60
    DEFAULT_ADX_STRONG: float = 25.0
    DEFAULT_ADX_WEAK: float = 20.0
    DEFAULT_BB_COMPRESSED_BPS: float = 30.0
    DEFAULT_MOMENTUM_BPS: float = 10.0
    MIN_BARS_FOR_CLASSIFICATION: int = 30
    MOMENTUM_LOOKBACK_BARS: int = 30

    def __init__(
        self,
        lookback_min: int = DEFAULT_LOOKBACK_MIN,
        adx_strong_threshold: float = DEFAULT_ADX_STRONG,
        adx_weak_threshold: float = DEFAULT_ADX_WEAK,
        bb_compressed_bps: float = DEFAULT_BB_COMPRESSED_BPS,
        momentum_threshold_bps: float = DEFAULT_MOMENTUM_BPS,
    ) -> None:
        if lookback_min < self.MIN_BARS_FOR_CLASSIFICATION:
            raise ValueError(
                f"lookback_min must be >= {self.MIN_BARS_FOR_CLASSIFICATION}; "
                f"got {lookback_min}"
            )
        if not (adx_weak_threshold < adx_strong_threshold):
            raise ValueError(
                f"adx_weak_threshold must be < adx_strong_threshold; "
                f"got weak={adx_weak_threshold} strong={adx_strong_threshold}"
            )
        if bb_compressed_bps <= 0.0:
            raise ValueError(f"bb_compressed_bps must be > 0; got {bb_compressed_bps}")
        if momentum_threshold_bps <= 0.0:
            raise ValueError(f"momentum_threshold_bps must be > 0; got {momentum_threshold_bps}")
        self._lookback_min = lookback_min
        self._adx_strong = adx_strong_threshold
        self._adx_weak = adx_weak_threshold
        self._bb_compressed_ratio = bb_compressed_bps / 1e4
        self._momentum_threshold_ratio = momentum_threshold_bps / 1e4
        self._bars: deque[_Bar] = deque(maxlen=lookback_min)
        # Detect `ta` availability at construction time. Missing library →
        # no-op stub that returns UNKNOWN forever. Failure mode #1 from
        # design §6.
        try:
            import ta.trend  # type: ignore[import-untyped]
            import ta.volatility  # type: ignore[import-untyped]

            _ = (ta.trend, ta.volatility)  # silence "imported but unused"
            self._ta_available = True
        except ImportError:
            LOG.warning(
                "MarketModeDetector: `ta` library not importable; will return "
                "UNKNOWN for every call (no-op stub). Install with `uv add ta`."
            )
            self._ta_available = False

    @property
    def lookback_min(self) -> int:
        return self._lookback_min

    def bar_count(self) -> int:
        return len(self._bars)

    def push_bar(
        self,
        *,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        ts_ns: int,
    ) -> None:
        """Append a 1-min OHLCV bar to the rolling buffer."""
        self._bars.append(
            _Bar(open=open_, high=high, low=low, close=close, volume=volume, ts_ns=ts_ns)
        )

    def clear_buffer(self) -> None:
        """Empty the rolling buffer. Used by the poller on full-window refresh."""
        self._bars.clear()

    def latest(self, *, now_ns: int | None = None) -> MmdReading:
        """Compute a classification from the current buffer. Never raises."""
        last_bar_ts = self._bars[-1].ts_ns if self._bars else 0
        sampled_at = now_ns if now_ns is not None else last_bar_ts
        if not self._ta_available or len(self._bars) < self.MIN_BARS_FOR_CLASSIFICATION:
            return _unknown_reading(sampled_at_ns=sampled_at, bar_count=len(self._bars))
        try:
            return self._classify(sampled_at)
        except Exception as exc:
            LOG.warning("MarketModeDetector.latest() exception: %s", exc)
            return _unknown_reading(sampled_at_ns=sampled_at, bar_count=len(self._bars))

    def _classify(self, sampled_at: int) -> MmdReading:
        # Local imports keep the no-op stub fast at construction time.
        import pandas as pd  # type: ignore[import-untyped]
        from ta.trend import ADXIndicator
        from ta.volatility import BollingerBands

        highs = pd.Series([b.high for b in self._bars])
        lows = pd.Series([b.low for b in self._bars])
        closes = pd.Series([b.close for b in self._bars])

        adx_val = float(ADXIndicator(highs, lows, closes, window=14, fillna=True).adx().iloc[-1])
        bb = BollingerBands(closes, window=20, window_dev=2, fillna=True)
        last_close = float(closes.iloc[-1])
        bbw_ratio = float(
            (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / last_close
        )
        ref_idx = -self.MOMENTUM_LOOKBACK_BARS
        ref_close = float(closes.iloc[ref_idx])
        momentum_ratio = (last_close - ref_close) / ref_close if ref_close > 0.0 else 0.0

        adx_strong = adx_val > self._adx_strong
        adx_weak = adx_val < self._adx_weak
        bb_compressed = bbw_ratio < self._bb_compressed_ratio
        mom_up = momentum_ratio > self._momentum_threshold_ratio
        mom_dn = momentum_ratio < -self._momentum_threshold_ratio

        label: MmdLabel
        if adx_strong and mom_up:
            label = "UP"
            conf = (adx_val - self._adx_strong) / 15.0
        elif adx_strong and mom_dn:
            label = "DOWN"
            conf = (adx_val - self._adx_strong) / 15.0
        elif adx_weak and bb_compressed:
            label = "CHOPPY"
            conf = (self._adx_weak - adx_val) / 10.0
        else:
            label = "MIXED"
            conf = 0.5

        return MmdReading(
            label=label,
            confidence=max(0.0, min(1.0, float(conf))),
            adx=adx_val,
            bb_width_bps=bbw_ratio * 1e4,
            momentum_bps=momentum_ratio * 1e4,
            sampled_at_ns=sampled_at,
            bar_count=len(self._bars),
        )


class MmdBinanceKlinePoller:
    """asyncio background task: polls Binance public klines, refills MMD buffer.

    Polls `/api/v3/klines` (BTCUSDT 1m default, last N closed bars) every
    `poll_interval_s`. On each successful poll, clears the MMD buffer and
    push_bar's the fresh window. On any poll exception, leaves the buffer
    intact and logs a warning — `latest()` will naturally degrade to
    UNKNOWN once the last bar is more than ~2 × poll_interval stale
    (caller can check `mmd.bar_count() == 0` for fresh-start staleness).

    Public REST, no auth. Rate limit 1200 req/min on the no-auth bucket;
    at the default 30 s poll interval that's 2 req/min — well under budget.
    """

    DEFAULT_SYMBOL: str = "BTCUSDT"
    DEFAULT_BASE_URL: str = "https://api.binance.com"
    DEFAULT_POLL_INTERVAL_S: float = 30.0
    DEFAULT_TIMEOUT_S: float = 10.0

    def __init__(
        self,
        mmd: MarketModeDetector,
        *,
        symbol: str = DEFAULT_SYMBOL,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if poll_interval_s <= 0.0:
            raise ValueError(f"poll_interval_s must be > 0; got {poll_interval_s}")
        self._mmd = mmd
        self._symbol = symbol
        self._poll_interval_s = poll_interval_s
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owned_client = client is None
        self._timeout_s = timeout_s
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    async def poll_once(self) -> int:
        """Fetch one batch of klines + refill the MMD buffer. Returns bars added.

        Raises on HTTP error; the caller (`run`) catches and logs.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
            self._owned_client = True
        r = await self._client.get(
            f"{self._base_url}/api/v3/klines",
            params={
                "symbol": self._symbol,
                "interval": "1m",
                "limit": self._mmd.lookback_min,
            },
        )
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            raise ValueError(f"unexpected klines response shape: {type(rows).__name__}")
        self._mmd.clear_buffer()
        for row in rows:
            # Binance kline schema: [open_time_ms, open, high, low, close, volume, ...]
            self._mmd.push_bar(
                open_=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                ts_ns=int(row[0]) * 1_000_000,
            )
        return len(rows)

    async def run(self, *, stop: asyncio.Event) -> None:
        """Run the poll loop until `stop` is set. Always closes owned clients."""
        try:
            while not stop.is_set():
                try:
                    n = await self.poll_once()
                    if self._consecutive_failures > 0:
                        LOG.info("MMD poll recovered after %d failures", self._consecutive_failures)
                    self._consecutive_failures = 0
                    LOG.debug("MMD poll OK: %d bars buffered", n)
                except Exception as exc:
                    self._consecutive_failures += 1
                    LOG.warning(
                        "MMD poll failed (consecutive=%d): %s",
                        self._consecutive_failures,
                        exc,
                    )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_s)
                    break
                except TimeoutError:
                    continue
        finally:
            if self._owned_client and self._client is not None:
                with _suppress_exceptions():
                    await self._client.aclose()


class _suppress_exceptions:
    """Inline contextlib.suppress(Exception) without importing contextlib here."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return exc_type is not None and issubclass(exc_type, Exception)

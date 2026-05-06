"""Deterministic baseline — window-delta + oracle-gap composite signal.

The Tier-3 fallback path per locked decision #6, also tested as a standalone
strategy in Phase 3 A/B per locked decision #16. No LLM calls; pure math
from spot, oracle, and per-window state. Threshold + weights are calibrated
empirically in Phase 3.3; defaults here match MASTERPLAN line 146 with the
fractional-vs-percentage-points clarification from design/backtest.md §10.

Heartbeat-aware note (decision #21): the lag window is ~16.5s median, half
the masterplan's assumption. ttl_high_s = 30 may be tightened in Phase 3.3
once the empirical sweep speaks; the strategy code does not bake this in.
"""

from __future__ import annotations

from typing import Literal

from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    MarketEvent,
    OracleUpdate,
    Side,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.resolver import WINDOW_SECONDS

DEFAULT_W_WINDOW_DELTA = 0.5
DEFAULT_W_ORACLE_GAP = 0.5
DEFAULT_THRESHOLD_PCT = 0.6
DEFAULT_TTL_LOW_S = 10
DEFAULT_TTL_HIGH_S = 30
DEFAULT_SIZE_USD = 5.0


def composite_pct(
    spot_now: float,
    window_open_spot: float,
    oracle_last: float,
    *,
    w_wd: float = DEFAULT_W_WINDOW_DELTA,
    w_og: float = DEFAULT_W_ORACLE_GAP,
) -> float:
    """Returns a percentage-point composite signal. Positive ⇒ UP, negative ⇒ DOWN.

    The masterplan's threshold of 0.6 is in percentage points; the formula
    in MASTERPLAN line 146 is fractional. We multiply by 100 here so the
    threshold reads as a normal percentage and so weight tuning in Phase 3.3
    reads in the same units as a human's mental model of BTC moves.
    """
    if window_open_spot == 0.0 or oracle_last == 0.0:
        return 0.0
    window_delta_frac = (spot_now - window_open_spot) / window_open_spot
    oracle_gap_frac = (spot_now - oracle_last) / oracle_last
    return (w_wd * window_delta_frac + w_og * oracle_gap_frac) * 100.0


class DeterministicStrategy:
    """Baseline: fire BUY on the side whose composite >= threshold within a TTL window."""

    name: str = "deterministic"

    def __init__(
        self,
        *,
        w_window_delta: float = DEFAULT_W_WINDOW_DELTA,
        w_oracle_gap: float = DEFAULT_W_ORACLE_GAP,
        threshold_pct: float = DEFAULT_THRESHOLD_PCT,
        ttl_low_s: int = DEFAULT_TTL_LOW_S,
        ttl_high_s: int = DEFAULT_TTL_HIGH_S,
        size_usd: float = DEFAULT_SIZE_USD,
    ) -> None:
        if not 0.0 < threshold_pct:
            raise ValueError(f"threshold_pct must be > 0, got {threshold_pct}")
        if ttl_low_s < 0 or ttl_high_s < ttl_low_s:
            raise ValueError(f"ttl_low_s ({ttl_low_s}) must be in [0, ttl_high_s ({ttl_high_s})]")
        self._w_wd = w_window_delta
        self._w_og = w_oracle_gap
        self._threshold_pct = threshold_pct
        self._ttl_low_s = ttl_low_s
        self._ttl_high_s = ttl_high_s
        self._size_usd = size_usd

        self._spot_now: float | None = None
        self._oracle_last: float | None = None
        self._window_ts: int | None = None
        self._window_open_spot: float | None = None
        self._fired_for_window: int | None = None
        self._token_for_side: dict[Side, str] = {}
        self._best_ask_for_side: dict[Side, float] = {}

    def reset(self) -> None:
        self._spot_now = None
        self._oracle_last = None
        self._window_ts = None
        self._window_open_spot = None
        self._fired_for_window = None
        self._token_for_side = {}
        self._best_ask_for_side = {}

    async def on_event(self, event: MarketEvent) -> Decision | None:
        if isinstance(event, SpotTick):
            self._spot_now = event.price
            if self._window_open_spot is None and self._window_ts is not None:
                self._window_open_spot = event.price
            return self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, OracleUpdate):
            self._oracle_last = event.price
            return self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, BookUpdate):
            self._token_for_side[event.side] = event.asset_id
            if event.best_ask is not None:
                self._best_ask_for_side[event.side] = event.best_ask
            return self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, WindowBoundary):
            return self._on_boundary(event)
        return None

    def _on_boundary(self, event: WindowBoundary) -> Decision | None:
        if event.kind == "open":
            self._window_ts = event.window_ts
            # Latch window_open_spot lazily on the first spot tick after open,
            # not at the boundary itself — at boundary time we may not have
            # seen a spot tick yet (especially at replay start).
            self._window_open_spot = None
            self._fired_for_window = None
        return None

    def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:
        if self._window_ts is None:
            return None
        if self._fired_for_window == self._window_ts:
            return None
        if self._spot_now is None or self._oracle_last is None or self._window_open_spot is None:
            return None

        ttl_s = self._compute_ttl_s(now_ts_utc_ns)
        if not (self._ttl_low_s <= ttl_s <= self._ttl_high_s):
            return None

        signal = composite_pct(
            self._spot_now,
            self._window_open_spot,
            self._oracle_last,
            w_wd=self._w_wd,
            w_og=self._w_og,
        )
        if abs(signal) < self._threshold_pct:
            return None

        side: Side = "UP" if signal > 0 else "DOWN"
        asset_id = self._token_for_side.get(side)
        if asset_id is None:
            return None
        ask = self._best_ask_for_side.get(side)
        price_limit = ask if ask is not None else 0.50

        self._fired_for_window = self._window_ts
        return Decision(
            ts_utc_ns=now_ts_utc_ns,
            asset_id=asset_id,
            side="BUY",
            size_usd=self._size_usd,
            price_limit=price_limit,
            ttl_s=ttl_s,
            rationale=_rationale(signal, self._threshold_pct, ttl_s, side),
        )

    def _compute_ttl_s(self, now_ts_utc_ns: int) -> int:
        if self._window_ts is None:
            return -1  # caller guards via window_ts None-check; defensive only
        now_s = now_ts_utc_ns // 1_000_000_000
        close_s = self._window_ts + WINDOW_SECONDS
        return max(0, close_s - now_s)


def _rationale(
    signal_pct: float, threshold_pct: float, ttl_s: int, side: Literal["UP", "DOWN"]
) -> str:
    return f"composite={signal_pct:+.3f}pct (|.|>={threshold_pct:.2f}) ttl={ttl_s}s side={side}"

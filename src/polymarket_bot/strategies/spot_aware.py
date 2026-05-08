"""SpotAwareStrategy — Δ_bps + alignment + tier filter + EV gate.

Sibling strategy to DeterministicStrategy, locked in
design/spot_aware_strategy.md (committed at 02fac24). Driven by the
30-day Bonereaper analysis (+30.9pp aligned-vs-contrarian gap on 306,966
trades) plus the leaderboard scout's negative finding (high WR without
price-tier discipline = money-burning).

Trigger: |Δ_bps| ≥ Δ_min AND ≤ Δ_max AND aligned-with-spot AND price tier
in the lookup table AND p_win * $1 - (entry_price + fees) > ev_min.

NOT a clone of Bonereaper. NOT a replacement for DeterministicStrategy.
NOT live-trading code. Anti-vibe rule #1: this implementation matches
the locked spec; rule #2's failing tests live in tests/strategies/
test_spot_aware.py.
"""

from __future__ import annotations

import logging
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
from polymarket_bot.strategies.spot_aware_priors import SpotAwarePriors

LOG = logging.getLogger("polymarket_bot.strategies.spot_aware")

DEFAULT_DELTA_MIN_BPS = 8.0
DEFAULT_DELTA_MAX_BPS = 50.0
DEFAULT_SIZE_USD = 5.0  # locked decision #9
DEFAULT_FEE_PCT = 0.005
DEFAULT_EV_MIN_DOLLARS = 0.005
DEFAULT_TTL_LOW_S = 10
DEFAULT_TTL_HIGH_S = 30


def delta_bps(*, spot_now: float, window_open_spot: float) -> float:
    """Δ_bps = 10000 * (St - S0) / S0. Returns 0 on zero-open-spot guard."""
    if window_open_spot == 0.0:
        return 0.0
    return 10_000.0 * (spot_now - window_open_spot) / window_open_spot


class SpotAwareStrategy:
    """Fire BUY on the side aligned with current Δ_bps when EV gate clears."""

    name: str = "spot_aware"

    def __init__(
        self,
        *,
        priors: SpotAwarePriors,
        delta_min_bps: float = DEFAULT_DELTA_MIN_BPS,
        delta_max_bps: float = DEFAULT_DELTA_MAX_BPS,
        size_usd: float = DEFAULT_SIZE_USD,
        fee_estimate_pct: float | None = None,
        ev_min_dollars_per_share: float | None = None,
        ttl_low_s: int = DEFAULT_TTL_LOW_S,
        ttl_high_s: int = DEFAULT_TTL_HIGH_S,
    ) -> None:
        if delta_min_bps <= 0:
            raise ValueError(f"delta_min_bps must be > 0, got {delta_min_bps}")
        if delta_max_bps <= delta_min_bps:
            raise ValueError(
                f"delta_max_bps ({delta_max_bps}) must be > delta_min_bps ({delta_min_bps})"
            )
        if ttl_low_s < 0 or ttl_high_s < ttl_low_s:
            raise ValueError(f"ttl_low_s ({ttl_low_s}) must be in [0, ttl_high_s ({ttl_high_s})]")
        self._priors = priors
        self._delta_min = delta_min_bps
        self._delta_max = delta_max_bps
        self._size_usd = size_usd
        # Allow the strategy to override the priors' fee/EV constants if the
        # operator has live data that differs. Default is to use whatever the
        # priors JSON declared (so the source of truth stays the priors file).
        self._fee_pct = priors.fee_estimate_pct if fee_estimate_pct is None else fee_estimate_pct
        self._ev_min = (
            priors.ev_min_dollars_per_share
            if ev_min_dollars_per_share is None
            else ev_min_dollars_per_share
        )
        self._ttl_low_s = ttl_low_s
        self._ttl_high_s = ttl_high_s

        self._spot_now: float | None = None
        self._window_ts: int | None = None
        self._window_open_spot: float | None = None
        self._fired_for_window: int | None = None
        self._token_for_side: dict[Side, str] = {}
        self._best_ask_for_side: dict[Side, float] = {}

    def reset(self) -> None:
        self._spot_now = None
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
        if isinstance(event, BookUpdate):
            self._token_for_side[event.side] = event.asset_id
            if event.best_ask is not None:
                self._best_ask_for_side[event.side] = event.best_ask
            return self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, OracleUpdate):
            # Strategy is spot-only by design (§7); oracle is ignored. The
            # deterministic baseline handles oracle gap.
            return None
        if isinstance(event, WindowBoundary):
            return self._on_boundary(event)
        return None

    def _on_boundary(self, event: WindowBoundary) -> Decision | None:
        if event.kind == "open":
            self._window_ts = event.window_ts
            self._window_open_spot = None
            self._fired_for_window = None
        return None

    def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:
        if self._window_ts is None:
            return None
        if self._fired_for_window == self._window_ts:
            return None
        if self._spot_now is None or self._window_open_spot is None:
            return None

        d_bps = delta_bps(spot_now=self._spot_now, window_open_spot=self._window_open_spot)
        abs_d = abs(d_bps)
        if abs_d < self._delta_min or abs_d > self._delta_max:
            return None

        side: Side = "UP" if d_bps > 0 else "DOWN"
        asset_id = self._token_for_side.get(side)
        if asset_id is None:
            return None
        ask = self._best_ask_for_side.get(side)
        if ask is None:
            return None

        p_win = self._priors.lookup(price=ask, abs_delta_bps=abs_d)
        if p_win is None:
            return None

        ev = p_win - (ask + self._fee_pct)
        if ev <= self._ev_min:
            return None

        # spot_aware fires whenever signal+EV align within a window — not
        # only in the last 10-30s like the deterministic strategy. The ttl
        # range is a *clamp*, not a fire gate. We do require enough time
        # left in the window for the order to plausibly fill, hence the
        # ttl_low_s lower bound.
        time_to_close_s = self._compute_time_to_close_s(now_ts_utc_ns)
        if time_to_close_s < self._ttl_low_s:
            return None
        ttl_s = min(self._ttl_high_s, time_to_close_s)

        self._fired_for_window = self._window_ts
        return Decision(
            ts_utc_ns=now_ts_utc_ns,
            asset_id=asset_id,
            side="BUY",
            size_usd=self._size_usd,
            price_limit=ask,
            ttl_s=ttl_s,
            rationale=_rationale(d_bps, p_win, ev, ttl_s, side),
        )

    def _compute_time_to_close_s(self, now_ts_utc_ns: int) -> int:
        if self._window_ts is None:
            return -1
        now_s = now_ts_utc_ns // 1_000_000_000
        close_s = self._window_ts + WINDOW_SECONDS
        return max(0, close_s - now_s)


def _rationale(
    d_bps: float,
    p_win: float,
    ev: float,
    ttl_s: int,
    side: Literal["UP", "DOWN"],
) -> str:
    return (
        f"strategy=spot_aware delta_bps={d_bps:+.2f} p_win={p_win:.3f} "
        f"ev={ev:+.4f} ttl={ttl_s}s side={side}"
    )

"""SpotAwareStrategyV2 -- tier-restricted, no-fallback variant of v1.

Locked spec: design/spot_aware_v2_tier_restricted.md (2026-05-09).
Driven by the Phase 11.A.2 mid-soak edge-discovery audit
(runbooks/research/edge-discovery-2026-05-09.md):

  * Tier 50-70% holds 76% of v1+aggressive fires but loses $76 with
    49% WR -- structural asymmetric-payoff loss.
  * The aggressive-mode p_win=0.54 fallback produces false-positive EV
    signals; the EV [0.02, 0.05) bucket was -$60 / 38% WR.
  * 95% of aggressive fires were in |delta|<2 bps (pure-noise zone).

v2 fixes all three:
  1. Reject tier 50-70% explicitly (in addition to v1's 85-100% reject).
  2. Drop the priors-fallback -- a priors-table miss = no fire.
  3. Re-enforce delta_min/delta_max + EV gate (no aggressive bypass).

Decision interface and rationale format are unchanged from v1 except
the strategy marker is ``strategy=spot_aware_v2``. This makes telemetry
parsers identify v2 fires distinctly while keeping the rest of the
runner pipeline unchanged.
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
from polymarket_bot.strategies.spot_aware import (
    DEFAULT_LIMIT_BUFFER_USD,
    DEFAULT_SIZE_USD,
    DEFAULT_TTL_HIGH_S,
    DEFAULT_TTL_LOW_S,
    delta_bps,
)
from polymarket_bot.strategies.spot_aware_priors import SpotAwarePriors

# v2 defaults differ from v1: delta_min=5 (matches priors-table coverage
# at the loose-start floor) instead of v1's 8. The priors table's
# delta_buckets_bps starts at 5; below that the lookup misses anyway,
# so 5 is the right floor.
DEFAULT_DELTA_MIN_BPS_V2 = 5.0
DEFAULT_DELTA_MAX_BPS_V2 = 50.0
DEFAULT_EV_MIN_DOLLARS_V2 = 0.005

# Tiers v2 explicitly REJECTS (in addition to whatever the priors-table
# already excludes via lookup-miss). 50-70% per the edge-discovery audit;
# 85-100% is already excluded by the priors table itself but we list it
# here for documentation / defense-in-depth.
DEFAULT_REJECTED_TIERS_V2: tuple[tuple[float, float], ...] = (
    (0.50, 0.70),
    (0.85, 1.01),  # belt-and-braces; priors table already excludes this
)


class SpotAwareStrategyV2:
    """Fire BUY on aligned-side when priors hit AND tier not rejected AND EV clears.

    Same MarketEvent interface as v1 (SpotAwareStrategy). Subclass-able;
    standalone implementation chosen over subclassing v1 to avoid coupling
    to v1's internal state lifecycle.
    """

    name: str = "spot_aware_v2"

    def __init__(
        self,
        *,
        priors: SpotAwarePriors,
        rejected_tiers: tuple[tuple[float, float], ...] = DEFAULT_REJECTED_TIERS_V2,
        delta_min_bps: float = DEFAULT_DELTA_MIN_BPS_V2,
        delta_max_bps: float = DEFAULT_DELTA_MAX_BPS_V2,
        size_usd: float = DEFAULT_SIZE_USD,
        fee_estimate_pct: float | None = None,
        ev_min_dollars_per_share: float | None = None,
        ttl_low_s: int = DEFAULT_TTL_LOW_S,
        ttl_high_s: int = DEFAULT_TTL_HIGH_S,
        limit_buffer_usd: float = DEFAULT_LIMIT_BUFFER_USD,
    ) -> None:
        if delta_min_bps <= 0:
            raise ValueError(f"delta_min_bps must be > 0, got {delta_min_bps}")
        if delta_max_bps <= delta_min_bps:
            raise ValueError(
                f"delta_max_bps ({delta_max_bps}) must be > delta_min_bps ({delta_min_bps})"
            )
        if ttl_low_s < 0 or ttl_high_s < ttl_low_s:
            raise ValueError(f"ttl_low_s ({ttl_low_s}) must be in [0, ttl_high_s ({ttl_high_s})]")
        for lo, hi in rejected_tiers:
            if not 0 <= lo < hi <= 1.01:
                raise ValueError(
                    f"rejected_tiers entry [{lo}, {hi}] must be in [0, 1.01] with lo < hi"
                )
        self._priors = priors
        self._rejected_tiers = tuple(rejected_tiers)
        self._delta_min = delta_min_bps
        self._delta_max = delta_max_bps
        self._size_usd = size_usd
        self._fee_pct = priors.fee_estimate_pct if fee_estimate_pct is None else fee_estimate_pct
        self._ev_min = (
            ev_min_dollars_per_share
            if ev_min_dollars_per_share is not None
            else DEFAULT_EV_MIN_DOLLARS_V2
        )
        self._ttl_low_s = ttl_low_s
        self._ttl_high_s = ttl_high_s
        self._limit_buffer = max(0.0, limit_buffer_usd)

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

    def _is_tier_rejected(self, price: float) -> bool:
        """True iff ``price`` falls into any explicit reject band."""
        for lo, hi in self._rejected_tiers:
            if lo <= price < hi:
                return True
        return False

    def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:
        if self._window_ts is None:
            return None
        if self._fired_for_window == self._window_ts:
            return None
        if self._spot_now is None or self._window_open_spot is None:
            return None

        d_bps = delta_bps(spot_now=self._spot_now, window_open_spot=self._window_open_spot)
        abs_d = abs(d_bps)

        # v2: re-enforced delta gate (no aggressive bypass available).
        if abs_d < self._delta_min or abs_d > self._delta_max:
            return None
        if d_bps == 0.0:
            return None

        side: Side = "UP" if d_bps > 0 else "DOWN"
        asset_id = self._token_for_side.get(side)
        if asset_id is None:
            return None
        ask = self._best_ask_for_side.get(side)
        if ask is None:
            return None

        # v2: explicit tier rejection BEFORE the priors lookup. Rejected
        # tiers (e.g. 50-70%) are never fired regardless of priors data --
        # the structural asymmetric payoff at this band loses money even
        # at near-50% WR. Per edge-discovery audit 2026-05-09.
        if self._is_tier_rejected(ask):
            return None

        # v2: priors miss = no fire (NO p_win=0.54 fallback).
        p_win = self._priors.lookup(price=ask, abs_delta_bps=abs_d)
        if p_win is None:
            return None

        price_limit = min(0.99, ask + self._limit_buffer)
        ev = p_win - (price_limit + self._fee_pct)

        # v2: re-enforced EV gate (no aggressive bypass).
        if ev <= self._ev_min:
            return None

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
            price_limit=price_limit,
            ttl_s=ttl_s,
            rationale=_rationale_v2(d_bps, p_win, ev, ttl_s, side),
        )

    def _compute_time_to_close_s(self, now_ts_utc_ns: int) -> int:
        if self._window_ts is None:
            return -1
        now_s = now_ts_utc_ns // 1_000_000_000
        close_s = self._window_ts + WINDOW_SECONDS
        return max(0, close_s - now_s)


def _rationale_v2(
    d_bps: float,
    p_win: float,
    ev: float,
    ttl_s: int,
    side: Literal["UP", "DOWN"],
) -> str:
    return (
        f"strategy=spot_aware_v2 mode=tier_restricted delta_bps={d_bps:+.2f} "
        f"p_win={p_win:.3f} ev={ev:+.4f} ttl={ttl_s}s side={side}"
    )

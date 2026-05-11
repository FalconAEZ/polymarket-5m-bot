"""WideFireStrategy — fires on every 5m window with any directional spot move.

Phase 5 base strategy for "let the LLM ensemble filter everything" mode.
Operator-approved 2026-05-10 directive: maximum fire volume → meta-decider
gates → only the high-conviction subset actually trades. This strategy
intentionally does NO filtering of its own beyond the bare minimum
(spot moved, asset_id known, ask known, time-in-window valid). It's the
opposite extreme from SpotAwareStrategyV2 — every gate v2 added is gone:

  • NO Δ_bps minimum (any non-zero direction qualifies)
  • NO Δ_bps maximum
  • NO tier rejection (50-70%, 85-100%, all tiers admitted)
  • NO priors lookup (no p_win gate, no priors-miss-rejection)
  • NO EV gate (no fee/edge calculation)
  • NO oracle requirement

The rationale tag (see _rationale) carries:
  strategy=wide_fire mode=ensemble_base delta_bps=±X.XX side=UP|DOWN ttl=Ns

EnsembleWrapper composes this strategy with the 3-specialist + Sonnet meta
agents; the LLM ensemble's meta-decider becomes the only real gate.

Use ONLY as a base for EnsembleWrapper. As a standalone strategy this is
guaranteed-loss: 50% baseline WR with fees + simulator impact.
"""

from __future__ import annotations

from polymarket_bot.backtest.fills import DEFAULT_FLOOR_BEST_ASK
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


class WideFireStrategy:
    """Fires on every window with non-zero spot delta. No filters."""

    name: str = "wide_fire"

    def __init__(
        self,
        *,
        size_usd: float = DEFAULT_SIZE_USD,
        ttl_low_s: int = DEFAULT_TTL_LOW_S,
        ttl_high_s: int = DEFAULT_TTL_HIGH_S,
        limit_buffer_usd: float = DEFAULT_LIMIT_BUFFER_USD,
        # delta_min_bps is OPTIONAL minimum. Default 0.0 fires on any
        # non-zero direction. Operator can set to e.g. 1.0 to require
        # at least 1bp move (filters out flat-spot noise without
        # constraining tier).
        delta_min_bps: float = 0.0,
    ) -> None:
        if ttl_low_s < 0 or ttl_high_s < ttl_low_s:
            raise ValueError(f"ttl_low_s ({ttl_low_s}) must be in [0, ttl_high_s ({ttl_high_s})]")
        if delta_min_bps < 0:
            raise ValueError(f"delta_min_bps must be >= 0; got {delta_min_bps}")
        self._size_usd = size_usd
        self._ttl_low_s = ttl_low_s
        self._ttl_high_s = ttl_high_s
        self._limit_buffer = max(0.0, limit_buffer_usd)
        self._delta_min = delta_min_bps

        self._spot_now: float | None = None
        self._window_ts: int | None = None
        self._window_open_spot: float | None = None
        self._fired_for_window: int | None = None
        self._token_for_side: dict[Side, str] = {}
        self._best_ask_for_side: dict[Side, float] = {}
        # ask_size_top per side — None means "no depth signal", which is
        # the trigger for FillSimulator._refuse_for_no_depth (Phase 11.A
        # phantom-fill defense). Mirrored here so we abstain BEFORE
        # emitting a fired record the simulator would later refuse.
        self._ask_size_for_side: dict[Side, float | None] = {}

    def reset(self) -> None:
        self._spot_now = None
        self._window_ts = None
        self._window_open_spot = None
        self._fired_for_window = None
        self._token_for_side = {}
        self._best_ask_for_side = {}
        self._ask_size_for_side = {}

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
            # Track depth signal (may be None on certain Polymarket book
            # updates — best_bid_ask / price_change events). The latest
            # observation wins per side.
            self._ask_size_for_side[event.side] = event.ask_size_top
            return self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, OracleUpdate):
            return None
        if isinstance(event, WindowBoundary) and event.kind == "open":
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
        if d_bps == 0.0:
            return None  # alignment undefined
        if abs_d < self._delta_min:
            return None  # 0.0 default = no constraint

        side: Side = "UP" if d_bps > 0 else "DOWN"
        asset_id = self._token_for_side.get(side)
        if asset_id is None:
            return None
        ask = self._best_ask_for_side.get(side)
        if ask is None:
            return None

        # Phantom-fill defense alignment (audit 2026-05-11).
        # FillSimulator refuses fills when ask_size_top is None AND
        # fill_price <= DEFAULT_FLOOR_BEST_ASK ($0.05). Mirror that
        # threshold here so we don't emit a "fired" record for a
        # decision the simulator will immediately refuse — wastes a
        # decision-log slot, burns an LLM round-trip when ensemble-
        # wrapped, and clouds the audit numbers. 33/35 unfilled fires
        # on 2026-05-11 matched this pattern.
        ask_size = self._ask_size_for_side.get(side)
        if ask_size is None and ask <= DEFAULT_FLOOR_BEST_ASK:
            return None

        # No tier rejection. No priors lookup. No EV gate. Just fire.
        price_limit = min(0.99, ask + self._limit_buffer)

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
            rationale=_rationale(d_bps, ttl_s, side),
        )

    def _compute_time_to_close_s(self, now_ts_utc_ns: int) -> int:
        if self._window_ts is None:
            return -1
        now_s = now_ts_utc_ns // 1_000_000_000
        close_s = self._window_ts + WINDOW_SECONDS
        return max(0, close_s - now_s)


def _rationale(d_bps: float, ttl_s: int, side: Side) -> str:
    return (
        f"strategy=wide_fire mode=ensemble_base " f"delta_bps={d_bps:+.2f} ttl={ttl_s}s side={side}"
    )

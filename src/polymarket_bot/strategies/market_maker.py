"""MarketMakerStrategy + LadderPlanner + InventoryTracker + RiskGate + PayoutResolver.

Locked spec: design/S.1-market-maker-bot.md (Phase S Session 1).
Source priors: design/j7_priors.json (n=306,966 bonereaper 30d aligned-WR
table; aligned-row WR 67.4%, alignment-gap +30.9pp).

MMB places maker-limit BUY orders on BOTH outcome tokens of each Polymarket
5-min BTC up/down market: a 3-level ladder per side per market at depths
-$0.05 / -$0.10 / -$0.20 below best_ask. It cancels-and-replaces on book
moves, accumulates inventory across the window, and holds to resolution.
Net edge comes from the population-level positive $/trade observed on the
bonereaper wallet ($0.66/trade across 306k trades, 51.7% direct WR, 67.4%
aligned WR) under the hypothesis that the edge is per-trade EV across
ladder-level sizing, not directional win-rate. Operator pushback 2026-05-20
on paper-mode-is-fake: MMB's queue position + book presence are part of
the edge, so simulator PnL is structurally optimistic and we rely on the
S.5 live-micro soak for honest edge measurement, not the Session 2 backtest.

This module ships the strategy-logic layer only. Order placement, cancel,
heartbeat, and the asyncio runner live in `_paper/mm_runner.py` (paper
shakedown) and `_live/clob_orders.py` (real CLOB calls) — Session 3
deliverables. The interface here is pure: actions are returned as
dataclasses; state lives in InventoryTracker; no IO.

Hard requirements surfaced from S.1.1 research (runbooks/S-mmb-research-
2026-05-20.md §5.1) that this module honors:

  1. Per-market tick + min-size enforcement — LadderPlanner rounds ladder
     prices to the market's tick size and skips levels whose size in
     shares falls below the market's `orderMinSize`.
  2. In-flight trades count toward inventory caps until CONFIRMED —
     InventoryTracker tracks `in_flight_usd` separately from `filled_usd`
     and includes both in cap checks.
  3. Floor + skip — no order below $0.05 (matches Phase 11.A simulator
     floor at commit 46b3ce6); skip a side entirely if best_ask < $0.10
     (the ladder would clip the floor).
  4. Window-end cleanup — at remaining_s < 15, cancel ALL open orders.

Decision #22 (Phase S build-not-copy carve-out from #19) governs the
overall posture: we use bonereaper's aggregate stats as a prior anchor,
not as live behavior to mirror.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final

from polymarket_bot.strategies.j7_priors import J7Priors

# Default ladder depths per design/S.1-market-maker-bot.md §2.2.
# Three levels below best_ask: -$0.05 / -$0.10 / -$0.20.
DEFAULT_LADDER_DEPTHS_USD: Final[tuple[float, ...]] = (0.05, 0.10, 0.20)

# Cancel-and-replace thresholds per design §2.2.
# Move > 2¢ at top of book → cancel + repost L1.
# Move > 5¢ at top of book → cancel + repost L2 and L3 as well.
DEFAULT_L1_REPOST_THRESHOLD: Final[float] = 0.02
DEFAULT_L2L3_REPOST_THRESHOLD: Final[float] = 0.05

# Window-end cleanup trigger: cancel ALL when this much time remains.
DEFAULT_WINDOW_CLEANUP_SECS: Final[float] = 15.0

# Edge 2 (audit 2026-05-20 §2): late-window size multiplier. Bonereaper's
# fresh weekly data showed the 0-30s + 30-60s buckets have $/tr 3-12x
# higher than mid/early. Default doubles ladder-level size when
# `seconds_remaining < 60`. Capped by RiskGate so it can't blow through
# the per-token / per-window / max-bet limits.
DEFAULT_LATE_WINDOW_THRESHOLD_S: Final[float] = 60.0
DEFAULT_LATE_WINDOW_SIZE_MULTIPLIER: Final[float] = 2.0

# Polymarket simulator floor (commit 46b3ce6, post-Phase-11.A): do not
# post any order below $0.05. Below this, fill behavior is phantom.
DEFAULT_PRICE_FLOOR: Final[float] = 0.05

# Default risk caps for live-micro deploy at $1k bankroll (design §2.4).
# Scale-up column lives in the design doc and ships via a separate
# RiskCaps instance — these are the conservative live-micro defaults.
DEFAULT_MAX_INVENTORY_PER_TOKEN_USD: Final[float] = 25.0
DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_USD: Final[float] = 50.0
DEFAULT_MAX_OPEN_ORDERS_GLOBAL: Final[int] = 20
DEFAULT_MAX_DAILY_LOSS_USD: Final[float] = 50.0
DEFAULT_MAX_ORDERS_PER_MINUTE: Final[int] = 30

# Edge 3 (audit 2026-05-20 §4): pct-of-bankroll cap defaults. Conservative
# initial values for S.5 — half of the §4 spec's "scale-up" values. Operator
# ramps via MM_CAPS_MODE=pct_bankroll env-flip after Day-1 + Day-7 audits.
DEFAULT_MAX_INVENTORY_PER_TOKEN_PCT: Final[float] = 0.025  # 2.5% of bankroll
DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_PCT: Final[float] = 0.05  # 5% per window
DEFAULT_MAX_DAILY_LOSS_PCT: Final[float] = 0.05  # 5% daily loss → halt
# Absolute sanity ceiling on per-order bet. At $100k bankroll a 1% per-order
# pct cap = $1,000; the absolute ceiling at $500 keeps us inside CLOB
# liquidity at the upper bankroll bound (operator-decision to lift later).
DEFAULT_MAX_BET_USD_CEILING: Final[float] = 500.0


class Side(StrEnum):
    """Bet direction for a ladder level. Distinct from BUY/SELL order semantics —
    MMB only ever places BUY orders; UP/DOWN tags which outcome token."""

    UP = "UP"
    DOWN = "DOWN"


class OrderStatus(StrEnum):
    """Order lifecycle state. Mirrors CLOB trade-status from agent-skills
    order-patterns.md but condensed for inventory accounting."""

    PENDING = "PENDING"
    LIVE = "LIVE"
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(slots=True, frozen=True)
class LadderLevel:
    """One rung of the 3-level ladder. Pure data; no state."""

    market_id: str
    token_id: str
    side: Side
    depth_from_ask_usd: float
    price: float
    size_usd: float
    size_shares: float


@dataclass(slots=True, frozen=True)
class PlaceOrder:
    """Action: post a new maker-limit BUY at `level.price` for `level.size_shares`."""

    level: LadderLevel


@dataclass(slots=True, frozen=True)
class CancelOrder:
    """Action: cancel an existing order by its order_id."""

    order_id: str


# Union over actions LadderPlanner.plan_update() can emit.
LadderAction = PlaceOrder | CancelOrder


@dataclass(slots=True)
class OpenOrder:
    """An order this strategy has on the book (or in-flight to/from the book)."""

    order_id: str
    level: LadderLevel
    status: OrderStatus
    placed_ts_ns: int


@dataclass(slots=True)
class InventoryPosition:
    """Per-(market, side) inventory state.

    `filled_usd` and `filled_shares` aggregate CONFIRMED fills only.
    `in_flight_usd` and `in_flight_shares` track MATCHED/MINED fills that
    have not yet confirmed; both are included in cap math so an inflight
    burst can't slip past MAX_INVENTORY. On confirmation the in_flight
    counters drain into the filled counters.
    """

    market_id: str
    side: Side
    filled_usd: float = 0.0
    filled_shares: float = 0.0
    in_flight_usd: float = 0.0
    in_flight_shares: float = 0.0

    @property
    def gross_usd(self) -> float:
        """Total committed capital on this (market, side) — used for cap math."""
        return self.filled_usd + self.in_flight_usd

    @property
    def gross_shares(self) -> float:
        """Total share count on this (market, side) for payout math."""
        return self.filled_shares + self.in_flight_shares


@dataclass(slots=True)
class RiskCaps:
    """Hard caps from design/S.1-market-maker-bot.md §2.4 + audit §4 (Edge 3).

    Two cap modes:

      - `fixed_usd` (default, S.5 first-deploy): the *_usd fields bind
        directly. Behavior identical to pre-Edge-3 code.
      - `pct_bankroll`: the *_pct fields are evaluated against the live
        bankroll at each `effective_*` call. As bankroll compounds, caps
        scale proportionally — the operator-vision compounding trajectory.

    `max_bet_usd_ceiling` is an absolute ceiling that ALWAYS applies (in
    either mode), bounding runaway sizing if Kelly suggests > $500 per
    order at large bankroll. Operator lifts this when comfortable.
    """

    # fixed_usd mode (existing behavior)
    max_inventory_per_token_usd: float = DEFAULT_MAX_INVENTORY_PER_TOKEN_USD
    max_gross_exposure_per_window_usd: float = DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_USD
    max_open_orders_global: int = DEFAULT_MAX_OPEN_ORDERS_GLOBAL
    max_daily_loss_usd: float = DEFAULT_MAX_DAILY_LOSS_USD
    max_orders_per_minute: int = DEFAULT_MAX_ORDERS_PER_MINUTE

    # Edge 3 — pct-of-bankroll fields
    max_inventory_per_token_pct: float = DEFAULT_MAX_INVENTORY_PER_TOKEN_PCT
    max_gross_exposure_per_window_pct: float = DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_PCT
    max_daily_loss_pct: float = DEFAULT_MAX_DAILY_LOSS_PCT
    max_bet_usd_ceiling: float = DEFAULT_MAX_BET_USD_CEILING

    # Mode selector: which set of fields wins.
    caps_mode: str = "fixed_usd"

    def __post_init__(self) -> None:
        for fname in (
            "max_inventory_per_token_usd",
            "max_gross_exposure_per_window_usd",
            "max_daily_loss_usd",
        ):
            v = getattr(self, fname)
            if v <= 0:
                raise ValueError(f"{fname} must be > 0; got {v}")
        if self.max_open_orders_global <= 0:
            raise ValueError(
                f"max_open_orders_global must be > 0; got {self.max_open_orders_global}"
            )
        if self.max_orders_per_minute <= 0:
            raise ValueError(f"max_orders_per_minute must be > 0; got {self.max_orders_per_minute}")
        for pname in (
            "max_inventory_per_token_pct",
            "max_gross_exposure_per_window_pct",
            "max_daily_loss_pct",
        ):
            v = getattr(self, pname)
            if not 0 < v <= 1.0:
                raise ValueError(f"{pname} must be in (0, 1]; got {v}")
        if self.max_bet_usd_ceiling <= 0:
            raise ValueError(f"max_bet_usd_ceiling must be > 0; got {self.max_bet_usd_ceiling}")
        if self.caps_mode not in ("fixed_usd", "pct_bankroll"):
            raise ValueError(
                f"caps_mode must be 'fixed_usd' or 'pct_bankroll'; got {self.caps_mode!r}"
            )

    def effective_max_inventory_per_token(self, bankroll_usd: float) -> float:
        """Resolve the per-token inventory cap against current bankroll.

        In fixed_usd mode returns the static USD field. In pct_bankroll
        mode returns `pct * bankroll`, clamped to max_bet_usd_ceiling
        (defensive — prevents giant inventory if bankroll spikes)."""
        if self.caps_mode == "pct_bankroll":
            return min(self.max_inventory_per_token_pct * bankroll_usd, self.max_bet_usd_ceiling)
        return self.max_inventory_per_token_usd

    def effective_max_gross_exposure(self, bankroll_usd: float) -> float:
        """Resolve the per-window gross cap against current bankroll."""
        if self.caps_mode == "pct_bankroll":
            return min(
                self.max_gross_exposure_per_window_pct * bankroll_usd,
                self.max_bet_usd_ceiling * 2.0,
            )
        return self.max_gross_exposure_per_window_usd

    def effective_max_daily_loss(self, bankroll_usd: float) -> float:
        """Resolve the daily-loss halt threshold against current bankroll."""
        if self.caps_mode == "pct_bankroll":
            return self.max_daily_loss_pct * bankroll_usd
        return self.max_daily_loss_usd


def round_to_tick(price: float, tick_size: str) -> float:
    """Round `price` DOWN to the nearest multiple of `tick_size`.

    Use Decimal for tick rounding so floats don't drift; the CLOB rejects
    any order whose price doesn't match the market's tick exactly
    (`INVALID_ORDER_MIN_TICK_SIZE` per order-patterns.md error table).
    Round DOWN (not nearest) because we want the maker level safely
    below the best_ask; rounding up could push us above the depth target.
    """
    tick = Decimal(tick_size)
    if tick <= 0:
        raise ValueError(f"tick_size must be > 0; got {tick_size}")
    p = Decimal(str(price))
    multiplier = (p / tick).quantize(Decimal("1"))  # floor by truncation
    # Adjust if quantize rounded up (banker's rounding can land us above p):
    while multiplier * tick > p:
        multiplier -= 1
    return float(multiplier * tick)


def tier_for_price(price: float) -> str | None:
    """Map a CLOB price (in dollars, 0-1) to a J.7 tier label.

    Boundaries match design/j7_priors.json schema notes ("inclusive-lower
    / exclusive-upper"). Returns None on a degenerate price so callers can
    distinguish "no tier" from "valid tier with no aligned data".
    """
    if price <= 0.0 or price >= 1.0:
        return None
    if price < 0.15:
        return "<15%"
    if price < 0.30:
        return "15-30%"
    if price < 0.50:
        return "30-50%"
    if price < 0.70:
        return "50-70%"
    if price < 0.85:
        return "70-85%"
    return "85-100%"


# Per-tier-side blocklist locked from `runbooks/research/mmb-deep-edge-audit-
# 2026-05-20.md` §2 Edge 1. These three cells were measured at NEGATIVE $/tr
# across n=8,000+ fresh weekly fills (bonereaper 2026-05-19) — keeping them
# enabled in MMB at our scale is a guaranteed weekly leak.
DEFAULT_TIER_SIDE_BLOCKLIST: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("50-70%", "DOWN"),  # -$0.76/tr x 3366 fills = -$2,563/wk leak
        ("15-30%", "UP"),  # -$0.61/tr x 1345 fills = -$820/wk leak
        ("30-50%", "UP"),  # -$0.11/tr x 3079 fills = -$325/wk marginal leak
    }
)


@dataclass(slots=True)
class LadderPlanner:
    """Pure planner: produces ladder levels + cancel/replace actions.

    No state — the strategy owns active-orders state and passes it in.
    `J7Priors` is the priors source for per-level sizing. `RiskCaps` is
    read for the per-token inventory cap; gross + daily checks happen in
    `RiskGate`.

    `blocklist` is a set of (tier, side-string) pairs the planner will
    refuse to ladder. Default set comes from the 2026-05-20 deep edge audit
    (`runbooks/research/mmb-deep-edge-audit-2026-05-20.md` §2 Edge 1) which
    found 3 cells with statistically-real negative $/tr in bonereaper's
    fresh weekly fills. Side is stored as the StrEnum value (`"UP"` /
    `"DOWN"`) so the literal set is JSON-serialisable for env-driven
    overrides without depending on the Side enum at module load time.
    """

    priors: J7Priors
    caps: RiskCaps = field(default_factory=RiskCaps)
    depths_usd: tuple[float, ...] = DEFAULT_LADDER_DEPTHS_USD
    l1_repost_threshold: float = DEFAULT_L1_REPOST_THRESHOLD
    l2l3_repost_threshold: float = DEFAULT_L2L3_REPOST_THRESHOLD
    window_cleanup_secs: float = DEFAULT_WINDOW_CLEANUP_SECS
    price_floor: float = DEFAULT_PRICE_FLOOR
    blocklist: frozenset[tuple[str, str]] = DEFAULT_TIER_SIDE_BLOCKLIST
    late_window_threshold_s: float = DEFAULT_LATE_WINDOW_THRESHOLD_S
    late_window_size_multiplier: float = DEFAULT_LATE_WINDOW_SIZE_MULTIPLIER

    def plan_levels(
        self,
        *,
        market_id: str,
        token_id: str,
        side: Side,
        best_ask: float,
        bankroll_usd: float,
        tick_size: str,
        min_order_size_shares: float,
        seconds_remaining: float | None = None,
    ) -> list[LadderLevel]:
        """Generate the 3-level ladder for one (market, side) at current book state.

        Skip the entire side if `best_ask < $0.10` (any ladder would clip
        the $0.05 floor). Skip any individual level whose post-tick-rounded
        price falls below the floor, OR whose Kelly-sized USD bet is 0
        (no edge / below MIN_BET), OR whose share count would fall below
        the market's `min_order_size_shares`.

        `seconds_remaining` enables Edge 2 (audit §2 Edge 2): when the
        window is in its LATE phase (default < 60s remaining), size each
        level by `late_window_size_multiplier` (default 2x). Bonereaper's
        fresh weekly data shows 0-30s + 30-60s buckets have $/tr 3-12x
        higher than mid/early — overweighting size there is the second
        major audit edge. None (default) preserves the pre-Edge-2 behavior
        for callers that don't supply window timing.
        """
        if best_ask < self.price_floor * 2.0:
            # best_ask < $0.10: every ladder level clips the floor.
            return []
        levels: list[LadderLevel] = []
        for depth in self.depths_usd:
            raw_price = best_ask - depth
            if raw_price < self.price_floor:
                continue
            price = round_to_tick(raw_price, tick_size)
            if price < self.price_floor:
                continue
            tier = tier_for_price(price)
            if tier is None:
                continue
            # Edge 1 (audit §2): refuse to ladder cells the data marks as
            # statistically-negative-$/tr. Skip per-level (not per-side)
            # because ladder depths can span tier boundaries — e.g. at
            # best_ask=0.55 the L3 lands in 30-50% which is blocked for UP
            # but L1+L2 are in 50-70% (also blocked for DOWN). Per-level
            # check catches both cases cleanly.
            if (tier, side.value) in self.blocklist:
                continue
            size_usd = self.priors.bet_size(tier=tier, fill_price=price, bankroll=bankroll_usd)
            if size_usd <= 0.0:
                continue
            # Edge 2 (audit §2): LATE-window size multiplier. Doubles size
            # in the last `late_window_threshold_s` of the window. Capped
            # by the per-token RiskCap to prevent blow-through.
            if seconds_remaining is not None and seconds_remaining < self.late_window_threshold_s:
                boosted = size_usd * self.late_window_size_multiplier
                size_usd = min(boosted, self.caps.max_inventory_per_token_usd)
            size_shares = size_usd / price
            if size_shares < min_order_size_shares:
                continue
            levels.append(
                LadderLevel(
                    market_id=market_id,
                    token_id=token_id,
                    side=side,
                    depth_from_ask_usd=depth,
                    price=price,
                    size_usd=size_usd,
                    size_shares=size_shares,
                )
            )
        return levels

    def plan_update(
        self,
        *,
        market_id: str,
        token_id: str,
        side: Side,
        current_best_ask: float,
        previous_best_ask: float | None,
        open_orders: list[OpenOrder],
        bankroll_usd: float,
        tick_size: str,
        min_order_size_shares: float,
        seconds_remaining: float,
    ) -> list[LadderAction]:
        """Compute the cancel + place actions needed to align the ladder to the current book.

        Decision matrix (design §2.2):
          - remaining < `window_cleanup_secs` → cancel ALL, place nothing.
          - book moved > `l2l3_repost_threshold` → cancel ALL open orders
            on this side, place fresh full ladder.
          - book moved > `l1_repost_threshold` → cancel L1 only, place
            fresh L1 at new depth.
          - otherwise no-op (existing ladder still valid).
        """
        actions: list[LadderAction] = []
        side_orders = [
            o for o in open_orders if o.level.side == side and o.level.market_id == market_id
        ]

        if seconds_remaining < self.window_cleanup_secs:
            actions.extend(CancelOrder(order_id=o.order_id) for o in side_orders)
            return actions

        if previous_best_ask is None:
            # First book update for this market — place full ladder fresh.
            # Pass seconds_remaining so Edge 2 late-window multiplier fires
            # when this is also the LATE-bucket placement.
            for lvl in self.plan_levels(
                market_id=market_id,
                token_id=token_id,
                side=side,
                best_ask=current_best_ask,
                bankroll_usd=bankroll_usd,
                tick_size=tick_size,
                min_order_size_shares=min_order_size_shares,
                seconds_remaining=seconds_remaining,
            ):
                actions.append(PlaceOrder(level=lvl))
            return actions

        move = abs(current_best_ask - previous_best_ask)

        if move > self.l2l3_repost_threshold:
            # Cancel all + replace
            actions.extend(CancelOrder(order_id=o.order_id) for o in side_orders)
            for lvl in self.plan_levels(
                market_id=market_id,
                token_id=token_id,
                side=side,
                best_ask=current_best_ask,
                bankroll_usd=bankroll_usd,
                tick_size=tick_size,
                min_order_size_shares=min_order_size_shares,
                seconds_remaining=seconds_remaining,
            ):
                actions.append(PlaceOrder(level=lvl))
            return actions

        if move > self.l1_repost_threshold:
            # Cancel L1 only (the level with smallest depth_from_ask_usd)
            # and replace at fresh L1 depth.
            if side_orders:
                l1_order = min(side_orders, key=lambda o: o.level.depth_from_ask_usd)
                actions.append(CancelOrder(order_id=l1_order.order_id))
                fresh_levels = self.plan_levels(
                    market_id=market_id,
                    token_id=token_id,
                    side=side,
                    best_ask=current_best_ask,
                    bankroll_usd=bankroll_usd,
                    tick_size=tick_size,
                    min_order_size_shares=min_order_size_shares,
                    seconds_remaining=seconds_remaining,
                )
                if fresh_levels:
                    fresh_l1 = min(fresh_levels, key=lambda lvl: lvl.depth_from_ask_usd)
                    actions.append(PlaceOrder(level=fresh_l1))
            return actions

        return actions


@dataclass(slots=True)
class InventoryTracker:
    """Per-(market, side) inventory state across the lifetime of the strategy.

    Inventory is keyed by (market_id, side). Window resolution drains
    positions via `resolve_window()`; partial fills, in-flight
    transitions, and cancels mutate the position fields. Caller is
    responsible for calling `resolve_window()` exactly once per
    (market, window) at window-close.
    """

    positions: dict[tuple[str, Side], InventoryPosition] = field(default_factory=dict)

    def position(self, market_id: str, side: Side) -> InventoryPosition:
        """Return the position; create a zeroed one if absent."""
        key = (market_id, side)
        pos = self.positions.get(key)
        if pos is None:
            pos = InventoryPosition(market_id=market_id, side=side)
            self.positions[key] = pos
        return pos

    def add_in_flight(
        self, market_id: str, side: Side, size_usd: float, size_shares: float
    ) -> None:
        """Record a MATCHED order awaiting CONFIRMED."""
        pos = self.position(market_id, side)
        pos.in_flight_usd += size_usd
        pos.in_flight_shares += size_shares

    def confirm_in_flight(
        self, market_id: str, side: Side, size_usd: float, size_shares: float
    ) -> None:
        """Move a confirmed fill from in_flight → filled."""
        pos = self.position(market_id, side)
        pos.in_flight_usd = max(0.0, pos.in_flight_usd - size_usd)
        pos.in_flight_shares = max(0.0, pos.in_flight_shares - size_shares)
        pos.filled_usd += size_usd
        pos.filled_shares += size_shares

    def drop_in_flight(
        self, market_id: str, side: Side, size_usd: float, size_shares: float
    ) -> None:
        """Remove in_flight on cancel/failure — does NOT credit to filled."""
        pos = self.position(market_id, side)
        pos.in_flight_usd = max(0.0, pos.in_flight_usd - size_usd)
        pos.in_flight_shares = max(0.0, pos.in_flight_shares - size_shares)

    def gross_exposure_for_market(self, market_id: str) -> float:
        """Sum gross USD across UP + DOWN for a single market."""
        return sum(p.gross_usd for (m, _s), p in self.positions.items() if m == market_id)

    def resolve_window(self, market_id: str, winning_side: Side) -> tuple[float, float]:
        """Drain positions for `market_id` and return (realized_pnl_usd, gross_traded_usd).

        Winning side: realized PnL = `gross_shares * $1.00` - `gross_usd` (you paid
        gross_usd to buy gross_shares shares; they each pay $1 at resolution).
        Losing side: realized PnL = `-gross_usd` (you paid that USD; shares pay $0).
        Positions are removed from the tracker after resolution.
        """
        realized = 0.0
        gross_traded = 0.0
        for side in (Side.UP, Side.DOWN):
            key = (market_id, side)
            pos = self.positions.get(key)
            if pos is None:
                continue
            gross_traded += pos.gross_usd
            if side == winning_side:
                realized += pos.gross_shares - pos.gross_usd
            else:
                realized -= pos.gross_usd
            del self.positions[key]
        return realized, gross_traded


@dataclass(slots=True)
class RiskGate:
    """Hard pre-place check against caps + halt state.

    Returned reason strings are stable: callers may log them or surface
    them to dashboards. None of the gate methods raise — they return a
    decision tuple `(allowed, reason)`.
    """

    caps: RiskCaps = field(default_factory=RiskCaps)
    halted: bool = False
    today_realized_pnl_usd: float = 0.0

    def can_place(
        self,
        *,
        market_id: str,
        side: Side,
        size_usd: float,
        tracker: InventoryTracker,
        open_orders_count: int,
        bankroll_usd: float = 0.0,
    ) -> tuple[bool, str]:
        """Approve or reject a single PlaceOrder action.

        Order of checks: cheapest first so we fail fast.

        `bankroll_usd` is required when `caps.caps_mode == 'pct_bankroll'`;
        in `fixed_usd` mode it's ignored. Defaults to 0.0 so a caller in
        pct mode that forgets to pass bankroll will fail all checks
        (safe) rather than silently disable the caps.
        """
        if self.halted:
            return False, "halted"
        if size_usd <= 0:
            return False, "zero_size"
        if open_orders_count >= self.caps.max_open_orders_global:
            return False, "max_open_orders"
        if self.today_realized_pnl_usd <= -self.caps.effective_max_daily_loss(bankroll_usd):
            return False, "max_daily_loss"
        pos = tracker.position(market_id, side)
        if pos.gross_usd + size_usd > self.caps.effective_max_inventory_per_token(bankroll_usd):
            return False, "max_inventory_per_token"
        gross_market = tracker.gross_exposure_for_market(market_id)
        if gross_market + size_usd > self.caps.effective_max_gross_exposure(bankroll_usd):
            return False, "max_gross_exposure"
        return True, "ok"

    def record_realized_pnl(self, pnl_usd: float, bankroll_usd: float = 0.0) -> None:
        """Accumulate window-resolved PnL into the daily-loss tracker.

        On a sufficiently bad day, the next `can_place()` will return
        `max_daily_loss`. Callers are responsible for also writing the
        halt sentinel + Telegram alert; this is the in-process gate.

        `bankroll_usd` matters in pct_bankroll mode — it sets the
        daily-loss threshold at the time of recording. In fixed_usd mode
        ignored.
        """
        self.today_realized_pnl_usd += pnl_usd
        if self.today_realized_pnl_usd <= -self.caps.effective_max_daily_loss(bankroll_usd):
            self.halted = True

    def force_halt(self, reason: str = "operator") -> None:
        """Manual halt — used by kill-switch env-var path."""
        self.halted = True


@dataclass(slots=True, frozen=True)
class WindowPnl:
    """Result of resolving one (market, window): realized PnL + traded notional."""

    market_id: str
    winning_side: Side
    realized_pnl_usd: float
    gross_traded_usd: float


@dataclass(slots=True)
class PayoutResolver:
    """Thin orchestrator: calls InventoryTracker.resolve_window + RiskGate.record."""

    tracker: InventoryTracker
    gate: RiskGate

    def resolve(
        self,
        *,
        market_id: str,
        winning_side: Side,
        bankroll_usd: float = 0.0,
    ) -> WindowPnl:
        """Resolve a window, update daily-loss tracker, and return the PnL record.

        `bankroll_usd` is threaded into the gate's PnL accumulator so the
        pct-mode daily-loss threshold resolves correctly. In fixed_usd
        mode it's ignored.
        """
        realized, gross = self.tracker.resolve_window(market_id, winning_side)
        self.gate.record_realized_pnl(realized, bankroll_usd=bankroll_usd)
        return WindowPnl(
            market_id=market_id,
            winning_side=winning_side,
            realized_pnl_usd=realized,
            gross_traded_usd=gross,
        )


# Callable that returns the current bankroll in USD. Injected as a
# dependency so live bankroll math (after past fills) is observable
# without coupling the strategy to the BankrollTracker module.
BankrollGetter = Callable[[], float]


@dataclass(slots=True, kw_only=True)
class MarketMakerStrategy:
    """Top-level MMB orchestrator: holds priors, planner, tracker, gate, resolver.

    Not a strict implementation of `polymarket_bot.strategies.protocol.Strategy`
    — that protocol returns a single `Decision | None` per event, which
    does not fit MMB's multi-order semantics. Instead this class exposes
    a richer interface used by `_paper/mm_runner.py` (Session 3):

      - `on_book_update(...)`  → list[LadderAction]
      - `on_fill(...)`         → None (state-mutating)
      - `on_resolution(...)`   → WindowPnl
      - `reset()`              → None

    Active-order state lives in `self.open_orders` keyed by order_id.
    Previous best_ask per (market, side) is held so `plan_update()` can
    compute book-move thresholds. Fields are keyword-only so callers must
    explicitly pass priors + bankroll_getter (no silent defaults).
    """

    priors: J7Priors
    bankroll_getter: BankrollGetter
    name: str = "market_maker"
    tracker: InventoryTracker = field(default_factory=InventoryTracker)
    gate: RiskGate = field(default_factory=RiskGate)
    blocklist: frozenset[tuple[str, str]] = DEFAULT_TIER_SIDE_BLOCKLIST
    planner: LadderPlanner = field(init=False)
    resolver: PayoutResolver = field(init=False)
    open_orders: dict[str, OpenOrder] = field(default_factory=dict)
    previous_best_ask: dict[tuple[str, Side], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.planner = LadderPlanner(
            priors=self.priors, caps=self.gate.caps, blocklist=self.blocklist
        )
        self.resolver = PayoutResolver(tracker=self.tracker, gate=self.gate)

    def on_book_update(
        self,
        *,
        market_id: str,
        token_id: str,
        side: Side,
        best_ask: float,
        tick_size: str,
        min_order_size_shares: float,
        seconds_remaining: float,
    ) -> list[LadderAction]:
        """Compute ladder actions for one (market, side) tick.

        Applies the planner's decision matrix, then filters each
        PlaceOrder through the RiskGate. PlaceOrders rejected by the
        gate are dropped silently (they should be logged by the caller).
        Returns the surviving action list in the order the planner
        produced (cancels before places where mixed).
        """
        key = (market_id, side)
        previous = self.previous_best_ask.get(key)
        actions = self.planner.plan_update(
            market_id=market_id,
            token_id=token_id,
            side=side,
            current_best_ask=best_ask,
            previous_best_ask=previous,
            open_orders=list(self.open_orders.values()),
            bankroll_usd=self.bankroll_getter(),
            tick_size=tick_size,
            min_order_size_shares=min_order_size_shares,
            seconds_remaining=seconds_remaining,
        )
        self.previous_best_ask[key] = best_ask
        approved: list[LadderAction] = []
        open_count = len(self.open_orders)
        bankroll_usd = self.bankroll_getter()
        for action in actions:
            if isinstance(action, CancelOrder):
                approved.append(action)
                continue
            # Exhaustive match: LadderAction = PlaceOrder | CancelOrder.
            # Narrow explicitly without assert (ruff S101).
            if not isinstance(action, PlaceOrder):
                continue
            # Edge 3: thread bankroll through so pct-mode caps resolve.
            # In fixed_usd mode the bankroll is ignored.
            allowed, _reason = self.gate.can_place(
                market_id=action.level.market_id,
                side=action.level.side,
                size_usd=action.level.size_usd,
                tracker=self.tracker,
                open_orders_count=open_count,
                bankroll_usd=bankroll_usd,
            )
            if allowed:
                approved.append(action)
                open_count += 1  # speculative — actual count updates on ack
        return approved

    def on_fill(
        self,
        *,
        market_id: str,
        side: Side,
        size_usd: float,
        size_shares: float,
        status: OrderStatus,
    ) -> None:
        """Update inventory accounting on a fill event.

        `status` distinguishes provisional (MATCHED/MINED → in_flight)
        from terminal (CONFIRMED → filled). Cancels and failures call
        `drop_in_flight` instead.
        """
        if status == OrderStatus.CONFIRMED:
            self.tracker.confirm_in_flight(market_id, side, size_usd, size_shares)
        elif status in (OrderStatus.MATCHED, OrderStatus.LIVE):
            self.tracker.add_in_flight(market_id, side, size_usd, size_shares)
        elif status in (OrderStatus.CANCELLED, OrderStatus.FAILED):
            self.tracker.drop_in_flight(market_id, side, size_usd, size_shares)

    def on_resolution(self, *, market_id: str, winning_side: Side) -> WindowPnl:
        """Resolve a window. Drains inventory for `market_id`, records realized PnL.
        Threads current bankroll through so the resolver's daily-loss check uses
        the pct-mode threshold (no-op in fixed_usd mode)."""
        self.previous_best_ask = {
            k: v for k, v in self.previous_best_ask.items() if k[0] != market_id
        }
        return self.resolver.resolve(
            market_id=market_id,
            winning_side=winning_side,
            bankroll_usd=self.bankroll_getter(),
        )

    def reset(self) -> None:
        """Clear all state — used by tests + walk-forward folds."""
        self.tracker = InventoryTracker()
        self.gate = RiskGate(caps=self.gate.caps)
        self.resolver = PayoutResolver(tracker=self.tracker, gate=self.gate)
        self.open_orders = {}
        self.previous_best_ask = {}

"""Fill simulator — match a Decision against captured top-of-book + self-impact.

Self-impact model is deliberately simple per design/backtest.md §5: a $5
trade against $5K of top-of-book depth moves the next-tick price by ~0.1¢
linearly. Phase 1B's first real fills calibrate this; Phase 3 uses paper
estimates. attempt_fill() answers "can this order fill against this book?"
in one snapshot; the walk-forward harness handles TTL by calling
attempt_fill repeatedly across the book updates inside the order's TTL.
"""

from __future__ import annotations

from polymarket_bot.backtest.types import BookUpdate, Decision, Fill

DEFAULT_FEE_BPS = 2.0
DEFAULT_IMPACT_PER_5USD_PER_5K_DEPTH = 0.001  # 0.1¢ per $5 trade vs $5K depth
DEFAULT_REFERENCE_TRADE_USD = 5.0
DEFAULT_REFERENCE_DEPTH_USD = 5_000.0
# Cap the linear-impact estimate at 1¢. The naive linear model
# overshoots wildly when ask_size_top is small but the deeper ladder is
# fine — e.g., $76 of top depth gives 6.6¢ impact, but a $5 trade
# really only walks the top tier (worst case ~0.5-1¢ slippage on a
# Polymarket BTC 5m market). Without the cap, thin-top books make
# every fill rejected even though they'd execute fine in practice.
DEFAULT_MAX_IMPACT_USD = 0.01

# Defensive depth floor — refuse fills when best_ask is in the near-floor
# zone AND ask_size_top is unknown. The audit 2026-05-10 found phantom
# wins at multiple price levels:
#   - $0.011 (taker, 2 windows) — original phantom case (~$449 each)
#   - $0.03 (maker, ~10+ windows) — the more common pattern with
#     wide_fire firing at price_limit=$0.03 and the book later crashing
#   - $0.04 (maker) and $0.021 (maker) — additional variants
# Real Polymarket depth at $0.01-0.05 is typically <$1 worth of shares;
# the simulator over-fills the entire $5 size and inflates pnl by 30-100x.
# Bumped 0.02 -> 0.05 on 2026-05-10 to catch the $0.03 maker pattern that
# slipped through the original threshold. Combined with the size-based
# guard below for defense in depth.
DEFAULT_FLOOR_BEST_ASK = 0.05

# Size-based defensive guard — refuse fills that would produce more
# shares than DEFAULT_MAX_FILL_SIZE_NO_DEPTH when the book has no
# ask_size_top info. For a $5 stake at $0.10 ask, size = 50 shares —
# above this is the over-fill zone where real Polymarket depth is
# almost certainly less than what the simulator would produce. This
# is more general than the price-floor check (it catches over-fills
# at any price level when depth is unknown).
DEFAULT_MAX_FILL_SIZE_NO_DEPTH = 50.0

# Phase T 2026-05-21 — size-guard is now PRICE-CONDITIONAL. Historical
# phantom over-fills (per Phase 11.A audit 2026-05-10) happened at
# prices $0.011, $0.021, $0.03, $0.04 — all below 0.05. The original
# price-floor guard catches those via _floor_best_ask. The size-cap
# defense-in-depth is now scoped to fill_price < DEFAULT_SIZE_GUARD_MAX_PRICE
# (= 0.10, 2x safety margin above the highest measured phantom-fill
# price). Above 0.10, legitimate Kelly-sized bets at mid-prices
# routinely produce 200-600 shares which real Polymarket depth absorbs
# without difficulty. Pre-fix fill-rate audit (2026-05-21, n=38) found
# the price-blind size cap rejected 23 legitimate mid-price fires
# (60% of fires) while preventing zero phantom-fills. See
# design/phase-T-fill-sim-size-guard-fix.md.
DEFAULT_SIZE_GUARD_MAX_PRICE = 0.10


class FillSimulator:
    """Simulates a buy-side fill against a single BookUpdate snapshot."""

    def __init__(
        self,
        *,
        fee_bps: float = DEFAULT_FEE_BPS,
        impact_per_5usd_per_5k: float = DEFAULT_IMPACT_PER_5USD_PER_5K_DEPTH,
        reference_trade_usd: float = DEFAULT_REFERENCE_TRADE_USD,
        reference_depth_usd: float = DEFAULT_REFERENCE_DEPTH_USD,
        max_impact_usd: float = DEFAULT_MAX_IMPACT_USD,
        floor_best_ask: float = DEFAULT_FLOOR_BEST_ASK,
        max_fill_size_no_depth: float = DEFAULT_MAX_FILL_SIZE_NO_DEPTH,
        size_guard_max_price: float = DEFAULT_SIZE_GUARD_MAX_PRICE,
    ) -> None:
        if fee_bps < 0:
            raise ValueError(f"fee_bps must be >= 0, got {fee_bps}")
        self._fee_bps = fee_bps
        self._impact_per_5usd_per_5k = impact_per_5usd_per_5k
        self._ref_trade = reference_trade_usd
        self._ref_depth = reference_depth_usd
        self._max_impact = max(0.0, max_impact_usd)
        self._floor_best_ask = max(0.0, floor_best_ask)
        self._max_fill_size_no_depth = max(0.0, max_fill_size_no_depth)
        self._size_guard_max_price = max(0.0, size_guard_max_price)

    def _refuse_for_no_depth(self, fill_price: float, size_filled: float, book: BookUpdate) -> bool:
        """Returns True when the would-be fill should be refused due to
        missing depth info + phantom-floor or over-fill pattern.

        Two conditions when ask_size_top is unknown:
          (a) fill_price <= floor_best_ask (near-floor pricing where
              real-book depth is microscopic);
          (b) fill_price < size_guard_max_price AND
              size_filled >= max_fill_size_no_depth (defense-in-depth
              for the near-floor over-fill zone; gated to prices below
              size_guard_max_price=0.10 per Phase T fill-rate audit
              2026-05-21 — see design/phase-T-fill-sim-size-guard-fix.md).

        Either condition triggers refusal. Above size_guard_max_price the
        size cap does NOT apply: legitimate Kelly-sized bets at mid-prices
        (0.30-0.85) routinely produce 200+ shares which real Polymarket
        depth absorbs without difficulty.
        """
        if book.ask_size_top is not None:
            return False
        if fill_price <= self._floor_best_ask:
            return True
        if fill_price < self._size_guard_max_price and size_filled >= self._max_fill_size_no_depth:
            return True
        return False

    def attempt_fill(
        self, decision: Decision, book: BookUpdate, *, is_taker: bool = True
    ) -> Fill | None:
        """Return Fill if the decision's limit allows a fill against this book.

        Two paths, controlled by ``is_taker``:

        TAKER (initial fill at decision time) — we cross the spread; our
        buy walks the ask side and incurs impact.
          - effective_ask = best_ask + impact(size_usd, depth=ask_size_top USD)
          - limit must be >= effective_ask
          - fill_price = effective_ask  (we got the ask + slippage)

        MAKER (pending-order match against a later book update) — our limit
        is resting; an incoming seller crosses our bid. Standard CLOB
        price-improvement rule: the maker's resting price is the trade
        price, and the maker incurs no impact (the seller is aggressor).
          - limit must be >= best_ask  (a seller has crossed our bid)
          - fill_price = decision.price_limit  (NOT min(limit, ask))

        Why this distinction matters: without it, a buy resting at $0.30
        would "fill" at $0.011 if the ask later crashed to $0.011 — which
        is impossible on a real CLOB, where any seller offering at $0.011
        crosses our $0.30 bid first and we'd be filled at $0.30. The naive
        ``min(limit, ask)`` model produced phantom 90x returns in
        paper-mode that wouldn't reproduce live (e.g., window 1778275800
        on 2026-05-08).

        The caller (PaperRunner / BacktestRunner) is responsible for
        passing the correct ``is_taker`` flag — True for immediate fills
        at decision time, False for pending fills against later book
        updates.
        """
        if book.asset_id != decision.asset_id:
            return None
        if book.best_ask is None:
            return None
        if is_taker:
            depth_usd = self._ask_depth_usd(book)
            impact = self._impact(decision.size_usd, depth_usd)
            effective_ask = book.best_ask + impact
            if decision.price_limit < effective_ask:
                return None
            fill_price = effective_ask
            # Defensive guard: refuse when ask depth is unknown AND the
            # would-be fill is near-floor or over-large. See
            # _refuse_for_no_depth + audit 2026-05-10 (windows 1778388600,
            # 1778389500, 1778390700, 1778415300, etc.). Without this
            # the simulator over-fills $5 at the floor producing 100-450
            # shares, which is impossible vs real Polymarket book depth
            # at those price levels.
            size_filled = decision.size_usd / fill_price
            if self._refuse_for_no_depth(fill_price, size_filled, book):
                return None
        else:
            # Maker path: a later book update has dropped the ask to or
            # below our resting limit. Treat as an incoming seller crossing
            # our bid; fill at the resting limit price.
            if decision.price_limit < book.best_ask:
                return None
            fill_price = decision.price_limit
            # Same defensive guard on the maker path. The later book that
            # triggers the maker fill may itself be a depth-less event
            # (best_bid_ask / price_change); refusing prevents the bot
            # from "filling" 166.67 shares at $0.03 when real book depth
            # at the floor is typically <$1.
            size_filled = decision.size_usd / fill_price
            if self._refuse_for_no_depth(fill_price, size_filled, book):
                return None
        fee_usd = decision.size_usd * (self._fee_bps / 10_000.0)
        return Fill(
            ts_utc_ns=book.ts_utc_ns,
            asset_id=decision.asset_id,
            size_filled=size_filled,
            price_filled=fill_price,
            fee_usd=fee_usd,
        )

    def _impact(self, trade_size_usd: float, depth_usd: float | None) -> float:
        if depth_usd is None or depth_usd <= 0:
            # Without depth info, assume reference depth.
            depth_usd = self._ref_depth
        ratio = (trade_size_usd / self._ref_trade) * (self._ref_depth / depth_usd)
        linear = self._impact_per_5usd_per_5k * ratio
        return min(linear, self._max_impact)

    def _ask_depth_usd(self, book: BookUpdate) -> float | None:
        if book.ask_size_top is None or book.best_ask is None:
            return None
        # ask_size is in shares; multiply by price for USD notional.
        return book.ask_size_top * book.best_ask


def realised_pnl_usd(
    fill: Fill,
    resolution_side_winning: bool,
) -> float:
    """Compute net P&L in USD for a single fill given the window resolution.

    Polymarket binary outcome shares pay $1 per share if the side wins, $0
    if it loses. Net = (1 if winning else 0) * size_filled - cost - fee.
    """
    cost = fill.size_filled * fill.price_filled
    payout = fill.size_filled if resolution_side_winning else 0.0
    return payout - cost - fill.fee_usd

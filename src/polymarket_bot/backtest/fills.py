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
    ) -> None:
        if fee_bps < 0:
            raise ValueError(f"fee_bps must be >= 0, got {fee_bps}")
        self._fee_bps = fee_bps
        self._impact_per_5usd_per_5k = impact_per_5usd_per_5k
        self._ref_trade = reference_trade_usd
        self._ref_depth = reference_depth_usd
        self._max_impact = max(0.0, max_impact_usd)

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
        else:
            # Maker path: a later book update has dropped the ask to or
            # below our resting limit. Treat as an incoming seller crossing
            # our bid; fill at the resting limit price.
            if decision.price_limit < book.best_ask:
                return None
            fill_price = decision.price_limit
        size_filled = decision.size_usd / fill_price
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

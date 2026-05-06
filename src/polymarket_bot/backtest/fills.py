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


class FillSimulator:
    """Simulates a buy-side fill against a single BookUpdate snapshot."""

    def __init__(
        self,
        *,
        fee_bps: float = DEFAULT_FEE_BPS,
        impact_per_5usd_per_5k: float = DEFAULT_IMPACT_PER_5USD_PER_5K_DEPTH,
        reference_trade_usd: float = DEFAULT_REFERENCE_TRADE_USD,
        reference_depth_usd: float = DEFAULT_REFERENCE_DEPTH_USD,
    ) -> None:
        if fee_bps < 0:
            raise ValueError(f"fee_bps must be >= 0, got {fee_bps}")
        self._fee_bps = fee_bps
        self._impact_per_5usd_per_5k = impact_per_5usd_per_5k
        self._ref_trade = reference_trade_usd
        self._ref_depth = reference_depth_usd

    def attempt_fill(self, decision: Decision, book: BookUpdate) -> Fill | None:
        """Return Fill if the decision's limit allows a fill against this book.

        Filter rules:
          - book.asset_id must match decision.asset_id
          - book.best_ask must exist
          - effective_ask = best_ask + impact(size_usd, depth=ask_size_top USD)
          - limit must be >= effective_ask for the order to fill
        """
        if book.asset_id != decision.asset_id:
            return None
        if book.best_ask is None:
            return None
        depth_usd = self._ask_depth_usd(book)
        impact = self._impact(decision.size_usd, depth_usd)
        effective_ask = book.best_ask + impact
        if decision.price_limit < effective_ask:
            return None
        # Buyer fills at the better of best_ask+impact and the limit (just
        # effective_ask in this model). Real CLOB matching is more nuanced
        # (the buy ladder eats the ask side); this is the paper estimate.
        fill_price = min(decision.price_limit, effective_ask)
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
        return self._impact_per_5usd_per_5k * ratio

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

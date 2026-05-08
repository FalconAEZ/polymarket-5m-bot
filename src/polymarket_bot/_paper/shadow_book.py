"""ShadowBook — per-asset latest BookUpdate + TTL-gated FillSimulator delegation.

Phase 4 paper-mode book mirror (design/paper.md §4.1). update(book) keeps
the most recent BookUpdate per asset_id, latest(asset_id) reads it back,
and attempt_fill(decision, now_ns) enforces decision.ttl_s before
delegating to the same FillSimulator the backtest harness uses. Sharing
the simulator is intentional: the cost model must be identical between
backtest and paper so the Phase 4 sim-validation script can isolate
"book staleness" from "fee math wrong" as orthogonal failure modes.
"""

from __future__ import annotations

from polymarket_bot.backtest.fills import FillSimulator
from polymarket_bot.backtest.types import BookUpdate, Decision, Fill


class ShadowBook:
    """In-memory snapshot of the most recent BookUpdate per asset_id."""

    def __init__(self, simulator: FillSimulator | None = None) -> None:
        self._sim = simulator if simulator is not None else FillSimulator()
        self._book_by_asset: dict[str, BookUpdate] = {}

    def update(self, book: BookUpdate) -> None:
        prev = self._book_by_asset.get(book.asset_id)
        if prev is not None and book.ts_utc_ns < prev.ts_utc_ns:
            # Stale book arriving out-of-order: keep the newer one.
            return
        self._book_by_asset[book.asset_id] = book

    def latest(self, asset_id: str) -> BookUpdate | None:
        return self._book_by_asset.get(asset_id)

    def attempt_fill(
        self, decision: Decision, now_ts_ns: int, *, is_taker: bool = True
    ) -> Fill | None:
        """Try to fill against the latest book for decision.asset_id.

        Returns Fill if the decision's limit allows fill against the latest
        book and the elapsed time since decision creation is within ttl_s.
        Returns None if no book is known, the TTL has expired, or the
        FillSimulator rejects the fill.

        ``is_taker`` discriminates immediate vs pending fills. Default True
        preserves the original (taker-only) behavior for callers that
        haven't been updated. PaperRunner passes is_taker=True from
        _on_decision and is_taker=False from _try_fill_pending.
        """
        book = self._book_by_asset.get(decision.asset_id)
        if book is None:
            return None
        elapsed_s = (now_ts_ns - decision.ts_utc_ns) / 1e9
        if elapsed_s < 0 or elapsed_s > decision.ttl_s:
            return None
        return self._sim.attempt_fill(decision, book, is_taker=is_taker)

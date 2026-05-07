"""Tests for polymarket_bot._paper.shadow_book.ShadowBook.

Cover: latest() empty / present, update() keeps newest, stale-out-of-order
ignored, attempt_fill returns None for unknown asset, TTL gate rejects
late attempts, FillSimulator delegation produces identical Fill to a
direct simulator.attempt_fill call on the same inputs.
"""

from __future__ import annotations

from polymarket_bot._paper.shadow_book import ShadowBook
from polymarket_bot.backtest.fills import FillSimulator
from polymarket_bot.backtest.types import BookUpdate, Decision

TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def _book(
    asset_id: str = TOKEN_UP,
    *,
    ts_utc_ns: int = 1_000_000_000,
    best_ask: float | None = 0.50,
    ask_size_top: float | None = 10_000.0,
) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=ts_utc_ns,
        asset_id=asset_id,
        side="UP",
        best_bid=0.49 if best_ask is not None else None,
        best_ask=best_ask,
        bid_size_top=ask_size_top,
        ask_size_top=ask_size_top,
    )


def _decision(
    asset_id: str = TOKEN_UP,
    *,
    ts_utc_ns: int = 1_000_000_000,
    price_limit: float = 0.55,
    ttl_s: int = 20,
) -> Decision:
    return Decision(
        ts_utc_ns=ts_utc_ns,
        asset_id=asset_id,
        side="BUY",
        size_usd=5.0,
        price_limit=price_limit,
        ttl_s=ttl_s,
        rationale="test side=UP",
    )


def test_latest_returns_none_when_unknown() -> None:
    book = ShadowBook()
    assert book.latest(TOKEN_UP) is None


def test_update_then_latest_returns_book() -> None:
    book = ShadowBook()
    b = _book()
    book.update(b)
    assert book.latest(TOKEN_UP) is b


def test_update_keeps_newer_book() -> None:
    book = ShadowBook()
    older = _book(ts_utc_ns=1_000_000_000, best_ask=0.50)
    newer = _book(ts_utc_ns=2_000_000_000, best_ask=0.52)
    book.update(older)
    book.update(newer)
    latest = book.latest(TOKEN_UP)
    assert latest is not None
    assert latest.best_ask == 0.52


def test_stale_out_of_order_book_is_ignored() -> None:
    book = ShadowBook()
    newer = _book(ts_utc_ns=2_000_000_000, best_ask=0.52)
    older = _book(ts_utc_ns=1_000_000_000, best_ask=0.50)
    book.update(newer)
    book.update(older)
    latest = book.latest(TOKEN_UP)
    assert latest is not None
    assert latest.best_ask == 0.52  # stayed at newer


def test_distinct_asset_ids_kept_separately() -> None:
    book = ShadowBook()
    up = _book(asset_id=TOKEN_UP, best_ask=0.50)
    down = _book(asset_id=TOKEN_DOWN, best_ask=0.45)
    book.update(up)
    book.update(down)
    assert book.latest(TOKEN_UP) is up
    assert book.latest(TOKEN_DOWN) is down


def test_attempt_fill_returns_none_when_no_book() -> None:
    book = ShadowBook()
    decision = _decision()
    assert book.attempt_fill(decision, now_ts_ns=decision.ts_utc_ns) is None


def test_attempt_fill_returns_none_when_ttl_expired() -> None:
    book = ShadowBook()
    book.update(_book())
    decision = _decision(ttl_s=10)
    # 11 seconds elapsed > 10 ttl
    too_late = decision.ts_utc_ns + 11 * 1_000_000_000
    assert book.attempt_fill(decision, now_ts_ns=too_late) is None


def test_attempt_fill_returns_none_when_clock_runs_backward() -> None:
    book = ShadowBook()
    book.update(_book())
    decision = _decision()
    earlier = decision.ts_utc_ns - 1_000_000_000
    assert book.attempt_fill(decision, now_ts_ns=earlier) is None


def test_attempt_fill_matches_direct_simulator() -> None:
    """ShadowBook must produce the same Fill as FillSimulator on same inputs."""
    sim = FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.0)
    book = ShadowBook(simulator=sim)
    b = _book(best_ask=0.50)
    book.update(b)
    decision = _decision(price_limit=0.55)
    paper_fill = book.attempt_fill(decision, now_ts_ns=decision.ts_utc_ns + 1_000_000)
    direct_fill = sim.attempt_fill(decision, b)
    assert paper_fill is not None
    assert direct_fill is not None
    assert paper_fill.asset_id == direct_fill.asset_id
    assert paper_fill.price_filled == direct_fill.price_filled
    assert paper_fill.size_filled == direct_fill.size_filled
    assert paper_fill.fee_usd == direct_fill.fee_usd


def test_attempt_fill_rejects_when_limit_below_ask() -> None:
    book = ShadowBook()
    book.update(_book(best_ask=0.50))
    decision = _decision(price_limit=0.40)
    # within TTL but limit too low
    assert book.attempt_fill(decision, now_ts_ns=decision.ts_utc_ns) is None


def test_attempt_fill_rejects_when_asset_id_mismatches_known_books() -> None:
    book = ShadowBook()
    book.update(_book(asset_id=TOKEN_UP))
    decision = _decision(asset_id=TOKEN_DOWN)
    # Even though we have books, none match the decision's asset_id.
    assert book.attempt_fill(decision, now_ts_ns=decision.ts_utc_ns) is None

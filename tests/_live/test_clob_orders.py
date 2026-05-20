"""Tests for polymarket_bot._live.clob_orders MockClobOrderClient.

LiveClobOrderClient is NOT tested here — it requires a real py-clob-client
+ live CLOB credentials + funded Signer, all of which are S.4+ scope.
The Mock's contract IS the type contract Live must honor (Protocol).
"""

from __future__ import annotations

import pytest

from polymarket_bot._live.clob_orders import (
    ClobOrderError,
    MockClobOrderClient,
    Orderbook,
    OrderbookLevel,
    OrderSizeViolation,
    OrderTickViolation,
    PostOnlyRejected,
)
from polymarket_bot.strategies.market_maker import OrderStatus


def _book(token_id: str = "t1", best_ask: float = 0.50, ts_ns: int = 1) -> Orderbook:  # noqa: S107
    return Orderbook(
        token_id=token_id,
        bids=(OrderbookLevel(price=best_ask - 0.02, size_shares=100.0),),
        asks=(OrderbookLevel(price=best_ask, size_shares=100.0),),
        tick_size="0.01",
        min_order_size_shares=5.0,
        neg_risk=False,
        ts_ns=ts_ns,
    )


async def test_mock_place_below_ask_succeeds() -> None:
    client = MockClobOrderClient()
    client.set_orderbook(_book(best_ask=0.50))
    result = await client.place_maker_limit(
        token_id="t1", price=0.45, size_shares=20.0, tick_size="0.01"
    )
    assert result.order_id  # non-empty
    assert result.status == OrderStatus.LIVE
    assert client.open_orders_count() == 1


async def test_mock_post_only_rejects_on_cross() -> None:
    """Limit BUY at exactly best_ask crosses → PostOnlyRejected."""
    client = MockClobOrderClient()
    client.set_orderbook(_book(best_ask=0.50))
    with pytest.raises(PostOnlyRejected) as exc:
        await client.place_maker_limit(
            token_id="t1", price=0.50, size_shares=20.0, tick_size="0.01"
        )
    assert exc.value.error_code == "INVALID_POST_ONLY_ORDER"
    assert client.n_post_only_rejections == 1
    assert client.open_orders_count() == 0


async def test_mock_rejects_below_min_size() -> None:
    client = MockClobOrderClient()
    client.set_orderbook(_book())
    with pytest.raises(OrderSizeViolation) as exc:
        await client.place_maker_limit(token_id="t1", price=0.45, size_shares=1.0, tick_size="0.01")
    assert exc.value.error_code == "INVALID_ORDER_MIN_SIZE"


async def test_mock_rejects_misaligned_tick() -> None:
    """Tick is 0.01; price 0.453 is between ticks → OrderTickViolation."""
    client = MockClobOrderClient()
    client.set_orderbook(_book())
    with pytest.raises(OrderTickViolation) as exc:
        await client.place_maker_limit(
            token_id="t1", price=0.453, size_shares=20.0, tick_size="0.01"
        )
    assert exc.value.error_code == "INVALID_ORDER_MIN_TICK_SIZE"


async def test_mock_cancel_removes_order() -> None:
    client = MockClobOrderClient()
    client.set_orderbook(_book())
    result = await client.place_maker_limit(
        token_id="t1", price=0.45, size_shares=20.0, tick_size="0.01"
    )
    assert client.has_open_order(result.order_id)
    cancel = await client.cancel(result.order_id)
    assert cancel.cancelled is True
    assert not client.has_open_order(result.order_id)


async def test_mock_cancel_unknown_returns_false() -> None:
    client = MockClobOrderClient()
    client.set_orderbook(_book())
    cancel = await client.cancel("nonexistent")
    assert cancel.cancelled is False


async def test_mock_cancel_all_drops_everything() -> None:
    client = MockClobOrderClient()
    client.set_orderbook(_book(token_id="t1", best_ask=0.50))
    client.set_orderbook(_book(token_id="t2", best_ask=0.60))
    await client.place_maker_limit(token_id="t1", price=0.45, size_shares=20.0, tick_size="0.01")
    await client.place_maker_limit(token_id="t2", price=0.55, size_shares=20.0, tick_size="0.01")
    assert client.open_orders_count() == 2
    n = await client.cancel_all()
    assert n == 2
    assert client.open_orders_count() == 0


async def test_mock_heartbeat_rotates_id() -> None:
    client = MockClobOrderClient()
    h1 = await client.post_heartbeat("")
    h2 = await client.post_heartbeat(h1)
    assert h1 != h2
    assert client.heartbeat_id_counter == 2


async def test_mock_get_orderbook_returns_seeded_book() -> None:
    client = MockClobOrderClient()
    book = _book(token_id="t1", best_ask=0.42)
    client.set_orderbook(book)
    fetched = await client.get_orderbook("t1")
    assert fetched is not None
    assert fetched.best_ask == 0.42
    assert fetched.best_bid == pytest.approx(0.40)


async def test_mock_get_orderbook_returns_none_for_unseeded() -> None:
    client = MockClobOrderClient()
    assert await client.get_orderbook("unknown") is None


async def test_mock_no_book_raises_on_place() -> None:
    client = MockClobOrderClient()
    with pytest.raises(ClobOrderError) as exc:
        await client.place_maker_limit(
            token_id="missing", price=0.5, size_shares=20.0, tick_size="0.01"
        )
    assert exc.value.error_code == "MOCK_NO_BOOK"


async def test_mock_inject_error_for_test() -> None:
    """Tests can opt to raise a specific error on the next place call."""
    client = MockClobOrderClient()
    client.set_orderbook(_book())
    client.raise_on_next_place = OrderSizeViolation
    with pytest.raises(OrderSizeViolation):
        await client.place_maker_limit(
            token_id="t1", price=0.45, size_shares=20.0, tick_size="0.01"
        )
    # One-shot — next call works
    result = await client.place_maker_limit(
        token_id="t1", price=0.45, size_shares=20.0, tick_size="0.01"
    )
    assert result.status == OrderStatus.LIVE

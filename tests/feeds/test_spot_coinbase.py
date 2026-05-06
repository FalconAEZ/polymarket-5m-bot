"""Tests for polymarket_bot._live.feeds.spot_coinbase.CoinbaseMatchFeed.

Drive the feed against FakeConnect (no network) and exercise: subscribe
payload sent on connect, type filtering (skip 'subscriptions' confirmations
and 'heartbeat'), ISO-8601 time parse to ns, reconnect on exception. Per
anti-vibe rule #6 these run cleanly with networking disabled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from polymarket_bot._live.feeds.spot_coinbase import (
    SUBSCRIBE_PAYLOAD,
    CoinbaseMatchFeed,
)
from polymarket_bot.feeds.protocols import Record
from tests.feeds.conftest import FakeConnect, collect_until_stop, no_sleep


def _match_msg(trade_id: int, price: str, when_iso: str) -> str:
    return json.dumps(
        {
            "type": "match",
            "trade_id": trade_id,
            "maker_order_id": "00000000-0000-0000-0000-000000000001",
            "taker_order_id": "00000000-0000-0000-0000-000000000002",
            "side": "buy",
            "size": "0.001",
            "price": price,
            "product_id": "BTC-USD",
            "sequence": 100 + trade_id,
            "time": when_iso,
        },
        separators=(",", ":"),
    )


def _subscriptions_ack() -> str:
    return json.dumps(
        {"type": "subscriptions", "channels": [{"name": "matches", "product_ids": ["BTC-USD"]}]},
        separators=(",", ":"),
    )


async def test_subscribe_payload_is_sent_on_connect() -> None:
    fake = FakeConnect(scenes=[[]])
    feed = CoinbaseMatchFeed(connect_fn=fake, sleep=no_sleep)

    await collect_until_stop(feed.stream(), max_records=1, timeout_s=0.5)
    feed.stop()

    assert len(fake.clients) >= 1
    assert fake.clients[0].sent == [SUBSCRIBE_PAYLOAD]


async def test_skips_subscriptions_ack_but_emits_match() -> None:
    msg = _match_msg(1, "61234.50", "2026-05-08T12:34:56.789012Z")
    scene = [_subscriptions_ack(), msg]
    fake = FakeConnect(scenes=[scene])
    feed = CoinbaseMatchFeed(connect_fn=fake, clock_ns=lambda: 42, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, Record)
    assert rec.source == "coinbase"
    assert rec.kind == "match"
    assert rec.received_at_ns == 42
    expected_ns = int(
        datetime(2026, 5, 8, 12, 34, 56, 789012, tzinfo=UTC).timestamp() * 1_000_000_000
    )
    assert rec.ts_utc_ns == expected_ns
    # msgs_seen counts everything that arrives, even the skipped ack.
    assert feed.health["msgs_seen"] == 2


async def test_skips_heartbeat_but_emits_match() -> None:
    heartbeat = json.dumps({"type": "heartbeat", "sequence": 99}, separators=(",", ":"))
    match = _match_msg(2, "60000", "2026-05-08T00:00:00Z")
    fake = FakeConnect(scenes=[[heartbeat, match]])
    feed = CoinbaseMatchFeed(connect_fn=fake, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].kind == "match"


async def test_reconnects_after_exception_and_re_sends_subscribe() -> None:
    err = TimeoutError("ws idle")
    match = _match_msg(3, "60000", "2026-05-08T00:00:01Z")
    fake = FakeConnect(scenes=[[err], [match]])
    feed = CoinbaseMatchFeed(connect_fn=fake, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert feed.health["reconnects"] == 1
    assert "TimeoutError" in feed.health["last_error"]
    # Both clients should have received the subscribe payload.
    assert len(fake.clients) == 2
    assert fake.clients[0].sent == [SUBSCRIBE_PAYLOAD]
    assert fake.clients[1].sent == [SUBSCRIBE_PAYLOAD]


async def test_falls_back_when_time_field_unparsable() -> None:
    bad_msg = json.dumps(
        {"type": "match", "trade_id": 1, "price": "1", "size": "1", "time": "not-a-date"},
        separators=(",", ":"),
    )
    fake = FakeConnect(scenes=[[bad_msg]])
    feed = CoinbaseMatchFeed(connect_fn=fake, clock_ns=lambda: 7777, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].ts_utc_ns == 7777
    assert records[0].received_at_ns == 7777

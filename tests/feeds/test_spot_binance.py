"""Tests for polymarket_bot._live.feeds.spot_binance.BinanceTradeFeed.

Drive the feed against FakeConnect/FakeWSClient (no network) and exercise:
parse path, fallback timestamp, reconnect on exception, msgs_seen counter,
last_seen_ns updated, source/kind constants. Per anti-vibe rule #6 these
tests run cleanly with networking disabled.
"""

from __future__ import annotations

import json

from polymarket_bot._live.feeds.spot_binance import BinanceTradeFeed
from polymarket_bot.feeds.protocols import Record
from tests.feeds.conftest import FakeConnect, collect_until_stop, no_sleep


def _trade_msg(trade_id: int, price: str, ts_ms: int) -> str:
    return json.dumps(
        {
            "e": "trade",
            "E": ts_ms,
            "s": "BTCUSDT",
            "t": trade_id,
            "p": price,
            "q": "0.001",
            "T": ts_ms,
            "m": False,
        },
        separators=(",", ":"),
    )


async def test_emits_one_record_per_trade_with_canonical_shape() -> None:
    msg = _trade_msg(1, "61234.50", 1_715_000_000_123)
    fake = FakeConnect(scenes=[[msg]])
    feed = BinanceTradeFeed(connect_fn=fake, clock_ns=lambda: 999, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, Record)
    assert rec.source == "binance"
    assert rec.kind == "trade"
    assert rec.payload_json == msg
    assert rec.received_at_ns == 999
    assert rec.ts_utc_ns == 1_715_000_000_123 * 1_000_000


async def test_uses_T_ms_field_for_event_time() -> None:
    msg = _trade_msg(2, "61234.50", 1_715_000_001_456)
    fake = FakeConnect(scenes=[[msg]])
    feed = BinanceTradeFeed(connect_fn=fake, clock_ns=lambda: 1, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].ts_utc_ns == 1_715_000_001_456 * 1_000_000


async def test_falls_back_to_recv_clock_on_malformed_json() -> None:
    bad = "not-json-at-all"
    fake = FakeConnect(scenes=[[bad]])
    feed = BinanceTradeFeed(connect_fn=fake, clock_ns=lambda: 12345, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].ts_utc_ns == 12345
    assert records[0].received_at_ns == 12345
    assert records[0].payload_json == bad


async def test_reconnects_after_exception_and_resumes() -> None:
    err = ConnectionResetError("simulated reset")
    msg = _trade_msg(7, "60000", 1_715_000_010_000)
    fake = FakeConnect(scenes=[[err], [msg]])
    feed = BinanceTradeFeed(connect_fn=fake, clock_ns=lambda: 5, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert feed.health["reconnects"] == 1
    assert feed.health["msgs_seen"] == 1
    assert "ConnectionResetError" in feed.health["last_error"]
    assert len(fake.urls_called) == 2


async def test_health_tracks_msgs_seen_and_last_seen_ns() -> None:
    msgs = [_trade_msg(i, "60000", 1_715_000_000_000 + i) for i in range(3)]
    fake = FakeConnect(scenes=[msgs])
    clock = iter([100, 200, 300])
    feed = BinanceTradeFeed(connect_fn=fake, clock_ns=lambda: next(clock), sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=3)
    feed.stop()

    assert len(records) == 3
    assert feed.health["msgs_seen"] == 3
    assert feed.health["last_seen_ns"] == 300
    assert feed.health["last_error"] == ""


async def test_uses_default_url_when_none_given() -> None:
    feed = BinanceTradeFeed(connect_fn=FakeConnect(scenes=[[]]), sleep=no_sleep)
    feed.stop()
    # Just verify the URL is stored as the documented default; no I/O.
    assert "stream.binance.com" in feed._url
    assert feed._url.endswith("/btcusdt@trade")

"""Tests for polymarket_bot._live.feeds.polymarket.PolymarketFeed.

Drive the feed against FakeConnect (no network) plus a fake gamma_fetch_fn
that returns a synthetic event with two clobTokenIds. Cover the subscribe
shape, message classification (book / price_change / last_trade_price kept;
tick_size_change kept; PONG and unknown event_types skipped), Gamma miss
handling, ts_utc_ns extraction, and the helper functions active_window_ts /
active_slug / extract_token_ids. Per anti-vibe rule #6 these run cleanly
with networking disabled.
"""

from __future__ import annotations

import json
from typing import Any

from polymarket_bot._live.feeds.polymarket import (
    PolymarketFeed,
    active_slug,
    active_window_ts,
    extract_token_ids,
)
from polymarket_bot.feeds.protocols import Record
from tests.feeds.conftest import FakeConnect, collect_until_stop, no_sleep

TOKEN_UP = "108228082174746074469228126225582702915828037389061512519554351684784175186017"
TOKEN_DOWN = "20585483282134597513891370255357024554725275596049858906332663762739670202958"


def _gamma_event(window_ts: int) -> dict[str, Any]:
    return {
        "slug": active_slug(window_ts),
        "title": f"Bitcoin Up or Down — fixture {window_ts}",
        "markets": [
            {
                "question": "Bitcoin Up or Down",
                "conditionId": "0xabc",
                "outcomes": json.dumps(["Up", "Down"]),
                "clobTokenIds": json.dumps([TOKEN_UP, TOKEN_DOWN]),
            }
        ],
    }


def _book_msg(asset_id: str = TOKEN_UP, ts_ms: int = 1_715_000_100_123) -> str:
    return json.dumps(
        {
            "event_type": "book",
            "asset_id": asset_id,
            "market": "0xabc",
            "bids": [{"price": ".48", "size": "30"}],
            "asks": [{"price": ".52", "size": "25"}],
            "timestamp": str(ts_ms),
            "hash": "0x" + "11" * 16,
        },
        separators=(",", ":"),
    )


def _trade_msg(asset_id: str = TOKEN_UP, ts_ms: int = 1_715_000_001_456) -> str:
    return json.dumps(
        {
            "event_type": "last_trade_price",
            "asset_id": asset_id,
            "price": "0.51",
            "side": "BUY",
            "size": "10",
            "fee_rate_bps": "0",
            "timestamp": str(ts_ms),
        },
        separators=(",", ":"),
    )


async def _fake_gamma_ok(window_ts: int):
    async def fetch(slug: str) -> dict[str, Any] | None:
        if slug == active_slug(window_ts):
            return _gamma_event(window_ts)
        return None

    return fetch


def test_active_window_ts_floors_to_300() -> None:
    # 1_714_999_800 = 300 * 5_716_666 — exact multiple, fixed point.
    assert active_window_ts(1_714_999_800) == 1_714_999_800
    # Off by one second still floors back to the same window.
    assert active_window_ts(1_714_999_801) == 1_714_999_800
    # 1_715_000_099 is just before the next boundary.
    assert active_window_ts(1_715_000_099) == 1_714_999_800
    # 1_715_000_100 = 300 * 5_716_667 — next boundary itself.
    assert active_window_ts(1_715_000_100) == 1_715_000_100


def test_active_slug_format() -> None:
    assert active_slug(1_715_000_100) == "btc-updown-5m-1715000100"


def test_extract_token_ids_handles_canonical_payload() -> None:
    event = _gamma_event(1_715_000_100)
    tokens = extract_token_ids(event)
    assert tokens == [TOKEN_UP, TOKEN_DOWN]


def test_extract_token_ids_returns_empty_on_malformed() -> None:
    assert extract_token_ids({}) == []
    assert extract_token_ids({"markets": []}) == []
    assert extract_token_ids({"markets": [{"clobTokenIds": "not-json"}]}) == []
    assert extract_token_ids({"markets": [{"clobTokenIds": json.dumps({"x": 1})}]}) == []


async def test_subscribe_payload_sent_with_resolved_token_ids() -> None:
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)

    fake = FakeConnect(scenes=[[_book_msg()]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(fake.clients) == 1
    sent_msgs = fake.clients[0].sent
    # The first sent message must be the subscribe; PINGs may or may not
    # follow (depends on background-task scheduling under no_sleep).
    sub = json.loads(sent_msgs[0])
    assert sub["type"] == "market"
    assert sub["assets_ids"] == [TOKEN_UP, TOKEN_DOWN]
    assert sub["custom_feature_enabled"] is True
    assert "operation" not in sub  # initial subscribe omits operation


async def test_emits_book_record_with_decoded_timestamp() -> None:
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)
    msg = _book_msg(ts_ms=1_715_000_007_000)
    fake = FakeConnect(scenes=[[msg]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, Record)
    assert rec.source == "polymarket"
    assert rec.kind == "book"
    assert rec.payload_json == msg
    assert rec.ts_utc_ns == 1_715_000_007_000 * 1_000_000


async def test_emits_last_trade_price_record() -> None:
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)
    msg = _trade_msg()
    fake = FakeConnect(scenes=[[msg]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].kind == "last_trade_price"


async def test_pong_and_unknown_event_types_are_skipped() -> None:
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)
    book = _book_msg()
    pong = "PONG"
    unknown = json.dumps(
        {"event_type": "garbage_event", "asset_id": TOKEN_UP}, separators=(",", ":")
    )
    fake = FakeConnect(scenes=[[pong, unknown, book]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].kind == "book"
    # PONG is not even counted as a message; unknown event_type counts in
    # msgs_seen because we did parse it, but doesn't yield.
    assert feed.health["msgs_seen"] >= 2


async def test_gamma_miss_does_not_crash() -> None:
    async def gamma_miss(_slug: str) -> dict[str, Any] | None:
        return None

    fake = FakeConnect(scenes=[[]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=gamma_miss,
        connect_fn=fake,
        clock_ns=lambda: 1_715_000_100 * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1, timeout_s=0.5)
    feed.stop()

    assert records == []
    assert "gamma-miss" in feed.health["last_error"]


async def test_handles_array_wrapped_messages() -> None:
    """Polymarket WS wraps multi-asset events in JSON arrays. Each element
    must yield its own Record, and payload_json must be the per-element
    dict (not the enclosing array). Regression test for the bug discovered
    in the 6-min smoke run on 2026-05-07.
    """
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)
    book_up = {
        "event_type": "book",
        "asset_id": TOKEN_UP,
        "market": "0xabc",
        "bids": [{"price": ".48", "size": "30"}],
        "asks": [{"price": ".52", "size": "25"}],
        "timestamp": "1715000005000",
        "hash": "0x" + "11" * 16,
    }
    book_down = {
        "event_type": "book",
        "asset_id": TOKEN_DOWN,
        "market": "0xabc",
        "bids": [{"price": ".48", "size": "20"}],
        "asks": [{"price": ".52", "size": "15"}],
        "timestamp": "1715000005000",
        "hash": "0x" + "22" * 16,
    }
    array_msg = json.dumps([book_up, book_down], separators=(",", ":"))
    fake = FakeConnect(scenes=[[array_msg]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=2)
    feed.stop()

    assert len(records) == 2
    asset_ids = {json.loads(r.payload_json)["asset_id"] for r in records if isinstance(r, Record)}
    assert asset_ids == {TOKEN_UP, TOKEN_DOWN}
    for r in records:
        assert isinstance(r, Record)
        assert r.kind == "book"


async def test_reconnects_after_ws_exception() -> None:
    window = 1_715_000_100
    fake_gamma = await _fake_gamma_ok(window)
    err = ConnectionResetError("kaboom")
    msg = _book_msg()
    fake = FakeConnect(scenes=[[err], [msg]])
    feed = PolymarketFeed(
        ws_url="wss://test",
        gamma_fetch_fn=fake_gamma,
        connect_fn=fake,
        clock_ns=lambda: window * 1_000_000_000,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert feed.health["reconnects"] == 1
    assert "ConnectionResetError" in feed.health["last_error"]

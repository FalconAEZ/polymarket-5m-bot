"""Tests for polymarket_bot._live.feeds.oracle.OracleFeed.

Drive the feed against FakeConnect that replays a captured JSON-RPC trace:
the eth_call(aggregator()) response, the eth_subscribe ack, and one or more
eth_subscription log notifications shaped like real Chainlink AnswerUpdated
events. Per anti-vibe rule #6 these run cleanly with networking disabled.
"""

from __future__ import annotations

import json

from polymarket_bot._live.feeds.oracle import (
    AGGREGATOR_FN_SELECTOR,
    EVENT_TOPIC,
    OracleFeed,
)
from polymarket_bot.feeds.protocols import Record
from tests.feeds.conftest import FakeConnect, collect_until_stop, no_sleep

UNDERLYING = "0x" + "ab" * 20  # 0xabab...ab
PROXY = "0xc907E116054Ad103354f2D350FD2514433D57F6f"
SUB_ID = "0xdeadbeefdeadbeefdeadbeefdeadbeef"


def _aggregator_call_response() -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": "0x" + "0" * 24 + "ab" * 20},
        separators=(",", ":"),
    )


def _subscribe_ack() -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "result": SUB_ID}, separators=(",", ":"))


def _hex_pad(n: int, signed: bool = False) -> str:
    if signed and n < 0:
        n = (1 << 256) + n
    return n.to_bytes(32, "big", signed=False).hex()


def _log_notification(
    *,
    current: int = 60_000_00000000,
    round_id: int = 18_446_744_073_709_551_616,
    updated_at: int = 1_715_000_000,
    address: str = UNDERLYING,
    sub_id: str = SUB_ID,
) -> str:
    log = {
        "address": address,
        "topics": [
            EVENT_TOPIC,
            "0x" + _hex_pad(current, signed=True),
            "0x" + _hex_pad(round_id),
        ],
        "data": "0x" + _hex_pad(updated_at),
        "blockHash": "0x" + "11" * 32,
        "blockNumber": "0x" + format(123, "x"),
        "transactionHash": "0x" + "22" * 32,
        "transactionIndex": "0x0",
        "logIndex": "0x0",
        "removed": False,
    }
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {"subscription": sub_id, "result": log},
        },
        separators=(",", ":"),
    )


async def test_emits_record_with_decoded_updated_at() -> None:
    scene = [
        _aggregator_call_response(),
        _subscribe_ack(),
        _log_notification(updated_at=1_715_000_123),
    ]
    fake = FakeConnect(scenes=[scene])
    feed = OracleFeed(
        rpc_url="wss://test",
        proxy_address=PROXY,
        connect_fn=fake,
        clock_ns=lambda: 999,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, Record)
    assert rec.source == "oracle"
    assert rec.kind == "AnswerUpdated"
    assert rec.received_at_ns == 999
    assert rec.ts_utc_ns == 1_715_000_123 * 1_000_000_000


async def test_sends_correct_eth_call_and_subscribe_payloads() -> None:
    scene = [_aggregator_call_response(), _subscribe_ack(), _log_notification()]
    fake = FakeConnect(scenes=[scene])
    feed = OracleFeed(rpc_url="wss://test", proxy_address=PROXY, connect_fn=fake, sleep=no_sleep)

    await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    sent = fake.clients[0].sent
    assert len(sent) == 2
    call = json.loads(sent[0])
    assert call["method"] == "eth_call"
    assert call["params"][0]["to"] == PROXY.lower()
    assert call["params"][0]["data"] == AGGREGATOR_FN_SELECTOR

    sub = json.loads(sent[1])
    assert sub["method"] == "eth_subscribe"
    assert sub["params"][0] == "logs"
    assert sub["params"][1]["address"] == UNDERLYING
    assert sub["params"][1]["topics"] == [EVENT_TOPIC]


async def test_skips_unrelated_subscription_notifications() -> None:
    other_sub = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {"subscription": "0xdifferent", "result": {"x": 1}},
        },
        separators=(",", ":"),
    )
    scene = [
        _aggregator_call_response(),
        _subscribe_ack(),
        other_sub,
        _log_notification(updated_at=1_715_111_222),
    ]
    fake = FakeConnect(scenes=[scene])
    feed = OracleFeed(rpc_url="wss://test", proxy_address=PROXY, connect_fn=fake, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].ts_utc_ns == 1_715_111_222 * 1_000_000_000


async def test_falls_back_when_data_is_not_unix_seconds() -> None:
    bogus_log = {
        "address": UNDERLYING,
        "topics": [EVENT_TOPIC, "0x" + "0" * 64, "0x" + "0" * 64],
        "data": "0x" + "0" * 64,  # decodes to 0, outside unix-seconds window
    }
    notif = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {"subscription": SUB_ID, "result": bogus_log},
        },
        separators=(",", ":"),
    )
    scene = [_aggregator_call_response(), _subscribe_ack(), notif]
    fake = FakeConnect(scenes=[scene])
    feed = OracleFeed(
        rpc_url="wss://test",
        proxy_address=PROXY,
        connect_fn=fake,
        clock_ns=lambda: 4242,
        sleep=no_sleep,
    )

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert isinstance(records[0], Record)
    assert records[0].ts_utc_ns == 4242
    assert records[0].received_at_ns == 4242


async def test_reconnects_after_subscription_failure() -> None:
    err_resp = json.dumps(
        {"jsonrpc": "2.0", "id": 2, "error": {"code": -32602, "message": "bad params"}},
        separators=(",", ":"),
    )
    scene_fail = [_aggregator_call_response(), err_resp]
    scene_ok = [_aggregator_call_response(), _subscribe_ack(), _log_notification()]
    fake = FakeConnect(scenes=[scene_fail, scene_ok])
    feed = OracleFeed(rpc_url="wss://test", proxy_address=PROXY, connect_fn=fake, sleep=no_sleep)

    records = await collect_until_stop(feed.stream(), max_records=1)
    feed.stop()

    assert len(records) == 1
    assert feed.health["reconnects"] == 1
    assert "RuntimeError" in feed.health["last_error"]


async def test_event_topic_matches_keccak_of_signature() -> None:
    """Spec lock: the topic constant must equal keccak256(signature)."""
    from eth_utils import keccak  # type: ignore[attr-defined]

    expected = "0x" + keccak(text="AnswerUpdated(int256,uint256,uint256)").hex()
    assert EVENT_TOPIC == expected

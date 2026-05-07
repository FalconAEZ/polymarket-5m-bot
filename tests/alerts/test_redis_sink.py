"""RedisAlertSink: LPUSH JSON, never raise on Redis errors."""

from __future__ import annotations

import json

from polymarket_bot.alerts import Alert, Level, RedisAlertSink
from tests._fakes.fake_redis import FakeRedisStore, FakeSyncRedis


def test_publish_lpushes_json() -> None:
    store = FakeRedisStore()
    fake = FakeSyncRedis(store)
    sink = RedisAlertSink(url="redis://ignored", queue_key="polybot:alerts", client=fake)
    a = Alert(
        level=Level.WARN,
        message="feed reconnect",
        ts_ns=12345,
        source="bot-staging",
        fields={"feed": "binance"},
    )
    sink.publish(a)
    queued = store.lists["polybot:alerts"]
    assert len(queued) == 1
    payload = json.loads(queued[0].decode("utf-8"))
    assert payload == {
        "level": "warn",
        "message": "feed reconnect",
        "ts_ns": 12345,
        "source": "bot-staging",
        "fields": {"feed": "binance"},
    }


def test_publish_swallows_connection_error() -> None:
    store = FakeRedisStore()
    fake = FakeSyncRedis(store)
    store.fail_next(1)
    sink = RedisAlertSink(url="redis://ignored", queue_key="polybot:alerts", client=fake)
    # Must not raise.
    sink.publish(Alert(level=Level.ERROR, message="boom", ts_ns=1, source="t"))
    # Nothing was pushed because lpush failed.
    assert len(store.lists["polybot:alerts"]) == 0


def test_close_does_not_raise_when_client_absent() -> None:
    sink = RedisAlertSink(url="redis://ignored", queue_key="polybot:alerts")
    # No publish() called — client never constructed. close() must be safe.
    sink.close()


def test_close_closes_underlying_client() -> None:
    store = FakeRedisStore()
    fake = FakeSyncRedis(store)
    sink = RedisAlertSink(url="redis://ignored", client=fake)
    sink.publish(Alert(level=Level.INFO, message="x", ts_ns=0, source="t"))
    sink.close()
    assert fake.closed is True

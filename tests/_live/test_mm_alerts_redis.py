"""Tests for the push_to_redis_alerter helper in mm_alerts.

Verifies the best-effort posture: any Redis failure (import-error,
connection-error, serialization-error) MUST be swallowed without
raising back to the caller. The on-disk halt sentinel is the
authoritative safety signal — alerting is observability sugar.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from polymarket_bot._live.mm_alerts import push_to_redis_alerter


async def test_push_swallows_redis_import_error(caplog: pytest.LogCaptureFixture) -> None:
    """If redis-py is somehow not installed, the helper logs + returns
    cleanly without raising."""
    # Simulate import failure by removing redis from sys.modules + adding
    # a sentinel that raises on import.
    saved = sys.modules.pop("redis.asyncio", None)
    sys.modules["redis.asyncio"] = None  # type: ignore[assignment]
    try:
        with caplog.at_level("ERROR"):
            await push_to_redis_alerter({"level": "warn", "source": "mm-bot", "message": "test"})
        # Should have logged but not raised.
        assert any("redis-py not installed" in rec.message for rec in caplog.records)
    finally:
        if saved is not None:
            sys.modules["redis.asyncio"] = saved
        else:
            sys.modules.pop("redis.asyncio", None)


async def test_push_swallows_redis_connection_error(caplog: pytest.LogCaptureFixture) -> None:
    """Connection failure → log + swallow."""

    class _FakeRedis:
        @classmethod
        def from_url(cls, _url: str) -> _FakeRedis:
            return cls()

        async def lpush(self, _key: str, _value: str) -> int:
            raise ConnectionError("redis unreachable")

        async def aclose(self) -> None:
            pass

    fake_module = MagicMock()
    fake_module.Redis = _FakeRedis
    with patch.dict(sys.modules, {"redis.asyncio": fake_module}):
        with caplog.at_level("ERROR"):
            await push_to_redis_alerter({"level": "warn", "source": "mm-bot", "message": "test"})
        assert any("MMB alert push failed" in rec.message for rec in caplog.records)


async def test_push_happy_path_calls_lpush() -> None:
    """When Redis is healthy, lpush is called once with the queue key + JSON payload."""
    captured: dict[str, Any] = {}

    class _FakeRedis:
        @classmethod
        def from_url(cls, _url: str) -> _FakeRedis:
            return cls()

        async def lpush(self, key: str, value: str) -> int:
            captured["key"] = key
            captured["value"] = value
            return 1

        async def aclose(self) -> None:
            captured["closed"] = True

    fake_module = MagicMock()
    fake_module.Redis = _FakeRedis
    payload = {"level": "critical", "source": "mm-bot", "message": "heartbeat failed"}
    with patch.dict(sys.modules, {"redis.asyncio": fake_module}):
        await push_to_redis_alerter(payload)
    assert captured["key"] == "polybot:alerts"
    assert '"level": "critical"' in captured["value"]
    assert captured.get("closed") is True

"""RedisQueueImpl: TimeoutError is "no entry yet", not a connection error.

Regression test for the smoke-time bug at 2026-05-07T19:23 UTC: redis-py's
`TimeoutError` (raised when no message arrives within the socket-read
deadline) was being caught by the generic RedisError branch, triggering an
unnecessary reconnect + 0.5s backoff and a noisy WARN line every BRPOP
cycle. Correct behavior: bubble up as `None` so the drain loop just calls
brpop again on its next tick.
"""

from __future__ import annotations

from typing import Any

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from polymarket_bot._live.alerter.redis_queue import RedisQueueImpl


class _StubClient:
    def __init__(self, behavior: list[Any]) -> None:
        self._behavior = list(behavior)

    def brpop(self, keys: list[str], timeout: int) -> Any:
        nxt = self._behavior.pop(0)

        async def _coro() -> Any:
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        return _coro()

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_brpop_returns_none_on_redis_timeout_error() -> None:
    client = _StubClient([RedisTimeoutError("Timeout reading from 127.0.0.1:6379")])
    q = RedisQueueImpl(url="redis://ignored", client=client)  # type: ignore[arg-type]
    assert await q.brpop(timeout=30.0) is None
    # Backoff must NOT have been ratcheted — this isn't a connection error.
    assert q._backoff_s == 0.5


@pytest.mark.asyncio
async def test_brpop_returns_value_on_hit() -> None:
    client = _StubClient([(b"polybot:alerts", b'{"level":"warn","message":"x"}')])
    q = RedisQueueImpl(url="redis://ignored", client=client)  # type: ignore[arg-type]
    out = await q.brpop(timeout=30.0)
    assert out == b'{"level":"warn","message":"x"}'


@pytest.mark.asyncio
async def test_brpop_returns_none_on_server_timeout() -> None:
    client = _StubClient([None])
    q = RedisQueueImpl(url="redis://ignored", client=client)  # type: ignore[arg-type]
    assert await q.brpop(timeout=30.0) is None

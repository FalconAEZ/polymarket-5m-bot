"""Tiny in-memory Redis double — only the surface our code uses.

We never depend on a running Redis in unit tests. The two surfaces this fake
must cover are: the sync `Redis` client used by RedisAlertSink (lpush, close,
ping), and the async `redis.asyncio.Redis` client used by RedisQueue (brpop,
lpush, llen, aclose). Both are scoped to a shared in-process dict-of-list
keyed by Redis key name. `mode="raise"` toggles connection-error simulation.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Iterable


class _FakeRedisError(Exception):
    """Stand-in for redis.exceptions.ConnectionError in tests."""


class FakeRedisStore:
    """In-memory key→deque store. Shared between sync + async fake clients."""

    def __init__(self) -> None:
        self.lists: dict[str, deque[bytes]] = defaultdict(deque)
        self.fail_next_n: int = 0

    def fail_next(self, n: int = 1) -> None:
        self.fail_next_n = n

    def _maybe_fail(self) -> None:
        if self.fail_next_n > 0:
            self.fail_next_n -= 1
            raise _FakeRedisError("simulated connection error")

    def lpush(self, key: str, *values: str | bytes) -> int:
        self._maybe_fail()
        dq = self.lists[key]
        for v in values:
            data = v.encode("utf-8") if isinstance(v, str) else v
            dq.appendleft(data)
        return len(dq)

    def rpush(self, key: str, *values: str | bytes) -> int:
        self._maybe_fail()
        dq = self.lists[key]
        for v in values:
            data = v.encode("utf-8") if isinstance(v, str) else v
            dq.append(data)
        return len(dq)

    def brpop_nowait(self, keys: Iterable[str]) -> tuple[bytes, bytes] | None:
        self._maybe_fail()
        for k in keys:
            dq = self.lists[k]
            if dq:
                return (k.encode("utf-8"), dq.pop())
        return None

    def llen(self, key: str) -> int:
        self._maybe_fail()
        return len(self.lists[key])


class FakeSyncRedis:
    """Sync surface used by RedisAlertSink."""

    def __init__(self, store: FakeRedisStore) -> None:
        self._store = store
        self.closed = False

    def lpush(self, key: str, value: str | bytes) -> int:
        return self._store.lpush(key, value)

    def ping(self) -> bool:
        self._store._maybe_fail()
        return True

    def close(self) -> None:
        self.closed = True


class FakeAsyncRedis:
    """Async surface used by RedisQueue (brpop loop)."""

    def __init__(self, store: FakeRedisStore) -> None:
        self._store = store
        self.closed = False

    async def brpop(
        self,
        keys: list[str],
        timeout: float = 0,  # noqa: ASYNC109
    ) -> tuple[bytes, bytes] | None:
        # Poll the in-memory store with a short sleep, mirroring blocking BRPOP.
        deadline = None if timeout == 0 else asyncio.get_event_loop().time() + timeout
        while True:
            try:
                hit = self._store.brpop_nowait(keys)
            except _FakeRedisError:
                raise
            if hit is not None:
                return hit
            if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.005)

    async def lpush(self, key: str, *values: str | bytes) -> int:
        return self._store.lpush(key, *values)

    async def llen(self, key: str) -> int:
        return self._store.llen(key)

    async def aclose(self) -> None:
        self.closed = True

    async def ping(self) -> bool:
        self._store._maybe_fail()
        return True


def connection_error_class() -> type[Exception]:
    return _FakeRedisError


__all__ = [
    "FakeAsyncRedis",
    "FakeRedisStore",
    "FakeSyncRedis",
    "connection_error_class",
]

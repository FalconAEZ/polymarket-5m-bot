"""Async Redis BRPOP wrapper with exponential backoff reconnect.

design/alerter.md §5.4 + §7: the consumer connects to a single Redis at
localhost:6379 and BRPOPs `polybot:alerts`. Connection-error exceptions trigger
exponential backoff (capped at 30s) and a reconnect; messages published while
Redis is down are lost (acceptable per "publish must not block trading").
DLQ pushes (`polybot:alerts:dlq`) are bounded via LTRIM to 1000 entries so a
prolonged Telegram outage cannot exhaust memory.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis as _AsyncRedisClient

LOG = logging.getLogger("polymarket_bot._live.alerter.redis_queue")

DEFAULT_QUEUE_KEY = "polybot:alerts"
DEFAULT_DLQ_KEY = "polybot:alerts:dlq"
DLQ_MAX_ENTRIES = 1000
BACKOFF_INITIAL_S = 0.5
BACKOFF_CAP_S = 30.0


class RedisQueueImpl:
    """Production async wrapper around redis.asyncio.Redis."""

    def __init__(
        self,
        *,
        url: str,
        queue_key: str = DEFAULT_QUEUE_KEY,
        dlq_key: str = DEFAULT_DLQ_KEY,
        client: _AsyncRedisClient | None = None,
    ) -> None:
        self._url = url
        self._queue_key = queue_key
        self._dlq_key = dlq_key
        self._client: _AsyncRedisClient | None = client
        self._backoff_s = BACKOFF_INITIAL_S

    async def _client_or_connect(self) -> _AsyncRedisClient:
        if self._client is not None:
            return self._client
        from redis.asyncio import Redis

        # No socket_timeout on BRPOP path — redis-py treats socket_timeout
        # as a hard read deadline that fires before BRPOP's server-side
        # timeout when the queue is idle, raising TimeoutError instead of
        # returning None. Health-check pings keep the connection alive.
        self._client = Redis.from_url(self._url, health_check_interval=30)
        return self._client

    async def brpop(self, timeout: float) -> bytes | None:  # noqa: ASYNC109
        """BRPOP one entry; on connection error, sleep + retry forever.

        Returns `None` when the BRPOP times out on the server side without
        finding an entry — the outer drain loop calls brpop again on its
        next tick. A redis-py `TimeoutError` (idle socket deadline) is also
        treated as "nothing arrived" rather than a connection error, since
        the queue is well-defined empty and reconnect would just rebuild
        the same connection.
        """
        from redis.exceptions import ConnectionError as RedisConnectionError
        from redis.exceptions import RedisError
        from redis.exceptions import TimeoutError as RedisTimeoutError

        while True:
            try:
                client = await self._client_or_connect()
                # redis-py overloads brpop's return; cast through Any.
                raw_call: Any = client.brpop([self._queue_key], timeout=int(timeout))
                hit: Any = await raw_call
                self._backoff_s = BACKOFF_INITIAL_S
                if hit is None:
                    return None
                _key, value = hit
                if isinstance(value, bytes):
                    return value
                return bytes(value)
            except RedisTimeoutError:
                # Idle wait — queue is empty, no entry yet. Caller loops.
                self._backoff_s = BACKOFF_INITIAL_S
                return None
            except (RedisConnectionError, OSError) as exc:
                LOG.warning(
                    "redis brpop connection error: %s; backing off %.1fs",
                    exc,
                    self._backoff_s,
                )
                await self._reconnect_after_backoff()
            except RedisError as exc:
                LOG.warning("redis brpop error: %s; backing off %.1fs", exc, self._backoff_s)
                await self._reconnect_after_backoff()

    async def _reconnect_after_backoff(self) -> None:
        await asyncio.sleep(self._backoff_s)
        self._backoff_s = min(self._backoff_s * 2.0, BACKOFF_CAP_S)
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                LOG.debug("redis aclose during reconnect raised: %s", exc)
        self._client = None

    async def lpush_dlq(self, payload: bytes) -> None:
        from redis.exceptions import RedisError

        try:
            client = await self._client_or_connect()
            push_call: Any = client.lpush(self._dlq_key, payload)
            await push_call
            trim_call: Any = client.ltrim(self._dlq_key, 0, DLQ_MAX_ENTRIES - 1)
            await trim_call
        except (RedisError, OSError) as exc:
            LOG.warning("redis dlq push failed: %s; dropping", exc)

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:
                LOG.debug("redis aclose raised: %s", exc)

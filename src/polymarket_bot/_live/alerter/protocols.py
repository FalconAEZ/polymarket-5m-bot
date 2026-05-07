"""Protocols for the consumer-side alerter daemon (anti-vibe rule #10).

`RedisQueue` and `TelegramClient` are the two stochastic surfaces of the
alerter. Real implementations land in `redis_queue.py` and
`telegram_client.py`; tests inject in-memory fakes. `HaltWriter` is the
sentinel-write callable so tests can substitute a no-op writer that just
records its calls. `ClockNs` matches `polymarket_bot.alerts.protocols.Clock`
but is duplicated locally so the consumer module never depends on the
producer protocols (clean process-local boundary).
"""

from __future__ import annotations

from typing import Any, Protocol


class RedisQueue(Protocol):
    # `timeout` mirrors redis-py's BRPOP signature; we cannot rewrite it as
    # asyncio.timeout (the timeout is sent server-side, not in-process).
    async def brpop(self, timeout: float) -> bytes | None: ...  # noqa: ASYNC109

    async def lpush_dlq(self, payload: bytes) -> None: ...

    async def aclose(self) -> None: ...


class TelegramClient(Protocol):
    async def send_message(self, text: str, *, chat_id: str) -> dict[str, Any]: ...

    # `timeout` mirrors Telegram's getUpdates long-poll parameter (server-side).
    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int,  # noqa: ASYNC109
    ) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


class HaltWriter(Protocol):
    def __call__(self, reason: str, ts_ns: int) -> None: ...


class ClockNs(Protocol):
    def __call__(self) -> int: ...

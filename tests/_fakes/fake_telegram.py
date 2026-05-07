"""In-memory FakeTelegramClient + FakeRedisQueue for alerter unit tests."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import httpx


class FakeTelegramResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeTelegramClient:
    """Drives send_message + get_updates without httpx.

    Behaviors are scriptable via attributes:
      - send_results: deque of either dict (success) or int (status_code) for
        each subsequent send_message call. Default: success ({}).
      - updates_script: deque of list[dict] returned by successive get_updates.
        After exhausting the script, get_updates returns [] forever.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.send_results: deque[dict[str, Any] | int] = deque()
        self.updates_script: deque[list[dict[str, Any]]] = deque()
        self.closed = False

    async def send_message(self, text: str, *, chat_id: str) -> dict[str, Any]:
        self.sent.append((text, chat_id))
        if not self.send_results:
            return {"ok": True}
        result = self.send_results.popleft()
        if isinstance(result, int):
            req = httpx.Request("POST", "http://test/send")
            resp = httpx.Response(status_code=result, request=req)
            raise httpx.HTTPStatusError(f"server error {result}", request=req, response=resp)
        return result

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int,  # noqa: ASYNC109
    ) -> list[dict[str, Any]]:
        if not self.updates_script:
            await asyncio.sleep(0.005)
            return []
        return self.updates_script.popleft()

    async def aclose(self) -> None:
        self.closed = True


class FakeRedisQueue:
    """Async queue stand-in for the alerter's RedisQueue protocol."""

    def __init__(self) -> None:
        self._items: deque[bytes] = deque()
        self.dlq: list[bytes] = []
        self.closed = False

    def enqueue(self, payload: bytes) -> None:
        self._items.append(payload)

    async def brpop(self, timeout: float) -> bytes | None:  # noqa: ASYNC109
        deadline = asyncio.get_event_loop().time() + timeout
        while not self._items:
            if asyncio.get_event_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.005)
        return self._items.popleft()

    async def lpush_dlq(self, payload: bytes) -> None:
        self.dlq.append(payload)

    async def aclose(self) -> None:
        self.closed = True


__all__ = ["FakeRedisQueue", "FakeTelegramClient"]

"""Shared fakes for tests/feeds — FakeWSClient and FakeConnect.

Provides a Protocol-compatible fake WebSocket client whose behavior is
scripted as a list of "scenes" (per connect call). Each scene is either a
list of messages (str) or contains a sentinel Exception that will be raised
mid-iteration. Tests use this to drive feed code without real network and
to exercise the reconnect/backoff/parse paths deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

# Scene = list of items where each item is either:
#   - a str: yielded as a WS message
#   - an Exception instance: raised in place of the next message
SceneItem = str | BaseException
Scene = list[SceneItem]


class FakeWSClient:
    """A scripted async WS client. One scene per __aenter__ call."""

    def __init__(self, scene: Scene) -> None:
        self._scene: Scene = list(scene)
        self.sent: list[str] = []
        self.entered: bool = False
        self.exited: bool = False
        self.closed: bool = False

    async def __aenter__(self) -> FakeWSClient:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        self.exited = True

    def __aiter__(self) -> FakeWSClient:
        return self

    async def __anext__(self) -> str:
        if not self._scene:
            raise StopAsyncIteration
        item = self._scene.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


class FakeConnect:
    """Scripted connect_fn — returns one FakeWSClient per call, drains scenes in order.

    After scenes are exhausted, subsequent connect calls return an empty client
    (immediate StopAsyncIteration). Tracks every URL passed in for assertions.
    """

    def __init__(self, scenes: list[Scene]) -> None:
        self._scenes: list[Scene] = list(scenes)
        self.urls_called: list[str] = []
        self.clients: list[FakeWSClient] = []

    def __call__(self, url: str) -> FakeWSClient:
        self.urls_called.append(url)
        scene: Scene = self._scenes.pop(0) if self._scenes else []
        client = FakeWSClient(scene)
        self.clients.append(client)
        return client


async def no_sleep(_seconds: float) -> None:
    """Drop-in for asyncio.sleep that yields control once and returns immediately."""
    await asyncio.sleep(0)


async def collect_until_stop(
    feed_stream: AsyncIterator[object],
    *,
    max_records: int,
    timeout_s: float = 5.0,
) -> list[object]:
    """Drive an async iterator up to max_records or timeout. Helper for spot tests."""
    out: list[object] = []
    try:
        async with asyncio.timeout(timeout_s):
            async for record in feed_stream:
                out.append(record)
                if len(out) >= max_records:
                    break
    except TimeoutError:
        pass
    return out

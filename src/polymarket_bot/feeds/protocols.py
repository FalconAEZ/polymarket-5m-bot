"""Feed protocol + Record dataclass + WS-client structural types.

Pinned shapes used by every concrete feed in polymarket_bot._live.feeds and by
the Phase-4 paper replays under polymarket_bot._paper.feeds. Record schema is
load-bearing for the Parquet archive and must not drift after the first
captured day; see design/data_plane.md §4 for the full pin.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict


@dataclass(frozen=True, slots=True)
class Record:
    """A single archived event. Five fields total; see design/data_plane.md §4.

    ts_utc_ns is event-time per the upstream (Binance E/T, Coinbase time,
    Chainlink updatedAt, Polymarket timestamp). received_at_ns is our local
    clock at recv() return. payload_json is the raw upstream message,
    json.dumps with separators=(",", ":"), no transformation. The skew
    between the two timestamps is itself a Phase-3 metric.
    """

    ts_utc_ns: int
    received_at_ns: int
    source: str
    kind: str
    payload_json: str


class Health(TypedDict):
    """Per-feed health snapshot — written every message by the feed itself.

    Aggregated every 30s by polymarket_bot._live.health into
    state/feeds_health.json. last_seen_ns is time.time_ns() at the most recent
    successful WS recv(); msgs_seen and reconnects are monotonic counters;
    last_error is the most recent exception classname + truncated message
    (empty string when healthy).
    """

    name: str
    last_seen_ns: int
    msgs_seen: int
    reconnects: int
    last_error: str


class WSClient(Protocol):
    """Minimal WS client surface used by feeds — covers websockets and fakes.

    Real production passes websockets.connect (its yielded connection is
    structurally compatible). Tests pass a FakeWSClient that replays
    recorded payloads with deterministic timing. No real network in unit
    tests per anti-vibe rule #6.
    """

    async def send(self, message: str) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...

    async def close(self) -> None: ...


class WSConnectCtx(Protocol):
    """The async context manager returned by a connect call. Yields a WSClient."""

    async def __aenter__(self) -> WSClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None: ...


WSConnectFn = Callable[[str], WSConnectCtx]
"""Type alias: takes a URI, returns an async context manager yielding a WSClient.

Production binds this to websockets.connect. Tests bind this to a fake.
"""


SleepFn = Callable[[float], Awaitable[None]]
"""Async sleep — asyncio.sleep in production, deterministic stub in tests."""


ClockNs = Callable[[], int]
"""Wall-clock nanoseconds — time.time_ns in production, deterministic in tests."""


class Feed(Protocol):
    """Every concrete feed implements this. See design/data_plane.md §8.

    name is the source value emitted in every Record this feed yields. health
    is a live snapshot dict the runtime aggregator reads each cycle. stream()
    returns an async iterator that yields Records until the connection is
    shut down (via stop() or by the consumer aclose()'ing the generator).
    """

    name: str

    @property
    def health(self) -> Health: ...

    def stop(self) -> None: ...

    def stream(self) -> AsyncIterator[Record]: ...

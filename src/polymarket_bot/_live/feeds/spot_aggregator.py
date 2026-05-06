"""Spot fan-in — merges Binance + Coinbase Records into one stream.

Convenience layer for ad-hoc smoke runs and for code that wants a single
async iterator over both spot upstreams. The runtime in
polymarket_bot._live.runtime drives the underlying feeds directly (so each
appears as its own task in the health snapshot); this aggregator is mainly
the prompt's 60s-smoke entry point. Records pass through unchanged — they
keep their original source ("binance" or "coinbase"), no rewriting.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from polymarket_bot.feeds.protocols import Feed, Health, Record


class SpotAggregator:
    """Concurrent fan-in over a list of Feed instances.

    Each child feed runs as its own task; produced Records flow through a
    bounded internal queue (default 1024) into the consumer. Aggregator
    health is the OR of children: if any child has had a recent message,
    last_seen_ns is the max across children. Stopping the aggregator
    propagates stop() to every child.
    """

    name: str = "spot_aggregator"

    def __init__(
        self,
        feeds: Sequence[Feed],
        *,
        internal_queue_size: int = 1024,
    ) -> None:
        if not feeds:
            raise ValueError("SpotAggregator requires at least one child feed")
        self._feeds: list[Feed] = list(feeds)
        self._internal_queue_size = internal_queue_size
        self._stop = asyncio.Event()

    @property
    def health(self) -> Health:
        children = [f.health for f in self._feeds]
        last_seen = max((h["last_seen_ns"] for h in children), default=0)
        msgs = sum(h["msgs_seen"] for h in children)
        reconnects = sum(h["reconnects"] for h in children)
        errors = [h["last_error"] for h in children if h["last_error"]]
        last_error = " | ".join(errors)[:400]
        return Health(
            name=self.name,
            last_seen_ns=last_seen,
            msgs_seen=msgs,
            reconnects=reconnects,
            last_error=last_error,
        )

    @property
    def children(self) -> list[Feed]:
        return list(self._feeds)

    def stop(self) -> None:
        self._stop.set()
        for f in self._feeds:
            f.stop()

    def stream(self) -> AsyncIterator[Record]:
        return self._stream_impl()

    async def _stream_impl(self) -> AsyncIterator[Record]:
        queue: asyncio.Queue[Record | None] = asyncio.Queue(self._internal_queue_size)

        async def pump(feed: Feed) -> None:
            try:
                async for record in feed.stream():
                    await queue.put(record)
            except asyncio.CancelledError:
                raise
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(pump(f), name=f"pump-{f.name}") for f in self._feeds]
        active = len(tasks)
        try:
            while active > 0 and not self._stop.is_set():
                rec = await queue.get()
                if rec is None:
                    active -= 1
                    continue
                yield rec
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


_: type[Feed] = SpotAggregator

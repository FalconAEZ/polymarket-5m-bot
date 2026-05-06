"""Runtime — wires the four feeds + Parquet writer + health task into one loop.

main() is called by scripts/run_capture.py and runs forever (or until a
SIGTERM/SIGINT is received). Each feed runs as its own asyncio.Task. A
shared bounded queue (size 10_000) carries Records to the writer task.
Drop-oldest backpressure policy is implemented in the per-feed runner here
(not inside each Feed) so the same policy applies uniformly. The health
aggregator reads each Feed's health property every 30s and writes the
JSON snapshot. Graceful shutdown drains the queue before closing Parquet
writers so no in-flight records are lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable, Sequence
from pathlib import Path

from polymarket_bot._live.feeds.oracle import OracleFeed
from polymarket_bot._live.feeds.polymarket import PolymarketFeed
from polymarket_bot._live.feeds.spot_binance import BinanceTradeFeed
from polymarket_bot._live.feeds.spot_coinbase import CoinbaseMatchFeed
from polymarket_bot._live.health import health_task
from polymarket_bot._live.storage import writer_task
from polymarket_bot.feeds.protocols import Feed, Record

QUEUE_SIZE = 10_000
LOG = logging.getLogger("polymarket_bot.runtime")


class DropCounter:
    """Process-wide counter for records the runtime had to drop on QueueFull."""

    def __init__(self) -> None:
        self._n = 0

    def increment(self) -> None:
        self._n += 1

    def get(self) -> int:
        return self._n


async def feed_runner(
    feed: Feed,
    queue: asyncio.Queue[Record | None],
    drop_counter: DropCounter,
    stop: asyncio.Event,
) -> None:
    """Drives one Feed's stream; pushes Records onto the shared queue.

    Implements the drop-oldest backpressure policy from
    design/data_plane.md §7: on QueueFull, pop the oldest Record and retry
    once. If the queue is empty (impossible in practice — the writer
    drains continuously — but guarded), the policy degrades to "drop new"
    rather than blocking indefinitely.
    """
    try:
        async for record in feed.stream():
            if stop.is_set():
                break
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                drop_counter.increment()
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(record)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOG.exception("feed %s crashed unexpectedly", feed.name)
        raise


def default_feeds() -> list[Feed]:
    return [
        BinanceTradeFeed(),
        CoinbaseMatchFeed(),
        OracleFeed(),
        PolymarketFeed(),
    ]


async def main(
    *,
    feeds: Sequence[Feed] | None = None,
    ticks_root: str | Path = "ticks",
    health_path: str | Path = "state/feeds_health.json",
    install_signal_handlers: bool = True,
    stop: asyncio.Event | None = None,
) -> int:
    """Run the four-feed capture pipeline. Returns total records written.

    Tests (and the 60s end-to-end smoke) pass install_signal_handlers=False
    + a stop event they manage themselves. Production (run_capture.py)
    relies on this function to wire SIGTERM/SIGINT to the same stop event.
    """
    feed_list = list(feeds) if feeds is not None else default_feeds()
    queue: asyncio.Queue[Record | None] = asyncio.Queue(QUEUE_SIZE)
    drop_counter = DropCounter()
    stop_event = stop if stop is not None else asyncio.Event()

    if install_signal_handlers:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)

    feed_tasks = [
        asyncio.create_task(feed_runner(f, queue, drop_counter, stop_event), name=f"feed-{f.name}")
        for f in feed_list
    ]
    writer = asyncio.create_task(writer_task(queue, root=ticks_root), name="writer")
    health_stop = asyncio.Event()
    health_queue: asyncio.Queue[object] = queue  # type: ignore[assignment]
    health = asyncio.create_task(
        health_task(
            feed_list,
            queue=health_queue,
            dropped_counter=drop_counter.get,
            health_path=health_path,
            stop=health_stop,
        ),
        name="health",
    )

    await stop_event.wait()
    LOG.info("shutdown requested; stopping feeds")
    for f in feed_list:
        f.stop()
    for t in feed_tasks:
        t.cancel()
    await asyncio.gather(*feed_tasks, return_exceptions=True)

    LOG.info("feeds stopped; flushing writer queue")
    await queue.put(None)
    total = await writer
    health_stop.set()
    health.cancel()
    await asyncio.gather(health, return_exceptions=True)
    LOG.info("shutdown complete: records_written=%d dropped=%d", total, drop_counter.get())
    return total


def configure_logging(log_path: str | Path | None = None) -> None:
    """Side-effect helper invoked by run_capture.py — keeps main() pure."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


_: Callable[..., object] = main

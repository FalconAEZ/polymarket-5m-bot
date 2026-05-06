"""Parquet writer task — drains the shared queue into per-source-per-day files.

Owns one pyarrow ParquetWriter per (utc_date, source) pair. Flushes on the
first of: 200 records buffered for a given (date, source), or 5 seconds since
last flush, or shutdown. Rotates writers at UTC midnight (date change). The
schema is pinned in design/data_plane.md §4 and must not drift after the
first captured day. Backpressure (10k queue cap, drop-oldest) is the queue
producer's responsibility, not this writer's — see runtime.py and the feed
runners for that policy.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_bot.feeds.protocols import Record

SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("ts_utc_ns", pa.int64()),
        pa.field("received_at_ns", pa.int64()),
        pa.field("source", pa.string()),
        pa.field("kind", pa.string()),
        pa.field("payload_json", pa.string()),
    ]
)

DEFAULT_BATCH_SIZE = 200
DEFAULT_FLUSH_INTERVAL_S = 5.0
DEFAULT_TICKS_DIR = "ticks"


def default_launch_id() -> str:
    """Per-launch identifier baked into Parquet filenames.

    Format: `<unix_seconds>` of process start. A laptop sleep + restart
    produces a new launch_id, so the new ParquetWriter instances open
    distinct files (e.g. `binance_1715000123.parquet` alongside the
    earlier `binance_1715000045.parquet`) and the day's earlier data
    survives intact. The Phase 2.6 analysis and gate scripts glob
    `<source>*.parquet` to read all of a day's parts.
    """
    return str(int(time.time()))


class ParquetWriter:
    """Holds open writers for active (date, source) pairs and appends batches.

    Per design/data_plane.md §5: filesystem layout is
    <root>/<UTC-YYYY-MM-DD>/<source>_<launch_id>.parquet. The launch_id
    suffix means a re-launch (laptop sleep, crash recovery) NEVER
    truncates the previous launch's parquet file for the same day; each
    launch writes its own file. Tests pin launch_id to "test" so the
    paths read clean in fixtures.
    """

    def __init__(
        self,
        root: str | Path = DEFAULT_TICKS_DIR,
        *,
        launch_id: str | None = None,
    ) -> None:
        self._root = Path(root)
        self._launch_id = launch_id if launch_id is not None else default_launch_id()
        self._writers: dict[tuple[str, str], pq.ParquetWriter] = {}

    def _path_for(self, utc_date: str, source: str) -> Path:
        day_dir = self._root / utc_date
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"{source}_{self._launch_id}.parquet"

    def _writer_for(self, utc_date: str, source: str) -> pq.ParquetWriter:
        key = (utc_date, source)
        existing = self._writers.get(key)
        if existing is not None:
            return existing
        path = self._path_for(utc_date, source)
        writer = pq.ParquetWriter(path, SCHEMA, compression="zstd")  # type: ignore[no-untyped-call]
        self._writers[key] = writer
        return writer

    def write_batch(self, utc_date: str, source: str, records: list[Record]) -> None:
        if not records:
            return
        table = pa.table(
            {
                "ts_utc_ns": [r.ts_utc_ns for r in records],
                "received_at_ns": [r.received_at_ns for r in records],
                "source": [r.source for r in records],
                "kind": [r.kind for r in records],
                "payload_json": [r.payload_json for r in records],
            },
            schema=SCHEMA,
        )
        self._writer_for(utc_date, source).write_table(table)  # type: ignore[no-untyped-call]

    def close_all(self) -> None:
        while self._writers:
            (_date, _source), writer = self._writers.popitem()
            writer.close()  # type: ignore[no-untyped-call]

    def close_date(self, utc_date: str) -> None:
        """Close all writers for a given date (used on UTC-midnight rotation)."""
        keys = [k for k in self._writers if k[0] == utc_date]
        for k in keys:
            self._writers.pop(k).close()  # type: ignore[no-untyped-call]


def utc_today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


async def writer_task(
    queue: asyncio.Queue[Record | None],
    *,
    root: str | Path = DEFAULT_TICKS_DIR,
    batch_size: int = DEFAULT_BATCH_SIZE,
    flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
    monotonic: Callable[[], float] = time.monotonic,
    today_fn: Callable[[], str] = utc_today,
    launch_id: str | None = None,
) -> int:
    """Async writer loop. Drains queue into Parquet, rotates at UTC midnight.

    None on the queue is the shutdown sentinel; the writer flushes any
    buffered records and closes all open writers, then returns the total
    number of records written. Backpressure is upstream (the runtime's
    feed-runner drops oldest on QueueFull); this writer trusts whatever
    arrives. monotonic and today_fn are injected so tests can drive the
    flush-on-time and date-rotation paths deterministically.
    """
    writer = ParquetWriter(root=root, launch_id=launch_id)
    pending: dict[tuple[str, str], list[Record]] = {}
    last_flush = monotonic()
    total_written = 0

    def _flush_all() -> int:
        nonlocal pending
        n = 0
        for (date, source), buf in pending.items():
            writer.write_batch(date, source, buf)
            n += len(buf)
        pending = {}
        return n

    try:
        current_date = today_fn()
        while True:
            timeout = max(flush_interval_s - (monotonic() - last_flush), 0.05)
            try:
                rec = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                rec = None
                got_item = False
            else:
                got_item = True
                if rec is None:
                    total_written += _flush_all()
                    break
            if got_item and rec is not None:
                d = today_fn()
                if d != current_date:
                    total_written += _flush_all()
                    writer.close_date(current_date)
                    current_date = d
                key = (current_date, rec.source)
                pending.setdefault(key, []).append(rec)
                if len(pending[key]) >= batch_size:
                    writer.write_batch(current_date, rec.source, pending[key])
                    total_written += len(pending[key])
                    pending[key] = []
                    # NOTE: deliberately do NOT reset last_flush here.
                    # Per-key batch flushes are independent of the time-based
                    # _flush_all sweep that catches slow feeds (e.g. the
                    # oracle's 33s heartbeat will never reach batch_size of
                    # 200 in a single capture day, so it relies on the time
                    # sweep to land its records on disk).
            now = monotonic()
            if now - last_flush >= flush_interval_s:
                total_written += _flush_all()
                last_flush = now
    finally:
        writer.close_all()
    return total_written

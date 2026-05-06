"""Tests for polymarket_bot._live.storage — Parquet writer + writer_task.

Round-trips Records through write_batch and reads back via polars to verify
the schema is honoured. Drives writer_task with a fake clock + today_fn so
flush-on-time and UTC-midnight rotation paths are exercised deterministically
without a real wall clock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import polars as pl

from polymarket_bot._live.storage import ParquetWriter, writer_task
from polymarket_bot.feeds.protocols import Record


def _rec(source: str, kind: str, n: int) -> Record:
    return Record(
        ts_utc_ns=n * 1_000_000_000,
        received_at_ns=n * 1_000_000_000 + 1,
        source=source,
        kind=kind,
        payload_json=f'{{"i":{n}}}',
    )


def test_parquet_writer_round_trips_one_batch(tmp_path: Path) -> None:
    writer = ParquetWriter(root=tmp_path)
    records = [_rec("binance", "trade", i) for i in range(3)]
    writer.write_batch("2026-05-07", "binance", records)
    writer.close_all()

    path = tmp_path / "2026-05-07" / "binance.parquet"
    assert path.exists()
    df = pl.read_parquet(path)
    assert df.shape == (3, 5)
    assert df["source"].to_list() == ["binance", "binance", "binance"]
    assert df["kind"].to_list() == ["trade", "trade", "trade"]
    assert df["ts_utc_ns"].to_list() == [0, 1_000_000_000, 2_000_000_000]


def test_parquet_writer_appends_multiple_batches(tmp_path: Path) -> None:
    writer = ParquetWriter(root=tmp_path)
    writer.write_batch("2026-05-07", "binance", [_rec("binance", "trade", 0)])
    writer.write_batch("2026-05-07", "binance", [_rec("binance", "trade", 1)])
    writer.close_all()

    df = pl.read_parquet(tmp_path / "2026-05-07" / "binance.parquet")
    assert df.shape == (2, 5)


def test_parquet_writer_separates_sources_and_dates(tmp_path: Path) -> None:
    writer = ParquetWriter(root=tmp_path)
    writer.write_batch("2026-05-07", "binance", [_rec("binance", "trade", 1)])
    writer.write_batch("2026-05-07", "coinbase", [_rec("coinbase", "match", 2)])
    writer.write_batch("2026-05-08", "binance", [_rec("binance", "trade", 3)])
    writer.close_all()

    paths = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    assert paths == [
        "2026-05-07/binance.parquet",
        "2026-05-07/coinbase.parquet",
        "2026-05-08/binance.parquet",
    ]


def test_parquet_writer_close_date_only_closes_matching_keys(tmp_path: Path) -> None:
    writer = ParquetWriter(root=tmp_path)
    writer.write_batch("2026-05-07", "binance", [_rec("binance", "trade", 0)])
    writer.write_batch("2026-05-08", "binance", [_rec("binance", "trade", 1)])
    writer.close_date("2026-05-07")
    # 2026-05-08 writer must still be live; another write should succeed.
    writer.write_batch("2026-05-08", "binance", [_rec("binance", "trade", 2)])
    writer.close_all()
    df = pl.read_parquet(tmp_path / "2026-05-08" / "binance.parquet")
    assert df.shape == (2, 5)


async def test_writer_task_flushes_on_sentinel(tmp_path: Path) -> None:
    queue: asyncio.Queue[Record | None] = asyncio.Queue(100)
    for i in range(5):
        queue.put_nowait(_rec("binance", "trade", i))
    queue.put_nowait(None)

    total = await writer_task(
        queue,
        root=tmp_path,
        batch_size=200,
        flush_interval_s=10.0,
        today_fn=lambda: "2026-05-07",
    )
    assert total == 5
    df = pl.read_parquet(tmp_path / "2026-05-07" / "binance.parquet")
    assert df.shape == (5, 5)


async def test_writer_task_rotates_on_utc_midnight(tmp_path: Path) -> None:
    queue: asyncio.Queue[Record | None] = asyncio.Queue(100)
    for i in range(3):
        queue.put_nowait(_rec("binance", "trade", i))
    queue.put_nowait(None)

    dates = iter(["2026-05-07", "2026-05-07", "2026-05-08"])

    def today_fn() -> str:
        try:
            return next(dates)
        except StopIteration:
            return "2026-05-08"

    total = await writer_task(
        queue,
        root=tmp_path,
        batch_size=200,
        flush_interval_s=10.0,
        today_fn=today_fn,
    )
    assert total == 3
    files = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet")}
    assert files == {"2026-05-07/binance.parquet", "2026-05-08/binance.parquet"}

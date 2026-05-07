"""Pull last N days of BTCUSDT 1-minute klines from Binance public REST.

Driven by the operator's 2026-05-08 "we need more data" request after the
spot-vs-book correlation analysis on 837 trades found a 78%/25% aligned-vs-
contrarian gap. The bottleneck wasn't bonereaper trade count — it was
captured spot data (only ~132 min of overlap from a sibling worktree's
Phase 4 capture). Solution: pull historical BTCUSDT klines from Binance
public REST (no auth, no key required) and use those as the spot reference
for the broader bonereaper trade dataset.

1-minute resolution is sufficient for the Δ_bps analysis: a 5-10bps move
is ~$40-80 on $80k BTC, typically resolved within seconds; the open price
of the containing minute is a reasonable point estimate. Could go to 1s
klines later if results need refining, but at 30x the API calls.

Public REST endpoint: GET https://api.binance.com/api/v3/klines
  symbol=BTCUSDT, interval=1m, startTime=<ms>, endTime=<ms>, limit=1000

For 30 days: 30 * 1440 = 43,200 candles, 1000 per call → 44 API calls.
Public REST rate limit is 1200 requests/min weighted; far under.

Output: a parquet file at state/research/binance_historical/btcusdt_1m_<date>.parquet
with columns ts_s (open second), open, high, low, close, volume.

Usage:
  uv run python -u scripts/research/binance_historical_klines.py [--days 30]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = PROJECT_ROOT / "state" / "research" / "binance_historical"

BINANCE_BASE = "https://api.binance.com"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LIMIT = 1000


def _fetch_chunk(client: httpx.Client, start_ms: int, end_ms: int) -> list[list[float | int | str]]:
    resp = client.get(
        f"{BINANCE_BASE}/api/v3/klines",
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": LIMIT,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return list(data)


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Parquet output (default state/research/binance_historical/btcusdt_1m_<date>.parquet)",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or (OUT_DIR / f"btcusdt_1m_{_today_utc_str()}.parquet")

    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=args.days)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    print(
        f"==> pulling {SYMBOL} {INTERVAL} klines from "
        f"{start_dt.isoformat()} to {end_dt.isoformat()}",
        flush=True,
    )

    rows: list[list[float | int | str]] = []
    cursor_ms = start_ms
    n_calls = 0
    started = time.time()
    with httpx.Client(timeout=httpx.Timeout(15.0, read=15.0)) as cli:
        while cursor_ms < end_ms:
            chunk = _fetch_chunk(cli, cursor_ms, end_ms)
            n_calls += 1
            if not chunk:
                break
            rows.extend(chunk)
            # Each chunk's last open_time is the end of this batch; advance past it.
            last_open_ms = int(chunk[-1][0])
            next_ms = last_open_ms + 60_000  # next minute
            if next_ms <= cursor_ms:
                break
            cursor_ms = next_ms
            if n_calls % 10 == 0:
                print(f"    {n_calls} calls, {len(rows):,} candles", flush=True)
            # Tiny pacing — Binance is fine but be polite.
            time.sleep(0.05)

    print(f"    total {n_calls} calls, {len(rows):,} candles", flush=True)

    if not rows:
        print("    no data; aborting", flush=True)
        return 1

    df = (
        pl.DataFrame(
            {
                "open_time_ms": [int(r[0]) for r in rows],
                "open": [float(r[1]) for r in rows],
                "high": [float(r[2]) for r in rows],
                "low": [float(r[3]) for r in rows],
                "close": [float(r[4]) for r in rows],
                "volume": [float(r[5]) for r in rows],
            }
        )
        .unique(subset=["open_time_ms"])
        .sort("open_time_ms")
    )
    df = df.with_columns(ts_s=(pl.col("open_time_ms") // 1000).cast(pl.Int64))
    df = df.select(["ts_s", "open", "high", "low", "close", "volume"])

    df.write_parquet(out_path)
    elapsed = time.time() - started
    ts_min = int(df["ts_s"].min())
    ts_max = int(df["ts_s"].max())
    cov_hours = (ts_max - ts_min) / 3600
    print(
        f"==> wrote {len(df):,} candles to {out_path} "
        f"(coverage {cov_hours:.1f}h; elapsed {elapsed:.1f}s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

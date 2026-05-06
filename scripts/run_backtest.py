"""CLI: run BacktestRunner over captured Parquet data with the deterministic strategy.

`uv run python scripts/run_backtest.py --dates 2026-05-06,2026-05-07`

Steps:
  1. Discover unique 5m windows in the date range from captured polymarket
     parquet files (we only backtest windows we have data for).
  2. Warm a TokenSideIndex by calling Gamma per discovered window.
     Cache to state/token_side_index.json so re-runs skip the API calls.
  3. Run the DeterministicStrategy through BacktestRunner over the date
     range, with the warmed resolver.
  4. Print aggregate metrics + a per-window CSV-shaped summary.

This is a Phase 3.1.5d deliverable — first end-to-end backtest pass on
real data. Phase 3.3 (LLM A/B) will reuse this script with a different
strategy injected.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import polars as pl  # noqa: E402

from polymarket_bot._live.feeds.polymarket import GammaClient  # noqa: E402
from polymarket_bot.backtest.fills import FillSimulator  # noqa: E402
from polymarket_bot.backtest.replay import ReplayEngine  # noqa: E402
from polymarket_bot.backtest.runner import BacktestRunner, aggregate_metrics  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.resolver import active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import DeterministicStrategy  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_backtest")


def _discover_windows(ticks_root: Path, dates: list[str]) -> list[int]:
    windows: set[int] = set()
    for date in dates:
        for path in (ticks_root / date).glob("polymarket_*.parquet"):
            try:
                ts_col = pl.read_parquet(path).get_column("ts_utc_ns")
            except Exception as e:
                LOG.warning("skipping %s: %s", path, e)
                continue
            for ts_ns in ts_col:
                windows.add(active_window_ts(ts_ns // 1_000_000_000))
    return sorted(windows)


async def main(
    dates: list[str],
    *,
    ticks_root: Path,
    cache_path: Path,
    threshold_pct: float,
    ttl_low_s: int,
    ttl_high_s: int,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(f"Discovering windows in {ticks_root} for dates {dates}...", flush=True)
    windows = _discover_windows(ticks_root, dates)
    print(f"Found {len(windows)} unique 5m windows.", flush=True)
    if not windows:
        print("No polymarket data found; exiting.")
        return 1

    print(f"Warming TokenSideIndex (cache={cache_path})...", flush=True)
    gamma = GammaClient()
    index = TokenSideIndex(fetch_fn=gamma.fetch_event, cache_path=cache_path)
    n_new = await index.warm(windows)
    print(
        f"Resolver: {index.n_known_tokens} tokens mapped "
        f"({n_new} new fetches; rest from cache)",
        flush=True,
    )

    print(
        f"Replaying with DeterministicStrategy "
        f"(threshold={threshold_pct}pp, ttl=[{ttl_low_s},{ttl_high_s}]s)...",
        flush=True,
    )
    replay = ReplayEngine(ticks_root, dates, side_resolver=index)
    strategy = DeterministicStrategy(
        threshold_pct=threshold_pct, ttl_low_s=ttl_low_s, ttl_high_s=ttl_high_s
    )
    runner = BacktestRunner(replay, simulator=FillSimulator())
    results = await runner.run(strategy)
    metrics = aggregate_metrics(results)

    print()
    print("=== BACKTEST METRICS ===")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:+.4f}")
        else:
            print(f"  {k}: {v}")
    print()
    print("=== PER-WINDOW SUMMARY (filled trades only, first 50) ===")
    print(
        f"{'window_ts':>12s}  {'side':>4s}  {'res':>4s}  "
        f"{'fill_px':>7s}  {'pnl_usd':>9s}  rationale"
    )
    filled = [r for r in results if r.fill is not None]
    for r in filled[:50]:
        if r.fill is None:
            continue
        side_str = r.side or "?"
        res_str = r.resolution or "?"
        print(
            f"{r.window_ts:>12d}  {side_str:>4s}  {res_str:>4s}  "
            f"{r.fill.price_filled:>7.4f}  {r.pnl_usd:>+8.4f}  {r.rationale}"
        )
    if len(filled) > 50:
        print(f"... ({len(filled) - 50} more filled trades omitted)")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        required=True,
        help="Comma-separated UTC dates (YYYY-MM-DD) to backtest over.",
    )
    parser.add_argument("--ticks-root", default="ticks")
    parser.add_argument("--cache-path", default="state/token_side_index.json")
    parser.add_argument("--threshold-pct", type=float, default=0.6)
    parser.add_argument("--ttl-low", type=int, default=10)
    parser.add_argument("--ttl-high", type=int, default=30)
    args = parser.parse_args()
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    rc = asyncio.run(
        main(
            dates,
            ticks_root=Path(args.ticks_root),
            cache_path=Path(args.cache_path),
            threshold_pct=args.threshold_pct,
            ttl_low_s=args.ttl_low,
            ttl_high_s=args.ttl_high,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    cli()

"""CLI: A/B harness for Phase 3.3.

`uv run python scripts/run_ab.py --dates 2026-05-06`

Runs two strategies through the same captured data + same fill simulator
and prints paired metrics: win-rate delta, total P&L delta, fire-rate
delta, latency delta. Both sides see the identical event stream and
identical TokenSideIndex cache so the comparison is fair.

By default the A is the deterministic baseline (no API spend) and the B is
the deterministic baseline at a *calibrated* threshold — useful as a smoke
of the harness on quiet-market data without invoking the LLM ensemble.

To run the locked A/B (deterministic vs deterministic+ensemble) you must:
  1. confirm operator $-approval per locked decision #14, AND
  2. pass --enable-ensemble (which currently fails fast with an
     informative message because LLM A/B requires extra setup that this
     session does not ship).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
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
from polymarket_bot.strategies.protocol import Strategy  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_ab")


@dataclass
class PassResult:
    name: str
    elapsed_s: float
    metrics: dict[str, object]


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


async def _run_one_pass(
    name: str,
    strategy: Strategy,
    *,
    ticks_root: Path,
    dates: list[str],
    side_resolver: TokenSideIndex,
) -> PassResult:
    print(f"\n=== Pass: {name} ===", flush=True)
    replay = ReplayEngine(ticks_root, dates, side_resolver=side_resolver)
    runner = BacktestRunner(replay, simulator=FillSimulator())
    t0 = time.monotonic()
    results = await runner.run(strategy)
    elapsed = time.monotonic() - t0
    metrics = aggregate_metrics(results)
    print(f"  elapsed: {elapsed:.2f}s", flush=True)
    for k, v in metrics.items():
        print(f"  {k}: {v}", flush=True)
    return PassResult(name=name, elapsed_s=elapsed, metrics=metrics)


def _print_delta(a: PassResult, b: PassResult) -> None:
    print("\n=== A/B DELTA ===")
    print(f"  ({b.name}) - ({a.name})")

    def _f(metric: str, fmt: str = "{:+.4f}") -> None:
        a_val = a.metrics.get(metric)
        b_val = b.metrics.get(metric)
        if isinstance(a_val, int | float) and isinstance(b_val, int | float):
            print(
                f"  {metric:30s}  A={a_val:>8.4f}  B={b_val:>8.4f}  delta={fmt.format(b_val - a_val)}"
            )
        else:
            print(f"  {metric:30s}  A={a_val}  B={b_val}")

    for m in (
        "n_windows",
        "n_fired",
        "n_filled",
        "n_won",
        "win_rate",
        "total_pnl_usd",
        "avg_pnl_usd_per_filled",
    ):
        _f(m)

    print(
        f"  {'elapsed_s':30s}  A={a.elapsed_s:>8.2f}  B={b.elapsed_s:>8.2f}  delta={b.elapsed_s - a.elapsed_s:+.2f}"
    )


async def main(
    dates: list[str],
    *,
    ticks_root: Path,
    cache_path: Path,
    threshold_a: float,
    threshold_b: float,
    enable_ensemble: bool,
) -> int:
    if enable_ensemble:
        print(
            "\nERROR: --enable-ensemble requires operator $-approval per locked\n"
            "decision #14 (Anthropic budget). The deterministic-vs-ensemble A/B is\n"
            "not yet runnable end-to-end from this session — see\n"
            "design/agents.md §10 for the next-session plan.\n"
        )
        return 2

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

    pass_a = await _run_one_pass(
        f"deterministic@{threshold_a}pp",
        DeterministicStrategy(threshold_pct=threshold_a),
        ticks_root=ticks_root,
        dates=dates,
        side_resolver=index,
    )
    pass_b = await _run_one_pass(
        f"deterministic@{threshold_b}pp",
        DeterministicStrategy(threshold_pct=threshold_b),
        ticks_root=ticks_root,
        dates=dates,
        side_resolver=index,
    )

    _print_delta(pass_a, pass_b)
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dates",
        required=True,
        help="Comma-separated UTC dates (YYYY-MM-DD) to A/B over.",
    )
    parser.add_argument("--ticks-root", default="ticks")
    parser.add_argument("--cache-path", default="state/token_side_index.json")
    parser.add_argument(
        "--threshold-a",
        type=float,
        default=0.6,
        help="Pass A composite threshold in percentage points (locked decision #6 default 0.6).",
    )
    parser.add_argument(
        "--threshold-b",
        type=float,
        default=0.05,
        help="Pass B composite threshold (calibration variant).",
    )
    parser.add_argument(
        "--enable-ensemble",
        action="store_true",
        help="Run deterministic vs ensemble A/B (requires operator $-approval).",
    )
    args = parser.parse_args()
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    rc = asyncio.run(
        main(
            dates,
            ticks_root=Path(args.ticks_root),
            cache_path=Path(args.cache_path),
            threshold_a=args.threshold_a,
            threshold_b=args.threshold_b,
            enable_ensemble=args.enable_ensemble,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    cli()

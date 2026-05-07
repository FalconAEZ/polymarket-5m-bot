"""CLI: A/B harness for Phase 3.3.

`uv run python scripts/run_ab.py --dates 2026-05-06`

Runs two strategies through the same captured data + same fill simulator
and prints paired metrics: win-rate delta, total P&L delta, fire-rate
delta, latency delta. Both sides see the identical event stream and
identical TokenSideIndex cache so the comparison is fair.

By default the A is the deterministic baseline (no API spend) and the B is
the deterministic baseline at a *calibrated* threshold — useful as a smoke
of the harness on quiet-market data without invoking the LLM ensemble.

To run the locked deterministic-vs-ensemble A/B (decision #16), pass
`--enable-ensemble`. Pass A is the deterministic baseline; pass B builds an
EnsembleStrategy backed by a fresh AnthropicAdapter + BudgetTracker
(`--hard-limit-usd`, default $35 per locked decision #14). Spend is reported
at the end of pass B regardless of whether the budget cap fired.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
from polymarket_bot.agents.anthropic_client import AnthropicAdapter  # noqa: E402
from polymarket_bot.agents.budget import BudgetExceeded, BudgetTracker  # noqa: E402
from polymarket_bot.agents.meta import MetaDecider  # noqa: E402
from polymarket_bot.agents.momentum import MomentumAgent  # noqa: E402
from polymarket_bot.agents.oracle_gap import OracleGapAgent  # noqa: E402
from polymarket_bot.agents.orderbook import OrderbookAgent  # noqa: E402
from polymarket_bot.backtest.fills import FillSimulator  # noqa: E402
from polymarket_bot.backtest.replay import ReplayEngine  # noqa: E402
from polymarket_bot.backtest.runner import BacktestRunner, aggregate_metrics  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.resolver import active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import DeterministicStrategy  # noqa: E402
from polymarket_bot.strategies.ensemble import EnsembleStrategy  # noqa: E402
from polymarket_bot.strategies.protocol import Strategy  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_ab")


@dataclass
class PassResult:
    name: str
    elapsed_s: float
    metrics: dict[str, object]
    budget_report: dict[str, object] | None = None
    budget_exceeded: bool = False


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


def _build_ensemble_strategy(adapter: AnthropicAdapter, threshold_pct: float) -> EnsembleStrategy:
    """Construct the locked 3-specialist + meta ensemble per design/agents.md.

    All specialists + meta share one adapter (so they share one BudgetTracker
    and one cache namespace). Used by run_ab.py and by tests; lives at
    module scope so tests can import it without invoking ``cli()``.
    """
    orderbook = OrderbookAgent(adapter)
    oracle_gap = OracleGapAgent(adapter)
    momentum = MomentumAgent(adapter)
    meta = MetaDecider(adapter)
    return EnsembleStrategy(
        specialists=[orderbook, oracle_gap, momentum],
        meta=meta,
        threshold_pct=threshold_pct,
    )


async def _run_one_pass(
    name: str,
    strategy: Strategy,
    *,
    ticks_root: Path,
    dates: list[str],
    side_resolver: TokenSideIndex,
    budget: BudgetTracker | None = None,
) -> PassResult:
    print(f"\n=== Pass: {name} ===", flush=True)
    replay = ReplayEngine(ticks_root, dates, side_resolver=side_resolver)
    runner = BacktestRunner(replay, simulator=FillSimulator())
    t0 = time.monotonic()
    budget_exceeded = False
    try:
        results = await runner.run(strategy)
    except BudgetExceeded as e:
        # The BudgetTracker fired its hard cap mid-pass. Per design/agents.md
        # §5 + decision #14: surface the partial spend, do NOT re-run, leave
        # diagnosis to the operator (likely cache miss-rate).
        elapsed = time.monotonic() - t0
        print(f"  BudgetExceeded after {elapsed:.2f}s: {e}", flush=True)
        report = budget.report() if budget is not None else None
        if report is not None:
            print(f"  budget report: {report}", flush=True)
        return PassResult(
            name=name,
            elapsed_s=elapsed,
            metrics={
                "n_windows": 0,
                "n_fired": 0,
                "n_filled": 0,
                "n_won": 0,
                "win_rate": 0.0,
                "total_pnl_usd": 0.0,
                "avg_pnl_usd_per_filled": 0.0,
                "aborted_reason": str(e),
            },
            budget_report=report,
            budget_exceeded=True,
        )
    elapsed = time.monotonic() - t0
    metrics = aggregate_metrics(results)
    print(f"  elapsed: {elapsed:.2f}s", flush=True)
    for k, v in metrics.items():
        print(f"  {k}: {v}", flush=True)
    report = budget.report() if budget is not None else None
    if report is not None:
        print(f"  budget report: {report}", flush=True)
    return PassResult(
        name=name,
        elapsed_s=elapsed,
        metrics=metrics,
        budget_report=report,
        budget_exceeded=budget_exceeded,
    )


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
    hard_limit_usd: float,
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

    pass_a = await _run_one_pass(
        f"deterministic@{threshold_a}pp",
        DeterministicStrategy(threshold_pct=threshold_a),
        ticks_root=ticks_root,
        dates=dates,
        side_resolver=index,
    )

    if enable_ensemble:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "\nERROR: --enable-ensemble requires ANTHROPIC_API_KEY in the\n"
                "environment (loaded from .envrc per Phase 0). Aborting before\n"
                "any spend.\n",
                flush=True,
            )
            return 2
        budget = BudgetTracker(hard_limit_usd=hard_limit_usd)
        adapter = AnthropicAdapter(budget=budget)
        ensemble = _build_ensemble_strategy(adapter, threshold_pct=threshold_b)
        pass_b = await _run_one_pass(
            f"ensemble@{threshold_b}pp(hard_cap=${hard_limit_usd})",
            ensemble,
            ticks_root=ticks_root,
            dates=dates,
            side_resolver=index,
            budget=budget,
        )
    else:
        pass_b = await _run_one_pass(
            f"deterministic@{threshold_b}pp",
            DeterministicStrategy(threshold_pct=threshold_b),
            ticks_root=ticks_root,
            dates=dates,
            side_resolver=index,
        )

    _print_delta(pass_a, pass_b)
    if pass_b.budget_exceeded:
        return 3
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
        help="Pass B composite threshold (calibration variant or ensemble fallback).",
    )
    parser.add_argument(
        "--enable-ensemble",
        action="store_true",
        help="Run deterministic vs ensemble A/B (requires operator $-approval and ANTHROPIC_API_KEY).",
    )
    parser.add_argument(
        "--hard-limit-usd",
        type=float,
        default=35.0,
        help="BudgetTracker hard cap in USD for the ensemble pass (locked decision #14).",
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
            hard_limit_usd=args.hard_limit_usd,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    cli()

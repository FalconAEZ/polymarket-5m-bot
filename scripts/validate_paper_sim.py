"""Sim validation harness — does FillSimulator track the live orderbook?

Per design/paper.md §6 + RUNBOOK §4.3. Runs the deterministic backtest
over a captured date range, samples up to N decisions (default 100),
and for each compares the simulated fill price against the actual
top-of-book at decision_ts + 150ms latency. Reports count / mean /
median / p95 / max delta in cents and the within-1¢ pass rate.

Usage:
  uv run python scripts/validate_paper_sim.py \
      --dates 2026-05-06,2026-05-07 \
      --threshold-pct 0.6 \
      --n-samples 100 \
      --report runbooks/gate-evidence/phase-4.3-sim-validation.txt

Failures: this script does NOT fail when the pass-rate < 90%. The 14-day
paper run is what validates the simulator at scale; this is a pre-flight
sanity check on the hours of data captured this far.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import polars as pl  # noqa: E402

from polymarket_bot._live.feeds.polymarket import GammaClient  # noqa: E402
from polymarket_bot.backtest.fills import FillSimulator  # noqa: E402
from polymarket_bot.backtest.replay import (  # noqa: E402
    ReplayEngine,
    SideResolver,
)
from polymarket_bot.backtest.runner import BacktestRunner, WindowResult  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.backtest.types import BookUpdate  # noqa: E402
from polymarket_bot.resolver import WINDOW_SECONDS, active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import DeterministicStrategy  # noqa: E402

LATENCY_BUDGET_NS = 150_000_000  # 150 ms — gasless relayer typical p99 confirm time
LOG = logging.getLogger("polymarket_bot.scripts.validate_paper_sim")


@dataclass(frozen=True, slots=True)
class SampleResult:
    """One row of the validation report."""

    window_ts: int
    decision_ts_ns: int
    asset_id: str
    side: str
    sim_price: float
    actual_best_ask: float
    delta_cents: float


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


async def _run_backtest(
    ticks_root: Path,
    dates: list[str],
    cache_path: Path,
    threshold_pct: float,
) -> tuple[list[WindowResult], SideResolver]:
    """Drive BacktestRunner once to produce decisions; return results + resolver."""
    windows = _discover_windows(ticks_root, dates)
    print(f"Found {len(windows)} unique 5m windows.", flush=True)
    if not windows:
        return [], TokenSideIndex(fetch_fn=GammaClient().fetch_event, cache_path=cache_path)
    print(f"Warming TokenSideIndex from cache + Gamma (cache={cache_path})...", flush=True)
    gamma = GammaClient()
    index = TokenSideIndex(fetch_fn=gamma.fetch_event, cache_path=cache_path)
    n_new = await index.warm(windows)
    print(
        f"Resolver: {index.n_known_tokens} tokens mapped ({n_new} new fetches; rest from cache)",
        flush=True,
    )
    replay = ReplayEngine(ticks_root, dates, side_resolver=index)
    strategy = DeterministicStrategy(threshold_pct=threshold_pct)
    runner = BacktestRunner(replay, simulator=FillSimulator())
    results = await runner.run(strategy)
    return results, index


def _book_events_by_asset(
    ticks_root: Path, dates: list[str], side_resolver: SideResolver
) -> dict[str, list[BookUpdate]]:
    """Stream replay once and bucket BookUpdates by asset_id, sorted by ts_utc_ns.

    Used for the post-hoc lookup step: given a decision, find the next
    BookUpdate for the decision's asset_id at decision_ts + latency budget.
    """
    replay = ReplayEngine(ticks_root, dates, side_resolver=side_resolver)
    by_asset: dict[str, list[BookUpdate]] = {}

    async def collect() -> None:
        async for event in replay.stream():
            if isinstance(event, BookUpdate) and event.best_ask is not None:
                by_asset.setdefault(event.asset_id, []).append(event)

    asyncio.run(collect())
    for events in by_asset.values():
        events.sort(key=lambda e: e.ts_utc_ns)
    return by_asset


def _find_actual_book(
    by_asset: dict[str, list[BookUpdate]], asset_id: str, target_ts_ns: int, window_ts: int
) -> BookUpdate | None:
    """Return the first BookUpdate for asset_id at ts >= target_ts_ns, capped at window close."""
    candidates = by_asset.get(asset_id, [])
    if not candidates:
        return None
    cap_ns = (window_ts + WINDOW_SECONDS) * 1_000_000_000
    # Linear scan — number of book events per asset over a few hours is
    # small enough this isn't a bottleneck for N <= a few hundred samples.
    for event in candidates:
        if event.ts_utc_ns < target_ts_ns:
            continue
        if event.ts_utc_ns > cap_ns:
            return None
        return event
    return None


def _samples(results: list[WindowResult], n: int, seed: int) -> list[WindowResult]:
    fired_with_fill = [
        r for r in results if r.fired and r.fill is not None and r.fill.price_filled is not None
    ]
    if len(fired_with_fill) <= n:
        return fired_with_fill
    rng = random.Random(seed)  # noqa: S311 — not security-sensitive; reproducible sampling
    return rng.sample(fired_with_fill, n)


def _validate(
    samples: list[WindowResult],
    by_asset: dict[str, list[BookUpdate]],
) -> tuple[list[SampleResult], list[str]]:
    rows: list[SampleResult] = []
    excluded: list[str] = []
    for r in samples:
        if r.fill is None:
            excluded.append(f"window={r.window_ts} no_fill")
            continue
        target = r.fill.ts_utc_ns + LATENCY_BUDGET_NS
        actual = _find_actual_book(by_asset, r.fill.asset_id, target, r.window_ts)
        if actual is None or actual.best_ask is None:
            excluded.append(f"window={r.window_ts} no_book_after_decision")
            continue
        delta = abs(r.fill.price_filled - actual.best_ask) * 100.0
        side_marker = "UP" if "side=UP" in r.rationale else "DOWN"
        rows.append(
            SampleResult(
                window_ts=r.window_ts,
                decision_ts_ns=r.fill.ts_utc_ns,
                asset_id=r.fill.asset_id,
                side=side_marker,
                sim_price=r.fill.price_filled,
                actual_best_ask=actual.best_ask,
                delta_cents=delta,
            )
        )
    return rows, excluded


def _format_report(
    rows: list[SampleResult],
    excluded: list[str],
    *,
    n_samples_requested: int,
    n_decisions_total: int,
    dates: list[str],
    threshold_pct: float,
) -> str:
    lines: list[str] = []
    lines.append("=== Phase 4.3 — Paper Sim Validation Report ===")
    lines.append(f"dates: {','.join(dates)}")
    lines.append(f"strategy: deterministic threshold_pct={threshold_pct}")
    lines.append(f"latency_budget_ns: {LATENCY_BUDGET_NS}  (150 ms)")
    lines.append(f"decisions_total: {n_decisions_total}")
    lines.append(f"samples_requested: {n_samples_requested}")
    lines.append(f"samples_validated: {len(rows)}")
    lines.append(f"samples_excluded: {len(excluded)}")
    if excluded:
        lines.append("excluded reasons (first 20):")
        for r in excluded[:20]:
            lines.append(f"  - {r}")
    if not rows:
        lines.append("")
        lines.append("FATAL: no usable samples. Cannot compute pass-rate.")
        return "\n".join(lines)
    deltas = [r.delta_cents for r in rows]
    pass_rate = sum(1 for d in deltas if d <= 1.0) / len(deltas)
    lines.append("")
    lines.append("--- delta_cents (|sim_price - actual_best_ask| * 100) ---")
    lines.append(f"mean:   {statistics.mean(deltas):.4f}")
    lines.append(f"median: {statistics.median(deltas):.4f}")
    p95 = statistics.quantiles(deltas, n=20)[18] if len(deltas) >= 20 else max(deltas)
    lines.append(f"p95:    {p95:.4f}")
    lines.append(f"max:    {max(deltas):.4f}")
    lines.append(f"within_1c_rate: {pass_rate:.4f}  (target >= 0.90)")
    if pass_rate >= 0.90:
        lines.append("STATUS: PASS — simulator within 1¢ of live book on >= 90% of samples")
    else:
        lines.append(
            f"STATUS: GAP — {pass_rate:.1%} within 1¢; below 90% target. "
            "14-day run is the real validation; this is hours-of-data only."
        )
    lines.append("")
    lines.append("--- per-sample rows (first 100) ---")
    lines.append("window_ts,decision_ts_ns,asset_id,side,sim_price,actual_best_ask,delta_cents")
    for r in rows[:100]:
        lines.append(
            ",".join(
                [
                    str(r.window_ts),
                    str(r.decision_ts_ns),
                    r.asset_id[:14] + "...",
                    r.side,
                    f"{r.sim_price:.4f}",
                    f"{r.actual_best_ask:.4f}",
                    f"{r.delta_cents:.4f}",
                ]
            )
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dates", required=True, help="Comma-separated UTC dates (YYYY-MM-DD)")
    parser.add_argument("--threshold-pct", type=float, default=0.6)
    parser.add_argument("--n-samples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticks-root", default="ticks")
    parser.add_argument("--cache-path", default="state/token_side_index.json")
    parser.add_argument(
        "--report",
        default="runbooks/gate-evidence/phase-4.3-sim-validation.txt",
        help="Path to write the report",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    ticks_root = Path(args.ticks_root)
    cache_path = Path(args.cache_path)

    print("Step 1/3: running deterministic backtest to produce decisions...", flush=True)
    results, side_resolver = asyncio.run(
        _run_backtest(ticks_root, dates, cache_path, args.threshold_pct)
    )
    fired = [r for r in results if r.fired]
    filled = [r for r in fired if r.fill is not None]
    print(
        f"Decisions: {len(fired)} fired, {len(filled)} with fills; "
        f"sampling up to {args.n_samples}",
        flush=True,
    )
    samples = _samples(results, args.n_samples, args.seed)

    print("Step 2/3: rebuilding asset_id-> [BookUpdate] index for lookup...", flush=True)
    by_asset = _book_events_by_asset(ticks_root, dates, side_resolver)
    total_books = sum(len(v) for v in by_asset.values())
    print(f"Indexed {total_books} BookUpdates across {len(by_asset)} assets.", flush=True)

    print("Step 3/3: comparing simulated fills to actual top-of-book...", flush=True)
    rows, excluded = _validate(samples, by_asset)

    report = _format_report(
        rows,
        excluded,
        n_samples_requested=args.n_samples,
        n_decisions_total=len(filled),
        dates=dates,
        threshold_pct=args.threshold_pct,
    )
    print(report, flush=True)
    out_path = Path(args.report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(f"\nReport written to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

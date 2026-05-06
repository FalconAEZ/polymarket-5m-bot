"""Walk-forward harness — orchestrates BacktestRunner over rolling folds.

Per design/backtest.md §6: rolling (train_days, test_days) windows that
slide forward by test_days. The strategy's `reset()` is called at the
start of each fold so a stateful strategy doesn't leak training-window
information into the test fold. Train + test are replayed as one
continuous event stream so the strategy's per-window state warms up on
train data before test windows produce reportable WindowResults.

Phase 3.3 uses this for the deterministic vs deterministic+LLM A/B
comparison: same `all_dates` + windows() call → identical fold sets;
two strategy_factory callables produce the two strategy populations;
results are joined fold-by-fold for paired comparisons.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from polymarket_bot.backtest.fills import FillSimulator
from polymarket_bot.backtest.replay import ReplayEngine, SideResolver
from polymarket_bot.backtest.runner import (
    BacktestRunner,
    WindowResult,
    aggregate_metrics,
)
from polymarket_bot.strategies.protocol import Strategy

DEFAULT_TRAIN_DAYS = 7
DEFAULT_TEST_DAYS = 1


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """One fold: a slice of training dates followed by a slice of test dates."""

    train_dates: tuple[str, ...]
    test_dates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FoldResult:
    """Outcome of one fold — the test-window results + their aggregate metrics."""

    fold: WalkForwardWindow
    test_results: tuple[WindowResult, ...]
    metrics: dict[str, Any]


def windows(
    all_dates: Sequence[str],
    *,
    train_days: int = DEFAULT_TRAIN_DAYS,
    test_days: int = DEFAULT_TEST_DAYS,
) -> list[WalkForwardWindow]:
    """Build a rolling walk-forward window list from a list of UTC dates.

    Slides by test_days at a time. Skips folds that would extend past the
    end of all_dates. Returns an empty list if there aren't enough dates
    for even one fold.
    """
    if train_days <= 0 or test_days <= 0:
        raise ValueError(f"train_days ({train_days}) and test_days ({test_days}) must be > 0")
    n = len(all_dates)
    out: list[WalkForwardWindow] = []
    i = 0
    while i + train_days + test_days <= n:
        train = tuple(all_dates[i : i + train_days])
        test = tuple(all_dates[i + train_days : i + train_days + test_days])
        out.append(WalkForwardWindow(train_dates=train, test_dates=test))
        i += test_days
    return out


def _date_range_ts(date_str: str) -> tuple[int, int]:
    """Return (start_ts_s, end_ts_s) for a UTC YYYY-MM-DD date (end-exclusive)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    start = int(dt.timestamp())
    end = int((dt + timedelta(days=1)).timestamp())
    return start, end


def _is_in_test_dates(window_ts: int, test_dates: Sequence[str]) -> bool:
    for d in test_dates:
        start, end = _date_range_ts(d)
        if start <= window_ts < end:
            return True
    return False


class WalkForwardRunner:
    """Orchestrates BacktestRunner over a list of WalkForwardWindow folds.

    Each fold:
      1. fresh strategy from strategy_factory()
      2. continuous replay over (train_dates + test_dates)
      3. results filtered to test_dates only
      4. aggregate metrics over the test-fold results
    """

    def __init__(
        self,
        ticks_root: str | Path,
        *,
        side_resolver: SideResolver,
        simulator: FillSimulator | None = None,
    ) -> None:
        self._ticks_root = Path(ticks_root)
        self._side_resolver = side_resolver
        self._sim = simulator if simulator is not None else FillSimulator()

    async def run(
        self,
        strategy_factory: Callable[[], Strategy],
        folds: Sequence[WalkForwardWindow],
    ) -> list[FoldResult]:
        out: list[FoldResult] = []
        for fold in folds:
            strategy = strategy_factory()
            strategy.reset()
            dates = list(fold.train_dates) + list(fold.test_dates)
            replay = ReplayEngine(self._ticks_root, dates, side_resolver=self._side_resolver)
            runner = BacktestRunner(replay, simulator=self._sim)
            all_results = await runner.run(strategy)
            test_results = tuple(
                r for r in all_results if _is_in_test_dates(r.window_ts, fold.test_dates)
            )
            out.append(
                FoldResult(
                    fold=fold,
                    test_results=test_results,
                    metrics=aggregate_metrics(test_results),
                )
            )
        return out


def aggregate_folds(folds: Sequence[FoldResult]) -> dict[str, Any]:
    """Combine per-fold metrics into a single overall summary.

    Sums the count-based metrics, recomputes win_rate over total filled
    trades, recomputes total_pnl_usd. Ignores per-fold averages because
    a simple mean weights folds equally regardless of trade count, which
    is misleading.
    """
    n_windows = sum(int(f.metrics.get("n_windows", 0)) for f in folds)
    n_fired = sum(int(f.metrics.get("n_fired", 0)) for f in folds)
    n_filled = sum(int(f.metrics.get("n_filled", 0)) for f in folds)
    n_won = sum(int(f.metrics.get("n_won", 0)) for f in folds)
    total_pnl = sum(float(f.metrics.get("total_pnl_usd", 0.0)) for f in folds)
    return {
        "n_folds": len(folds),
        "n_windows": n_windows,
        "n_fired": n_fired,
        "n_filled": n_filled,
        "n_won": n_won,
        "win_rate": (n_won / n_filled) if n_filled else 0.0,
        "total_pnl_usd": total_pnl,
        "avg_pnl_usd_per_filled": (total_pnl / n_filled) if n_filled else 0.0,
    }

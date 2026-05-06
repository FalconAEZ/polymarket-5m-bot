"""Tests for polymarket_bot.backtest.walk_forward.

Cover: windows() arithmetic over various date list sizes; FoldResult
shape; the WalkForwardRunner driving DeterministicStrategy through
synthetic Parquet fixtures across train + test dates; aggregate_folds
metric sums.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from polymarket_bot.backtest.replay import StaticTokenSideResolver
from polymarket_bot.backtest.walk_forward import (
    DEFAULT_TEST_DAYS,
    DEFAULT_TRAIN_DAYS,
    FoldResult,
    WalkForwardRunner,
    WalkForwardWindow,
    aggregate_folds,
    windows,
)
from polymarket_bot.strategies.deterministic import DeterministicStrategy

TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def test_windows_returns_empty_when_too_few_dates() -> None:
    assert windows([], train_days=7, test_days=1) == []
    assert windows(["2026-05-07"], train_days=7, test_days=1) == []


def test_windows_basic_seven_train_one_test() -> None:
    dates = [f"2026-05-{d:02d}" for d in range(1, 11)]  # 10 dates
    folds = windows(dates, train_days=7, test_days=1)
    # n=10, train=7, test=1 → 10 - 7 - 1 = 2; folds at i=0,1,2 → 3 folds
    assert len(folds) == 3
    assert folds[0].train_dates == tuple(dates[0:7])
    assert folds[0].test_dates == ("2026-05-08",)
    assert folds[1].test_dates == ("2026-05-09",)
    assert folds[2].test_dates == ("2026-05-10",)


def test_windows_slides_by_test_days() -> None:
    dates = [f"2026-05-{d:02d}" for d in range(1, 13)]  # 12 dates
    folds = windows(dates, train_days=3, test_days=2)
    # n=12, train=3, test=2 → step 2; folds at i=0,2,4,6 → train+test ends at 5,7,9,11
    assert len(folds) == 4
    assert folds[0].train_dates == ("2026-05-01", "2026-05-02", "2026-05-03")
    assert folds[0].test_dates == ("2026-05-04", "2026-05-05")
    assert folds[1].train_dates == ("2026-05-03", "2026-05-04", "2026-05-05")
    assert folds[1].test_dates == ("2026-05-06", "2026-05-07")


def test_windows_rejects_invalid_args() -> None:
    with pytest.raises(ValueError, match="train_days"):
        windows(["2026-05-07"], train_days=0, test_days=1)
    with pytest.raises(ValueError, match="train_days"):
        windows(["2026-05-07"], train_days=7, test_days=0)


def test_default_constants_match_design_doc() -> None:
    """design/backtest.md §6 specifies 7-day train, 1-day test."""
    assert DEFAULT_TRAIN_DAYS == 7
    assert DEFAULT_TEST_DAYS == 1


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "ts_utc_ns": [int(r["ts_utc_ns"]) for r in rows],
            "received_at_ns": [int(r["ts_utc_ns"]) for r in rows],
            "source": [str(r["source"]) for r in rows],
            "kind": [str(r["kind"]) for r in rows],
            "payload_json": [str(r["payload_json"]) for r in rows],
        }
    ).write_parquet(path)


def _binance_payload(price: float, ts_ms: int) -> str:
    return json.dumps(
        {"e": "trade", "T": ts_ms, "p": str(price), "q": "0.001"},
        separators=(",", ":"),
    )


def _oracle_payload(price_usd: float, ts_s: int) -> str:
    scaled = int(price_usd * 1e8)
    if scaled < 0:
        topic1_int = (1 << 256) + scaled
    else:
        topic1_int = scaled
    log = {
        "address": "0x" + "ab" * 20,
        "topics": [
            "0x0559884fd3a460db3073b7fc896cc77986f16e378210ded43186175bf646fc5f",
            "0x" + topic1_int.to_bytes(32, "big").hex(),
            "0x" + (1).to_bytes(32, "big").hex(),
        ],
        "data": "0x" + (ts_s).to_bytes(32, "big").hex(),
    }
    return json.dumps(log, separators=(",", ":"))


def _polymarket_book_payload(asset_id: str, ts_ms: int, ask: float = 0.55) -> str:
    return json.dumps(
        {
            "event_type": "best_bid_ask",
            "asset_id": asset_id,
            "market": "0xabc",
            "best_bid": str(ask - 0.02),
            "best_ask": str(ask),
            "spread": "0.02",
            "timestamp": str(ts_ms),
        },
        separators=(",", ":"),
    )


def _row(ts: int, source: str, kind: str, payload: str) -> dict[str, object]:
    return {"ts_utc_ns": ts, "source": source, "kind": kind, "payload_json": payload}


# UTC date "2026-05-07" starts at unix second 1778112000.
DAY_05_07 = 1_778_112_000


def _seed_one_window(rows: list[dict[str, object]], window_ts: int) -> None:
    """Add a complete 5m window's worth of fixture events to `rows`.

    The window's spot moves +1.5% and oracle confirms — comfortably above
    a 0.5pp threshold; book updates fall inside the [10, 30]s TTL.
    """
    base_ns = window_ts * 1_000_000_000
    rows.append(
        _row(
            base_ns + 1_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_000.0, window_ts * 1000 + 1000),
        )
    )
    rows.append(
        _row(
            base_ns + 1_500_000_000,
            "polymarket",
            "best_bid_ask",
            _polymarket_book_payload(TOKEN_UP, window_ts * 1000 + 1500, ask=0.55),
        )
    )
    rows.append(
        _row(
            base_ns + 1_500_000_000,
            "polymarket",
            "best_bid_ask",
            _polymarket_book_payload(TOKEN_DOWN, window_ts * 1000 + 1500, ask=0.46),
        )
    )
    rows.append(
        _row(
            base_ns + 2_000_000_000,
            "oracle",
            "AnswerUpdated",
            _oracle_payload(60_000.0, window_ts + 2),
        )
    )
    rows.append(
        _row(
            base_ns + 270_000_000_000,
            "oracle",
            "AnswerUpdated",
            _oracle_payload(60_000.0, window_ts + 270),
        )
    )
    rows.append(
        _row(
            base_ns + 275_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_900.0, window_ts * 1000 + 275_000),
        )
    )
    rows.append(
        _row(
            base_ns + 276_000_000_000,
            "polymarket",
            "best_bid_ask",
            _polymarket_book_payload(TOKEN_UP, window_ts * 1000 + 276_000, ask=0.55),
        )
    )
    rows.append(
        _row(
            base_ns + 298_000_000_000,
            "oracle",
            "AnswerUpdated",
            _oracle_payload(60_500.0, window_ts + 298),
        )
    )


def _resolver() -> StaticTokenSideResolver:
    return StaticTokenSideResolver({TOKEN_UP: "UP", TOKEN_DOWN: "DOWN"})


async def test_walk_forward_runner_runs_one_fold(tmp_path: Path) -> None:
    """Single fold: 1-day train, 1-day test. Verifies test-only filter."""
    rows: list[dict[str, object]] = []
    # Train day window (2026-05-07): one complete window.
    _seed_one_window(rows, DAY_05_07 + 600)  # second 600 of 2026-05-07 (UTC)
    # Test day (2026-05-08): one complete window.
    _seed_one_window(rows, DAY_05_07 + 86_400 + 600)
    # Bracket end with a binance event past window close so the fold's
    # final boundary fires:
    end_ns = (DAY_05_07 + 86_400 + 1500) * 1_000_000_000
    rows.append(
        _row(
            end_ns,
            "binance",
            "trade",
            _binance_payload(60_500.0, (DAY_05_07 + 86_400 + 1500) * 1000),
        )
    )

    # Split rows by date directory:
    train_rows = [r for r in rows if int(r["ts_utc_ns"]) < (DAY_05_07 + 86_400) * 1_000_000_000]
    test_rows = [r for r in rows if int(r["ts_utc_ns"]) >= (DAY_05_07 + 86_400) * 1_000_000_000]
    _write_parquet(tmp_path / "2026-05-07" / "all_test.parquet", train_rows)
    _write_parquet(tmp_path / "2026-05-08" / "all_test.parquet", test_rows)

    runner = WalkForwardRunner(tmp_path, side_resolver=_resolver())
    folds = windows(["2026-05-07", "2026-05-08"], train_days=1, test_days=1)
    assert len(folds) == 1

    def make_strategy() -> DeterministicStrategy:
        return DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)

    fold_results = await runner.run(make_strategy, folds)
    assert len(fold_results) == 1
    fr = fold_results[0]
    assert isinstance(fr, FoldResult)
    # All result window_ts must fall in 2026-05-08.
    test_start = DAY_05_07 + 86_400
    test_end = DAY_05_07 + 86_400 * 2
    for r in fr.test_results:
        assert (
            test_start <= r.window_ts < test_end
        ), f"window_ts={r.window_ts} leaked from train fold"


async def test_walk_forward_runner_calls_strategy_reset_per_fold(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    _seed_one_window(rows, DAY_05_07 + 600)
    _seed_one_window(rows, DAY_05_07 + 86_400 + 600)
    _seed_one_window(rows, DAY_05_07 + 86_400 * 2 + 600)
    end_ns = (DAY_05_07 + 86_400 * 2 + 1500) * 1_000_000_000
    rows.append(
        _row(
            end_ns,
            "binance",
            "trade",
            _binance_payload(60_500.0, (DAY_05_07 + 86_400 * 2 + 1500) * 1000),
        )
    )
    for date, off in [("2026-05-07", 0), ("2026-05-08", 86_400), ("2026-05-09", 86_400 * 2)]:
        date_rows = [
            r
            for r in rows
            if (DAY_05_07 + off) * 1_000_000_000
            <= int(r["ts_utc_ns"])
            < (DAY_05_07 + off + 86_400) * 1_000_000_000
        ]
        _write_parquet(tmp_path / date / "all_test.parquet", date_rows)

    reset_count = {"n": 0}

    class _CountingStrategy(DeterministicStrategy):
        def reset(self) -> None:
            reset_count["n"] += 1
            super().reset()

    runner = WalkForwardRunner(tmp_path, side_resolver=_resolver())
    folds = windows(["2026-05-07", "2026-05-08", "2026-05-09"], train_days=1, test_days=1)
    assert len(folds) == 2

    await runner.run(
        lambda: _CountingStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30), folds
    )
    assert reset_count["n"] == 2  # one reset per fold


def test_aggregate_folds_sums_counters_and_recomputes_win_rate() -> None:
    fold_a = FoldResult(
        fold=WalkForwardWindow(train_dates=("2026-05-07",), test_dates=("2026-05-08",)),
        test_results=(),
        metrics={
            "n_windows": 100,
            "n_fired": 50,
            "n_filled": 30,
            "n_won": 18,
            "win_rate": 0.6,
            "total_pnl_usd": 5.0,
            "avg_pnl_usd_per_filled": 0.167,
        },
    )
    fold_b = FoldResult(
        fold=WalkForwardWindow(train_dates=("2026-05-08",), test_dates=("2026-05-09",)),
        test_results=(),
        metrics={
            "n_windows": 100,
            "n_fired": 40,
            "n_filled": 20,
            "n_won": 8,
            "win_rate": 0.4,
            "total_pnl_usd": -2.0,
            "avg_pnl_usd_per_filled": -0.1,
        },
    )
    agg = aggregate_folds([fold_a, fold_b])
    assert agg["n_folds"] == 2
    assert agg["n_windows"] == 200
    assert agg["n_fired"] == 90
    assert agg["n_filled"] == 50
    assert agg["n_won"] == 26
    assert agg["win_rate"] == pytest.approx(26 / 50)
    assert agg["total_pnl_usd"] == pytest.approx(3.0)


def test_aggregate_folds_handles_zero_filled() -> None:
    fold = FoldResult(
        fold=WalkForwardWindow(train_dates=("d",), test_dates=("d",)),
        test_results=(),
        metrics={"n_windows": 0, "n_fired": 0, "n_filled": 0, "n_won": 0, "total_pnl_usd": 0.0},
    )
    agg = aggregate_folds([fold])
    assert agg["win_rate"] == 0.0
    assert agg["avg_pnl_usd_per_filled"] == 0.0

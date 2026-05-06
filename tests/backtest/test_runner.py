"""Tests for polymarket_bot.backtest.runner.BacktestRunner.

Drives the runner through synthetic Parquet fixtures + the real
DeterministicStrategy. Covers: window resolution from oracle samples,
fire-and-fill end-to-end, fire-but-no-fill (limit too low), no-fire,
P&L sign correctness for winning + losing outcomes, aggregate_metrics
shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from polymarket_bot.backtest.fills import FillSimulator
from polymarket_bot.backtest.replay import ReplayEngine, StaticTokenSideResolver
from polymarket_bot.backtest.runner import (
    BacktestRunner,
    aggregate_metrics,
)
from polymarket_bot.strategies.deterministic import DeterministicStrategy

WINDOW_TS = 1_715_000_100  # exact 300s multiple
NEXT_WINDOW_TS = WINDOW_TS + 300
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def _row(ts: int, source: str, kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "ts_utc_ns": ts,
        "received_at_ns": ts,
        "source": source,
        "kind": kind,
        "payload_json": json.dumps(payload, separators=(",", ":")),
    }


def _binance_row(ts_offset_s: float, price: float) -> dict[str, object]:
    ts = WINDOW_OPEN_NS + int(ts_offset_s * 1_000_000_000)
    return _row(
        ts,
        "binance",
        "trade",
        {"e": "trade", "T": int(ts / 1_000_000), "p": str(price), "q": "0.001"},
    )


def _oracle_row(ts_offset_s: float, price_usd: float) -> dict[str, object]:
    ts = WINDOW_OPEN_NS + int(ts_offset_s * 1_000_000_000)
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
        "data": "0x" + (int(WINDOW_TS + ts_offset_s)).to_bytes(32, "big").hex(),
        "blockHash": "0x" + "11" * 32,
        "blockNumber": "0x1",
        "transactionHash": "0x" + "22" * 32,
        "transactionIndex": "0x0",
        "logIndex": "0x0",
        "removed": False,
    }
    return _row(ts, "oracle", "AnswerUpdated", log)


def _polymarket_book_row(ts_offset_s: float, asset_id: str, best_ask: float) -> dict[str, object]:
    ts = WINDOW_OPEN_NS + int(ts_offset_s * 1_000_000_000)
    payload = {
        "event_type": "best_bid_ask",
        "asset_id": asset_id,
        "market": "0xabc",
        "best_bid": str(best_ask - 0.02),
        "best_ask": str(best_ask),
        "spread": "0.02",
        "timestamp": str(int(ts / 1_000_000)),
    }
    return _row(ts, "polymarket", "best_bid_ask", payload)


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "ts_utc_ns": [int(r["ts_utc_ns"]) for r in rows],
            "received_at_ns": [int(r.get("received_at_ns", r["ts_utc_ns"])) for r in rows],
            "source": [str(r["source"]) for r in rows],
            "kind": [str(r["kind"]) for r in rows],
            "payload_json": [str(r["payload_json"]) for r in rows],
        }
    ).write_parquet(path)


def _make_replay(tmp_path: Path) -> ReplayEngine:
    return ReplayEngine(
        tmp_path,
        ["2026-05-07"],
        side_resolver=StaticTokenSideResolver({TOKEN_UP: "UP", TOKEN_DOWN: "DOWN"}),
    )


async def test_runner_fires_fills_and_settles_winning_up_window(tmp_path: Path) -> None:
    """Spot rises +1% from window open; oracle confirms; UP side wins → positive P&L."""
    rows: list[dict[str, object]] = []
    rows.append(_binance_row(1.0, 60_000.0))  # window-open spot
    rows.append(_polymarket_book_row(1.0, TOKEN_UP, best_ask=0.55))
    rows.append(_polymarket_book_row(1.0, TOKEN_DOWN, best_ask=0.46))
    rows.append(_oracle_row(2.0, 60_000.0))  # window-open oracle
    rows.append(_oracle_row(270.0, 60_000.0))  # late oracle (still flat)
    rows.append(_binance_row(275.0, 60_600.0))  # +1% spot ⇒ composite > threshold
    # Book update inside TTL so the simulator fills:
    rows.append(_polymarket_book_row(276.0, TOKEN_UP, best_ask=0.55))
    # Window close — resolution oracle:
    rows.append(_oracle_row(298.0, 60_500.0))  # close oracle > open ⇒ UP wins

    # Bracket with a sentinel event past window close to force a boundary:
    rows.append(_binance_row(310.0, 60_500.0))  # next-window event triggers close
    _write(tmp_path / "2026-05-07" / "all_test.parquet", rows)

    strategy = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    runner = BacktestRunner(
        _make_replay(tmp_path), simulator=FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.0)
    )

    results = await runner.run(strategy)

    assert len(results) >= 1
    fired = [r for r in results if r.fired]
    filled = [r for r in fired if r.fill is not None]
    assert filled, f"expected at least one filled trade; got results: {results}"
    target = filled[0]
    assert target.side == "UP"
    assert target.resolution == "UP"
    assert target.pnl_usd > 0  # winning trade


async def test_runner_settles_losing_when_oracle_reverses(tmp_path: Path) -> None:
    """Strategy fires UP, but oracle close < open ⇒ DOWN resolution ⇒ negative P&L."""
    rows: list[dict[str, object]] = []
    rows.append(_binance_row(1.0, 60_000.0))
    rows.append(_polymarket_book_row(1.0, TOKEN_UP, best_ask=0.55))
    rows.append(_polymarket_book_row(1.0, TOKEN_DOWN, best_ask=0.46))
    rows.append(_oracle_row(2.0, 60_000.0))
    rows.append(_oracle_row(270.0, 60_000.0))
    rows.append(_binance_row(275.0, 60_600.0))  # +1% spot
    rows.append(_polymarket_book_row(276.0, TOKEN_UP, best_ask=0.55))
    rows.append(_oracle_row(298.0, 59_500.0))  # close oracle < open → DOWN wins

    rows.append(_binance_row(310.0, 59_500.0))  # boundary trigger
    _write(tmp_path / "2026-05-07" / "all_test.parquet", rows)

    strategy = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    runner = BacktestRunner(
        _make_replay(tmp_path), simulator=FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.0)
    )

    results = await runner.run(strategy)
    filled = [r for r in results if r.fill is not None]
    assert filled
    target = filled[0]
    assert target.side == "UP"
    assert target.resolution == "DOWN"
    assert target.pnl_usd < 0


async def test_runner_records_no_fire_for_quiet_window(tmp_path: Path) -> None:
    """Spot moves <0.1% — composite below threshold — no decision."""
    rows: list[dict[str, object]] = []
    rows.append(_binance_row(1.0, 60_000.0))
    rows.append(_polymarket_book_row(1.0, TOKEN_UP, best_ask=0.55))
    rows.append(_polymarket_book_row(1.0, TOKEN_DOWN, best_ask=0.46))
    rows.append(_oracle_row(2.0, 60_000.0))
    rows.append(_binance_row(275.0, 60_010.0))  # +0.017% — too small
    rows.append(_oracle_row(298.0, 60_005.0))

    rows.append(_binance_row(310.0, 60_005.0))
    _write(tmp_path / "2026-05-07" / "all_test.parquet", rows)

    strategy = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    runner = BacktestRunner(_make_replay(tmp_path))
    results = await runner.run(strategy)

    fired = [r for r in results if r.fired]
    assert fired == []


async def test_aggregate_metrics_shape(tmp_path: Path) -> None:
    rows: list[dict[str, object]] = []
    rows.append(_binance_row(1.0, 60_000.0))
    rows.append(_polymarket_book_row(1.0, TOKEN_UP, best_ask=0.55))
    rows.append(_polymarket_book_row(1.0, TOKEN_DOWN, best_ask=0.46))
    rows.append(_oracle_row(2.0, 60_000.0))
    rows.append(_oracle_row(270.0, 60_000.0))
    rows.append(_binance_row(275.0, 60_600.0))
    rows.append(_polymarket_book_row(276.0, TOKEN_UP, best_ask=0.55))
    rows.append(_oracle_row(298.0, 60_500.0))
    rows.append(_binance_row(310.0, 60_500.0))
    _write(tmp_path / "2026-05-07" / "all_test.parquet", rows)

    strategy = DeterministicStrategy(threshold_pct=0.5, ttl_low_s=10, ttl_high_s=30)
    runner = BacktestRunner(
        _make_replay(tmp_path), simulator=FillSimulator(fee_bps=0.0, impact_per_5usd_per_5k=0.0)
    )
    results = await runner.run(strategy)
    metrics = aggregate_metrics(results)

    expected_keys = {
        "n_windows",
        "n_fired",
        "n_filled",
        "n_won",
        "win_rate",
        "total_pnl_usd",
        "avg_pnl_usd_per_filled",
    }
    assert set(metrics.keys()) == expected_keys
    assert metrics["n_filled"] >= 1
    assert metrics["win_rate"] in (0.0, 1.0)  # only one filled trade in this fixture

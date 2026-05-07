"""Round-trip tests for polymarket_bot._paper.decision_log.DecisionLog.

Cover: fired+settled lines write+read; append-only behaviour across
re-opens; closed instance rejects writes; per-UTC-date file selection;
join_fired_settled pairs records correctly even with interleaved order;
read_jsonl tolerates blank lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from polymarket_bot._paper.decision_log import (
    DecisionLog,
    join_fired_settled,
    read_jsonl,
)
from polymarket_bot.backtest.types import Decision, Fill

ASSET = "0x" + "ab" * 31  # 64 hex chars
WINDOW_TS = 1_762_540_500
DEC_TS_NS = WINDOW_TS * 1_000_000_000 + 12_000_000_000  # +12s into window


def _decision(ts_offset_ns: int = 0) -> Decision:
    return Decision(
        ts_utc_ns=DEC_TS_NS + ts_offset_ns,
        asset_id=ASSET,
        side="BUY",
        size_usd=5.0,
        price_limit=0.51,
        ttl_s=18,
        rationale="composite=+0.612pct (|.|>=0.60) ttl=18s side=UP",
    )


def _fill(price: float = 0.505) -> Fill:
    return Fill(
        ts_utc_ns=DEC_TS_NS + 100_000_000,
        asset_id=ASSET,
        size_filled=5.0 / price,
        price_filled=price,
        fee_usd=0.001,
    )


def test_round_trip_fired_and_settled(tmp_path: Path) -> None:
    log = DecisionLog(root=tmp_path)
    decision_id = log.record_fired(
        decision=_decision(),
        side="UP",
        window_ts=WINDOW_TS,
        snapshot={"spot_now": 67432.10, "best_ask": 0.505},
        composite_pct=0.612,
        fill=_fill(),
    )
    log.record_settled(
        decision_id=decision_id,
        window_ts=WINDOW_TS,
        settled_ts_ns=(WINDOW_TS + 300) * 1_000_000_000,
        open_oracle=67400.00,
        close_oracle=67450.00,
        resolution="UP",
        fill_at_settle=_fill(),
        pnl_usd=4.396,
    )
    log.close()

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    records = list(read_jsonl(files[0]))
    assert len(records) == 2

    fired, settled = records
    assert fired["kind"] == "fired"
    assert fired["decision_id"] == decision_id
    assert fired["window_ts"] == WINDOW_TS
    assert fired["asset_id"] == ASSET
    assert fired["side"] == "UP"
    assert fired["size_usd"] == 5.0
    assert fired["price_limit"] == 0.51
    assert fired["ttl_s"] == 18
    assert fired["composite_pct"] == 0.612
    assert fired["fill"]["price_filled"] == 0.505
    assert fired["snapshot"]["best_ask"] == 0.505

    assert settled["kind"] == "settled"
    assert settled["decision_id"] == decision_id
    assert settled["resolution"] == "UP"
    assert settled["pnl_usd"] == 4.396
    assert settled["fill_at_settle"]["price_filled"] == 0.505


def test_three_synthetic_decisions_round_trip(tmp_path: Path) -> None:
    log = DecisionLog(root=tmp_path)
    ids = []
    for i in range(3):
        did = log.record_fired(
            decision=_decision(ts_offset_ns=i * 10_000_000_000),
            side="UP" if i % 2 == 0 else "DOWN",
            window_ts=WINDOW_TS + i * 300,
            snapshot={"i": i},
            composite_pct=0.6 + i * 0.1,
            fill=_fill(price=0.5 + i * 0.01),
        )
        ids.append(did)
        log.record_settled(
            decision_id=did,
            window_ts=WINDOW_TS + i * 300,
            settled_ts_ns=(WINDOW_TS + (i + 1) * 300) * 1_000_000_000,
            open_oracle=67000.0,
            close_oracle=67000.0 + i * 50,
            resolution="UP",
            fill_at_settle=_fill(price=0.5 + i * 0.01),
            pnl_usd=float(i),
        )
    log.close()

    files = sorted(tmp_path.glob("*.jsonl"))
    all_records = []
    for f in files:
        all_records.extend(read_jsonl(f))
    assert len(all_records) == 6
    fired = [r for r in all_records if r["kind"] == "fired"]
    settled = [r for r in all_records if r["kind"] == "settled"]
    assert {r["decision_id"] for r in fired} == set(ids)
    assert {r["decision_id"] for r in settled} == set(ids)


def test_append_across_reopen(tmp_path: Path) -> None:
    log1 = DecisionLog(root=tmp_path)
    log1.record_fired(
        decision=_decision(),
        side="UP",
        window_ts=WINDOW_TS,
        snapshot={"k": 1},
        composite_pct=0.6,
        fill=None,
    )
    log1.close()

    log2 = DecisionLog(root=tmp_path)
    log2.record_fired(
        decision=_decision(ts_offset_ns=60_000_000_000),
        side="DOWN",
        window_ts=WINDOW_TS + 300,
        snapshot={"k": 2},
        composite_pct=-0.7,
        fill=None,
    )
    log2.close()

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1  # same UTC date
    records = list(read_jsonl(files[0]))
    assert len(records) == 2  # both decisions present
    assert records[0]["snapshot"] == {"k": 1}
    assert records[1]["snapshot"] == {"k": 2}


def test_writes_after_close_raise(tmp_path: Path) -> None:
    log = DecisionLog(root=tmp_path)
    log.close()
    with pytest.raises(RuntimeError, match="closed"):
        log.record_fired(
            decision=_decision(),
            side="UP",
            window_ts=WINDOW_TS,
            snapshot={},
            composite_pct=0.0,
            fill=None,
        )


def test_join_fired_settled_pairs_records() -> None:
    records = [
        {"kind": "fired", "decision_id": "a", "window_ts": 1},
        {"kind": "settled", "decision_id": "b", "window_ts": 2},
        {"kind": "fired", "decision_id": "b", "window_ts": 2},
        {"kind": "settled", "decision_id": "a", "window_ts": 1},
        {"kind": "fired", "decision_id": "c", "window_ts": 3},  # no settled match
    ]
    pairs = dict((f["decision_id"], s) for f, s in join_fired_settled(records))
    assert pairs["a"] is not None
    assert pairs["a"]["window_ts"] == 1
    assert pairs["b"] is not None
    assert pairs["b"]["window_ts"] == 2
    assert pairs["c"] is None


def test_read_jsonl_tolerates_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\n\n{"b":2}\n   \n{"c":3}\n', encoding="utf-8")
    records = list(read_jsonl(p))
    assert records == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_per_utc_date_file_split(tmp_path: Path) -> None:
    """Decisions on different UTC dates split into different files."""
    log = DecisionLog(root=tmp_path)
    # 2026-05-07 00:01 UTC
    day7_ns = (1_778_198_400 + 60) * 1_000_000_000
    # 2026-05-08 00:01 UTC (24h + 60s later)
    day8_ns = day7_ns + 86_400 * 1_000_000_000
    log.record_fired(
        decision=Decision(
            ts_utc_ns=day7_ns,
            asset_id=ASSET,
            side="BUY",
            size_usd=5.0,
            price_limit=0.51,
            ttl_s=18,
            rationale="side=UP",
        ),
        side="UP",
        window_ts=day7_ns // 1_000_000_000 // 300 * 300,
        snapshot={},
        composite_pct=0.6,
        fill=None,
    )
    log.record_fired(
        decision=Decision(
            ts_utc_ns=day8_ns,
            asset_id=ASSET,
            side="BUY",
            size_usd=5.0,
            price_limit=0.51,
            ttl_s=18,
            rationale="side=DOWN",
        ),
        side="DOWN",
        window_ts=day8_ns // 1_000_000_000 // 300 * 300,
        snapshot={},
        composite_pct=-0.6,
        fill=None,
    )
    log.close()

    files = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert len(files) == 2
    assert all(name.endswith(".jsonl") for name in files)

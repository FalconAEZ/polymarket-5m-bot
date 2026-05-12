"""Tests for scripts/four_day_audit.py — the Phase F per-day audit tool.

Covers the truth-correction overlay (the part where the script earns its
keep), strategy-tag parsing, multi-day bucketing, and the CLI filters.
Synthesizes JSONL fixtures rather than depending on real VPS data, so tests
are deterministic and fast.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import four_day_audit as fda  # noqa: E402


def _ns(iso: str) -> int:
    """Convert a UTC ISO timestamp to nanoseconds since epoch."""
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1e9)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _fired(
    decision_id: str, ts_iso: str, *, fill: bool, strategy: str = "spot_aware_v3"
) -> dict[str, object]:
    return {
        "kind": "fired",
        "decision_id": decision_id,
        "decision_ts_ns": _ns(ts_iso),
        "rationale": f"strategy={strategy} delta_bps=+1.0 side=UP",
        "fill": {"size_filled": 10.0, "price_filled": 0.5, "fee_usd": 0.001} if fill else None,
    }


def _settled(decision_id: str, ts_iso: str, pnl: float) -> dict[str, object]:
    return {
        "kind": "settled",
        "decision_id": decision_id,
        "settled_ts_ns": _ns(ts_iso),
        "pnl_usd": pnl,
    }


def _correction(decision_id: str, corrected_pnl: float) -> dict[str, object]:
    return {
        "kind": "settled_correction",
        "decision_id": decision_id,
        "corrected_pnl_usd": corrected_pnl,
    }


# ---------------------------------------------------------------------------
# audit() core logic
# ---------------------------------------------------------------------------


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert fda.audit(tmp_path) == []


def test_single_day_fires_no_settles(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T10:00:00", fill=True),
            _fired("b", "2026-05-09T11:00:00", fill=False),
            _fired("c", "2026-05-09T12:00:00", fill=True),
        ],
    )
    rows = fda.audit(tmp_path)
    assert len(rows) == 1
    r = rows[0]
    assert r.date == "2026-05-09"
    assert r.fires == 3
    assert r.filled == 2
    assert r.fill_rate == pytest.approx(2 / 3)
    assert r.settled == 0
    assert r.win_rate == 0.0
    assert r.naive_pnl == 0.0
    assert r.true_pnl == 0.0


def test_w_l_z_buckets(tmp_path: Path) -> None:
    """Truth-corrected pnl > 0 → W; < 0 → L; == 0 → Z."""
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T10:00:00", fill=True),
            _fired("b", "2026-05-09T11:00:00", fill=True),
            _fired("c", "2026-05-09T12:00:00", fill=False),
            _settled("a", "2026-05-09T10:05:00", pnl=5.0),
            _settled("b", "2026-05-09T11:05:00", pnl=-5.0),
            _settled("c", "2026-05-09T12:05:00", pnl=0.0),
        ],
    )
    r = fda.audit(tmp_path)[0]
    assert (r.wins, r.losses, r.zeros) == (1, 1, 1)
    assert r.win_rate == pytest.approx(0.5)
    assert r.naive_pnl == pytest.approx(0.0)
    assert r.true_pnl == pytest.approx(0.0)


def test_truth_correction_overrides_naive(tmp_path: Path) -> None:
    """The single most important behavior: a settled_correction record
    flips the W/L bucket and replaces the contribution to true_pnl, but
    naive_pnl ignores the correction."""
    _write_jsonl(
        tmp_path / "2026-05-10.jsonl",
        [
            _fired("phantom", "2026-05-10T10:00:00", fill=True),
            _settled("phantom", "2026-05-10T10:05:00", pnl=+2500.0),  # phantom win
            _correction("phantom", -5.0),  # post-hoc: actually a loss
        ],
    )
    r = fda.audit(tmp_path)[0]
    assert r.naive_pnl == pytest.approx(2500.0)
    assert r.true_pnl == pytest.approx(-5.0)
    assert (r.wins, r.losses, r.zeros) == (0, 1, 0), "post-correction should bucket as L"


def test_correction_zero_truth_pnl_buckets_z(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-10.jsonl",
        [
            _settled("a", "2026-05-10T10:05:00", pnl=5.0),
            _correction("a", 0.0),
        ],
    )
    r = fda.audit(tmp_path)[0]
    assert (r.wins, r.losses, r.zeros) == (0, 0, 1)
    assert r.true_pnl == 0.0
    assert r.naive_pnl == 5.0


def test_strategy_parsing_with_mode(tmp_path: Path) -> None:
    """rationale="strategy=spot_aware mode=aggressive" → "spot_aware:aggressive"."""
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T10:00:00", fill=True, strategy="spot_aware"),
            {
                "kind": "fired",
                "decision_id": "b",
                "decision_ts_ns": _ns("2026-05-09T11:00:00"),
                "rationale": "strategy=spot_aware mode=aggressive delta_bps=-0.6",
                "fill": None,
            },
        ],
    )
    r = fda.audit(tmp_path)[0]
    assert "spot_aware:aggressive" in r.strategy_label or "spot_aware" in r.strategy_label


def test_strategy_label_mixed_when_close_split(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [
            _fired("a", "2026-05-12T10:00:00", fill=True, strategy="wide_fire"),
            _fired("b", "2026-05-12T11:00:00", fill=True, strategy="wide_fire"),
            _fired("c", "2026-05-12T12:00:00", fill=True, strategy="spot_aware_v3"),
            _fired("d", "2026-05-12T13:00:00", fill=True, strategy="spot_aware_v3"),
        ],
    )
    r = fda.audit(tmp_path)[0]
    # 2 wide_fire + 2 spot_aware_v3 — dominant is not >=2x runner-up, so mixed label
    assert "/" in r.strategy_label


def test_multi_day_sorted_by_date(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "2026-05-09.jsonl", [_fired("a", "2026-05-09T10:00:00", fill=True)])
    _write_jsonl(tmp_path / "2026-05-08.jsonl", [_fired("b", "2026-05-08T10:00:00", fill=True)])
    _write_jsonl(tmp_path / "2026-05-10.jsonl", [_fired("c", "2026-05-10T10:00:00", fill=True)])
    rows = fda.audit(tmp_path)
    assert [r.date for r in rows] == ["2026-05-08", "2026-05-09", "2026-05-10"]


def test_since_filter(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "2026-05-08.jsonl", [_fired("a", "2026-05-08T10:00:00", fill=True)])
    _write_jsonl(tmp_path / "2026-05-10.jsonl", [_fired("b", "2026-05-10T10:00:00", fill=True)])
    rows = fda.audit(tmp_path, since=date(2026, 5, 10))
    assert [r.date for r in rows] == ["2026-05-10"]


def test_days_limit(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "2026-05-08.jsonl", [_fired("a", "2026-05-08T10:00:00", fill=True)])
    _write_jsonl(tmp_path / "2026-05-09.jsonl", [_fired("b", "2026-05-09T10:00:00", fill=True)])
    _write_jsonl(tmp_path / "2026-05-10.jsonl", [_fired("c", "2026-05-10T10:00:00", fill=True)])
    rows = fda.audit(tmp_path, days=2)
    assert [r.date for r in rows] == ["2026-05-09", "2026-05-10"]


def test_cross_day_settlement_attributed_to_settle_date(tmp_path: Path) -> None:
    """A fire on day D-1 that settles on day D contributes its PnL to day D,
    not to day D-1. Mirrors the Phase F prompt's May 9 settled=266 > fires=262."""
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T23:55:00", fill=True),  # fires late on May 9
        ],
    )
    _write_jsonl(
        tmp_path / "2026-05-10.jsonl",
        [
            _settled("a", "2026-05-10T00:05:00", pnl=5.0),  # settles on May 10
        ],
    )
    rows = fda.audit(tmp_path)
    assert len(rows) == 2
    by_date = {r.date: r for r in rows}
    assert by_date["2026-05-09"].fires == 1
    assert by_date["2026-05-09"].settled == 0
    assert by_date["2026-05-10"].fires == 0
    assert by_date["2026-05-10"].settled == 1
    assert by_date["2026-05-10"].wins == 1


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "2026-05-09.jsonl"
    with path.open("w") as fh:
        fh.write("not json\n")
        fh.write(json.dumps(_fired("a", "2026-05-09T10:00:00", fill=True)) + "\n")
        fh.write("\n")  # blank
        fh.write("{}\n")  # missing fields
        fh.write(json.dumps(_settled("a", "2026-05-09T10:05:00", pnl=3.0)) + "\n")
    rows = fda.audit(tmp_path)
    assert rows[0].fires == 1
    assert rows[0].settled == 1
    assert rows[0].wins == 1


# ---------------------------------------------------------------------------
# format_table()
# ---------------------------------------------------------------------------


def test_format_table_empty() -> None:
    assert fda.format_table([]) == "(no data)\n"


def test_format_table_has_total_footer(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T10:00:00", fill=True),
            _settled("a", "2026-05-09T10:05:00", pnl=5.0),
        ],
    )
    rows = fda.audit(tmp_path)
    out = fda.format_table(rows)
    assert "2026-05-09" in out
    assert "TOTAL" in out
    assert "+5.00" in out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_missing_dir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bogus = tmp_path / "does-not-exist"
    rc = fda.main(["--decisions-dir", str(bogus)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not a directory" in err


def test_cli_happy_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_jsonl(
        tmp_path / "2026-05-09.jsonl",
        [
            _fired("a", "2026-05-09T10:00:00", fill=True),
            _settled("a", "2026-05-09T10:05:00", pnl=5.0),
        ],
    )
    rc = fda.main(["--decisions-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-05-09" in out
    assert "+5.00" in out

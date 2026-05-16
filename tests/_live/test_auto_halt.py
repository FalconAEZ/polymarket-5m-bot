"""Tests for L.5 daily-PnL auto-halt — design/L.5-daily-pnl-auto-halt.md §8.

Covers the public `check_daily_pnl_gate` surface + the production
`JsonlDailyPnlReader` against synthetic decisions-resolved files.
Anti-vibe rule #10: all I/O behind injected protocols; tests use fakes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from polymarket_bot._live.alerter.halt import halt_sentinel_present, write_halt_sentinel
from polymarket_bot._live.auto_halt import (
    AutoHaltResult,
    JsonlDailyPnlReader,
    SentinelHaltWriter,
    check_daily_pnl_gate,
)
from polymarket_bot.alerts.types import Alert, Level

# ---------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------


@dataclass
class FakePnlReader:
    pnl: float = 0.0
    raises: Exception | None = None

    def read(self, day_utc: date) -> float:
        if self.raises is not None:
            raise self.raises
        return self.pnl


@dataclass
class FakeHaltWriter:
    written: list[dict[str, object]] = field(default_factory=list)
    raises: Exception | None = None

    def write(self, *, reason: str, ts_ns: int, by: str) -> None:
        if self.raises is not None:
            raise self.raises
        self.written.append({"reason": reason, "ts_ns": ts_ns, "by": by})


@dataclass
class FakeAlertSink:
    published: list[Alert] = field(default_factory=list)
    raises: Exception | None = None

    def publish(self, alert: Alert) -> None:
        if self.raises is not None:
            raise self.raises
        self.published.append(alert)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------
# check_daily_pnl_gate
# ---------------------------------------------------------------------


def test_halt_fires_when_pnl_below_threshold() -> None:
    reader = FakePnlReader(pnl=-50.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    result = check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    assert isinstance(result, AutoHaltResult)
    assert result.halted is True
    assert result.pnl_usd == -50.0
    assert "daily-pnl-gate-tripped" in result.reason
    assert len(writer.written) == 1
    assert len(alerts.published) == 1
    assert alerts.published[0].level == Level.CRITICAL


def test_halt_does_not_fire_when_pnl_above_threshold() -> None:
    reader = FakePnlReader(pnl=-20.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    result = check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    assert result.halted is False
    assert result.pnl_usd == -20.0
    assert result.reason == "pnl-above-threshold"
    assert writer.written == []
    assert alerts.published == []


def test_halt_fires_at_exact_threshold() -> None:
    reader = FakePnlReader(pnl=-30.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    result = check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    # pnl == threshold: at-or-below semantics → halted.
    assert result.halted is True
    assert len(writer.written) == 1


def test_reader_error_returns_halted_false_and_publishes_error() -> None:
    reader = FakePnlReader(raises=RuntimeError("disk full"))
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    result = check_daily_pnl_gate(
        now_ns=42,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    assert result.halted is False
    assert result.reason == "reader-failed"
    assert writer.written == []
    assert len(alerts.published) == 1
    assert alerts.published[0].level == Level.ERROR


def test_halt_writer_error_publishes_error_alert() -> None:
    reader = FakePnlReader(pnl=-50.0)
    writer = FakeHaltWriter(raises=OSError("fs readonly"))
    alerts = FakeAlertSink()
    result = check_daily_pnl_gate(
        now_ns=42,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    # No false-positive halt when sentinel write fails.
    assert result.halted is False
    assert result.reason == "sentinel-write-failed"
    # ERROR alert, not the CRITICAL trip alert.
    assert len(alerts.published) == 1
    assert alerts.published[0].level == Level.ERROR


def test_sentinel_written_with_by_field() -> None:
    reader = FakePnlReader(pnl=-99.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    assert writer.written[0]["by"] == "auto-halt-daily-pnl"
    assert "2026-05-16" in writer.written[0]["reason"]  # type: ignore[operator]


def test_alert_publish_uses_critical_level_with_fields() -> None:
    reader = FakePnlReader(pnl=-100.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink()
    check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    a = alerts.published[0]
    assert a.level == Level.CRITICAL
    assert a.source == "auto_halt.daily_pnl_gate"
    assert a.fields["pnl_usd"] == -100.0
    assert a.fields["threshold_usd"] == -30.0
    assert a.fields["day_utc"] == "2026-05-16"


def test_alert_publish_failure_does_not_block_halt() -> None:
    reader = FakePnlReader(pnl=-100.0)
    writer = FakeHaltWriter()
    alerts = FakeAlertSink(raises=RuntimeError("redis down"))
    result = check_daily_pnl_gate(
        now_ns=1_000_000,
        today_utc=date(2026, 5, 16),
        pnl_reader=reader,
        halt_writer=writer,
        alerts=alerts,
        threshold_usd=-30.0,
    )
    # Halt is the primary action; best-effort alert raising does not undo it.
    assert result.halted is True
    assert len(writer.written) == 1


# ---------------------------------------------------------------------
# halt.py backward-compat
# ---------------------------------------------------------------------


def test_halt_py_by_param_defaults_to_telegram(tmp_path: Path) -> None:
    target = tmp_path / "halt.sentinel"
    write_halt_sentinel("operator request", 12345, path=target)
    payload = json.loads(target.read_text())
    assert payload["halted_by"] == "telegram-/halt"  # backward-compat default


def test_halt_py_by_param_override(tmp_path: Path) -> None:
    target = tmp_path / "halt.sentinel"
    write_halt_sentinel("auto trip", 99, by="auto-halt-daily-pnl", path=target)
    payload = json.loads(target.read_text())
    assert payload["halted_by"] == "auto-halt-daily-pnl"
    assert payload["reason"] == "auto trip"


# ---------------------------------------------------------------------
# JsonlDailyPnlReader
# ---------------------------------------------------------------------


def test_jsonl_reader_missing_file_returns_zero(tmp_path: Path) -> None:
    reader = JsonlDailyPnlReader(resolved_dir=tmp_path)
    assert reader.read(date(2026, 5, 16)) == 0.0


def test_jsonl_reader_sums_settled_records(tmp_path: Path) -> None:
    day = date(2026, 5, 16)
    f = tmp_path / f"{day.isoformat()}.jsonl"
    f.write_text(
        "\n".join(
            [
                json.dumps({"kind": "settled", "decision_id": "a", "pnl_usd": 10.0}),
                json.dumps({"kind": "settled", "decision_id": "b", "pnl_usd": -5.0}),
                json.dumps({"kind": "fired", "decision_id": "c"}),  # ignored
            ]
        )
    )
    reader = JsonlDailyPnlReader(resolved_dir=tmp_path)
    assert reader.read(day) == pytest.approx(5.0)


def test_jsonl_reader_prefers_correction_over_settled(tmp_path: Path) -> None:
    day = date(2026, 5, 16)
    f = tmp_path / f"{day.isoformat()}.jsonl"
    f.write_text(
        "\n".join(
            [
                json.dumps({"kind": "settled", "decision_id": "a", "pnl_usd": 10.0}),
                json.dumps(
                    {"kind": "settled_correction", "decision_id": "a", "corrected_pnl_usd": -3.0}
                ),
                json.dumps({"kind": "settled", "decision_id": "b", "pnl_usd": 7.0}),
            ]
        )
    )
    reader = JsonlDailyPnlReader(resolved_dir=tmp_path)
    # a is corrected -3, b is settled 7. Total 4.
    assert reader.read(day) == pytest.approx(4.0)


def test_jsonl_reader_skips_malformed_lines(tmp_path: Path) -> None:
    day = date(2026, 5, 16)
    f = tmp_path / f"{day.isoformat()}.jsonl"
    f.write_text(
        "\n".join(
            [
                "{ not json",
                json.dumps({"kind": "settled", "decision_id": "a", "pnl_usd": 4.0}),
                "",
            ]
        )
    )
    reader = JsonlDailyPnlReader(resolved_dir=tmp_path)
    assert reader.read(day) == pytest.approx(4.0)


# ---------------------------------------------------------------------
# SentinelHaltWriter integration
# ---------------------------------------------------------------------


def test_sentinel_halt_writer_writes_atomically(tmp_path: Path) -> None:
    sentinel_path = tmp_path / "halt.sentinel"
    writer = SentinelHaltWriter(path=sentinel_path)
    writer.write(reason="r", ts_ns=42, by="x")
    assert halt_sentinel_present(sentinel_path)
    tmp = sentinel_path.with_suffix(sentinel_path.suffix + ".tmp")
    assert not tmp.exists()
    payload = json.loads(sentinel_path.read_text())
    assert payload["halted_by"] == "x"
    assert payload["reason"] == "r"
    assert payload["halted_at_ns"] == 42

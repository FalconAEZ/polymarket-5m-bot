"""Tests for polymarket_bot.dashboard.rtt_loader.

Reads the JSONL written by rtt_collector. Empty / missing / malformed /
mixed-provider cases plus the tail-bytes optimization. Per design/
dashboard-v2.md §10.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_bot.dashboard.rtt_loader import RttSample, load_provider_rtt

NOW = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)


def _line(provider: str, ts: datetime, *, rtt_ms: float | None = 100.0, ok: bool = True) -> str:
    return json.dumps(
        {
            "provider": provider,
            "ts_utc": ts.isoformat(),
            "rtt_ms": rtt_ms,
            "status_code": 200 if ok else None,
            "ok": ok,
        }
    )


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_provider_rtt(tmp_path) == {}


def test_basic_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    lines = [
        _line("Binance", NOW - timedelta(seconds=5), rtt_ms=120.0),
        _line("Coinbase", NOW - timedelta(seconds=5), rtt_ms=240.0),
    ]
    f.write_text("\n".join(lines) + "\n")
    out = load_provider_rtt(tmp_path, lookback_s=60.0)
    # The lookback_s logic uses NOW from datetime.now() — so we use a generous
    # window. The samples are 5s old which is well within typical lookback.
    assert "Binance" in out
    assert "Coinbase" in out
    assert isinstance(out["Binance"][0], RttSample)
    assert out["Binance"][0].rtt_ms == 120.0


def test_old_samples_filtered_by_lookback(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    f.write_text(_line("Binance", datetime(2020, 1, 1, tzinfo=UTC)) + "\n")
    out = load_provider_rtt(tmp_path, lookback_s=600.0)
    assert out == {}


def test_malformed_lines_skipped(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    f.write_text(
        "{not valid json\n"
        + _line("Binance", datetime.now(tz=UTC), rtt_ms=100.0)
        + "\n"
        + '{"provider": 5}\n'  # provider not a string
        + "\n"  # blank line
    )
    out = load_provider_rtt(tmp_path)
    assert "Binance" in out
    assert len(out["Binance"]) == 1


def test_failed_ping_recorded_as_none_rtt(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    now = datetime.now(tz=UTC)
    f.write_text(_line("Binance", now, rtt_ms=None, ok=False) + "\n")
    out = load_provider_rtt(tmp_path)
    assert out["Binance"][0].rtt_ms is None
    assert out["Binance"][0].status_code is None


def test_tail_bytes_optimization(tmp_path: Path) -> None:
    """A huge file should still load only the trailing window."""
    f = tmp_path / "provider_rtt.jsonl"
    pad = "X" * 100  # padding to bloat each line
    now = datetime.now(tz=UTC)
    lines = [
        json.dumps(
            {
                "provider": "Binance",
                "ts_utc": (now - timedelta(seconds=i)).isoformat(),
                "rtt_ms": 100.0 + i,
                "status_code": 200,
                "ok": True,
                "_pad": pad,
            }
        )
        for i in range(2000, 0, -1)  # oldest first
    ]
    f.write_text("\n".join(lines) + "\n")
    # max_bytes is 256KB by default; the file is ~400KB, so we read the tail.
    out = load_provider_rtt(tmp_path, max_per_provider=10, lookback_s=99999.0)
    assert "Binance" in out
    assert len(out["Binance"]) == 10
    # Most recent sample should be ~1s old (i=1)
    last = out["Binance"][-1]
    age_s = (now - last.ts_utc).total_seconds()
    assert -0.5 <= age_s <= 1.5


def test_max_per_provider_cap(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    now = datetime.now(tz=UTC)
    lines = [
        _line("Binance", now - timedelta(seconds=i), rtt_ms=float(i)) for i in range(20, 0, -1)
    ]
    f.write_text("\n".join(lines) + "\n")
    out = load_provider_rtt(tmp_path, max_per_provider=5)
    assert len(out["Binance"]) == 5

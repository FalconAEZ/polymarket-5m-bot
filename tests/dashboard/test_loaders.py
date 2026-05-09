"""Tests for polymarket_bot.dashboard.loaders.

Cover: process status (alive PID via os.getpid; dead PID via a high
random; missing pid file); feeds_health (present, missing, malformed);
load_decisions (fired-only, fired+settled, missing dir, date filter,
multiple files); tail_log (small, large, empty, missing); aggregate_pnl.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from polymarket_bot._paper.decision_log import DecisionLog
from polymarket_bot.backtest.types import Decision, Fill
from polymarket_bot.dashboard.loaders import (
    aggregate_pnl,
    load_decisions,
    load_feeds_health,
    load_process_status,
    tail_log,
)

ASSET = "0x" + "a1" * 31  # 64 hex chars
WINDOW_TS = 1_762_540_500
DEC_TS_NS = WINDOW_TS * 1_000_000_000 + 12_000_000_000


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


# ---------- process status ----------


def test_process_status_returns_capture_then_paper(tmp_path: Path) -> None:
    capture, paper = load_process_status(tmp_path)
    assert capture.name == "capture"
    assert paper.name == "paper"


def test_process_status_no_pid_file(tmp_path: Path) -> None:
    capture, paper = load_process_status(tmp_path)
    assert capture.pid is None
    assert capture.alive is False
    assert paper.pid is None


def test_process_status_alive_pid(tmp_path: Path) -> None:
    own_pid = os.getpid()
    (tmp_path / "paper.pid").write_text(str(own_pid))
    _, paper = load_process_status(tmp_path)
    assert paper.pid == own_pid
    assert paper.alive is True
    assert paper.create_time_utc is not None


def test_process_status_dead_pid(tmp_path: Path) -> None:
    # Use a very high PID unlikely to exist on a default-config laptop.
    (tmp_path / "paper.pid").write_text("9999999")
    _, paper = load_process_status(tmp_path)
    assert paper.pid == 9_999_999
    assert paper.alive is False


def test_process_status_garbage_pid(tmp_path: Path) -> None:
    (tmp_path / "paper.pid").write_text("not-a-number")
    _, paper = load_process_status(tmp_path)
    assert paper.pid is None
    assert paper.alive is False


# ---------- feeds health ----------


def test_load_feeds_health_missing_returns_none(tmp_path: Path) -> None:
    assert load_feeds_health(tmp_path) is None


def test_load_feeds_health_malformed_returns_none(tmp_path: Path) -> None:
    (tmp_path / "feeds_health.json").write_text("not json")
    assert load_feeds_health(tmp_path) is None


def test_load_feeds_health_happy(tmp_path: Path) -> None:
    payload = {
        "snapshot_ts_utc": "2026-05-07T11:00:00Z",
        "feeds": {
            "binance": {
                "msgs_seen": 1000,
                "healthy": True,
                "reconnects": 0,
                "last_error": "",
                "last_seen_ns": 1762541000000000000,
            },
            "oracle": {
                "msgs_seen": 5,
                "healthy": True,
                "reconnects": 1,
                "last_error": "transient",
                "last_seen_ns": 1762541010000000000,
            },
        },
    }
    (tmp_path / "feeds_health.json").write_text(json.dumps(payload))
    snap = load_feeds_health(tmp_path)
    assert snap is not None
    assert [f.name for f in snap.feeds] == ["binance", "oracle"]
    assert snap.feeds[0].msgs_seen == 1000
    assert snap.feeds[1].reconnects == 1
    assert snap.feeds[1].last_error == "transient"


def test_load_feeds_health_partial_schema(tmp_path: Path) -> None:
    payload = {"feeds": {"binance": {"msgs_seen": 50}}}
    (tmp_path / "feeds_health.json").write_text(json.dumps(payload))
    snap = load_feeds_health(tmp_path)
    assert snap is not None
    assert len(snap.feeds) == 1
    assert snap.feeds[0].msgs_seen == 50
    assert snap.feeds[0].healthy is False
    assert snap.feeds[0].last_error == ""


# ---------- load_decisions ----------


def test_load_decisions_missing_dir(tmp_path: Path) -> None:
    assert load_decisions(tmp_path / "does-not-exist") == []


def test_load_decisions_empty_dir(tmp_path: Path) -> None:
    (tmp_path / "decisions").mkdir()
    assert load_decisions(tmp_path / "decisions") == []


def test_load_decisions_fired_and_settled(tmp_path: Path) -> None:
    log_dir = tmp_path / "decisions"
    log = DecisionLog(root=log_dir)
    did = log.record_fired(
        decision=_decision(),
        side="UP",
        window_ts=WINDOW_TS,
        snapshot={"spot_now": 67400},
        composite_pct=0.612,
        fill=_fill(),
    )
    log.record_settled(
        decision_id=did,
        window_ts=WINDOW_TS,
        settled_ts_ns=(WINDOW_TS + 300) * 1_000_000_000,
        open_oracle=67400.0,
        close_oracle=67500.0,
        resolution="UP",
        fill_at_settle=_fill(),
        pnl_usd=4.4,
    )
    log.close()
    rows = load_decisions(log_dir)
    assert len(rows) == 1
    r = rows[0]
    assert r.decision_id == did
    assert r.side == "UP"
    assert r.fill_price == 0.505
    assert r.resolution == "UP"
    assert r.pnl_usd == 4.4
    assert r.composite_pct == 0.612


def test_load_decisions_fired_only(tmp_path: Path) -> None:
    """Decision fired but window hasn't closed → settled fields are None."""
    log_dir = tmp_path / "decisions"
    log = DecisionLog(root=log_dir)
    did = log.record_fired(
        decision=_decision(),
        side="DOWN",
        window_ts=WINDOW_TS,
        snapshot={},
        composite_pct=-0.7,
        fill=None,
    )
    log.close()
    rows = load_decisions(log_dir)
    assert len(rows) == 1
    assert rows[0].decision_id == did
    assert rows[0].fill_price is None
    assert rows[0].resolution is None
    assert rows[0].pnl_usd is None


def test_load_decisions_sorted_by_decision_dt(tmp_path: Path) -> None:
    log_dir = tmp_path / "decisions"
    log = DecisionLog(root=log_dir)
    log.record_fired(
        decision=_decision(ts_offset_ns=2 * 60_000_000_000),
        side="UP",
        window_ts=WINDOW_TS,
        snapshot={},
        composite_pct=0.6,
        fill=None,
    )
    log.record_fired(
        decision=_decision(ts_offset_ns=0),
        side="UP",
        window_ts=WINDOW_TS,
        snapshot={},
        composite_pct=0.7,
        fill=None,
    )
    log.close()
    rows = load_decisions(log_dir)
    assert len(rows) == 2
    assert rows[0].decision_dt_utc < rows[1].decision_dt_utc


def test_load_decisions_since_filter(tmp_path: Path) -> None:
    log_dir = tmp_path / "decisions"
    (log_dir).mkdir()
    (log_dir / "2026-05-06.jsonl").write_text(
        json.dumps(
            {
                "kind": "fired",
                "decision_id": "old",
                "window_ts": WINDOW_TS,
                "decision_ts_ns": DEC_TS_NS,
                "asset_id": ASSET,
                "side": "UP",
                "size_usd": 5.0,
                "price_limit": 0.51,
                "ttl_s": 18,
                "rationale": "side=UP",
                "snapshot": {},
                "composite_pct": 0.6,
                "fill": None,
            }
        )
        + "\n"
    )
    (log_dir / "2026-05-07.jsonl").write_text(
        json.dumps(
            {
                "kind": "fired",
                "decision_id": "new",
                "window_ts": WINDOW_TS + 86400,
                "decision_ts_ns": DEC_TS_NS + 86400 * 1_000_000_000,
                "asset_id": ASSET,
                "side": "DOWN",
                "size_usd": 5.0,
                "price_limit": 0.51,
                "ttl_s": 18,
                "rationale": "side=DOWN",
                "snapshot": {},
                "composite_pct": -0.6,
                "fill": None,
            }
        )
        + "\n"
    )
    rows = load_decisions(log_dir, since_utc_date="2026-05-07")
    assert {r.decision_id for r in rows} == {"new"}


# ---------- tail_log ----------


def test_tail_log_missing(tmp_path: Path) -> None:
    assert tail_log(tmp_path / "nope.log") == []


def test_tail_log_small(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("a\nb\nc\n")
    assert tail_log(p, n_lines=10) == ["a", "b", "c"]


def test_tail_log_truncates_to_n(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    p.write_text("\n".join(str(i) for i in range(100)) + "\n")
    out = tail_log(p, n_lines=5)
    assert out == ["95", "96", "97", "98", "99"]


def test_tail_log_large_file_uses_tail_window(tmp_path: Path) -> None:
    p = tmp_path / "x.log"
    # 200KB of repeating lines; tail window is 64KB by default.
    p.write_text("hello world\n" * 20_000)
    out = tail_log(p, n_lines=3)
    assert all(line == "hello world" for line in out)
    assert len(out) == 3


# ---------- aggregate_pnl ----------


def test_aggregate_pnl_empty() -> None:
    out = aggregate_pnl([])
    assert out["n_fired"] == 0
    assert out["n_filled"] == 0
    assert out["n_settled"] == 0
    assert out["n_won"] == 0
    assert out["win_rate"] is None
    assert out["avg_pnl_per_filled"] is None


def test_aggregate_pnl_with_rows(tmp_path: Path) -> None:
    log_dir = tmp_path / "decisions"
    log = DecisionLog(root=log_dir)
    # Two filled, one win and one loss.
    for i, (side, won) in enumerate([("UP", True), ("DOWN", False)]):
        did = log.record_fired(
            decision=_decision(ts_offset_ns=i * 10_000_000_000),
            side=side,
            window_ts=WINDOW_TS + i * 300,
            snapshot={},
            composite_pct=0.6,
            fill=_fill(),
        )
        resolution = side if won else ("DOWN" if side == "UP" else "UP")
        log.record_settled(
            decision_id=did,
            window_ts=WINDOW_TS + i * 300,
            settled_ts_ns=(WINDOW_TS + (i + 1) * 300) * 1_000_000_000,
            open_oracle=67400.0,
            close_oracle=67500.0,
            resolution=resolution,
            fill_at_settle=_fill(),
            pnl_usd=4.4 if won else -5.0,
        )
    # One fired-only.
    log.record_fired(
        decision=_decision(ts_offset_ns=99 * 10_000_000_000),
        side="UP",
        window_ts=WINDOW_TS + 99 * 300,
        snapshot={},
        composite_pct=0.7,
        fill=None,
    )
    log.close()
    rows = load_decisions(log_dir)
    out = aggregate_pnl(rows)
    assert out["n_fired"] == 3
    assert out["n_filled"] == 2
    assert out["n_settled"] == 2
    assert out["n_won"] == 1
    assert out["win_rate"] == 0.5
    win_rate = out["win_rate"]
    pnl = out["total_pnl_usd"]
    assert isinstance(win_rate, float)
    assert isinstance(pnl, float)
    assert abs(pnl - -0.6) < 1e-9  # 4.4 + -5.0 with float drift


# ---------- _float_marker regression (operator screenshot 2026-05-09) ----------


def test_float_marker_word_boundary_avoids_longer_marker_collision() -> None:
    """A rationale containing `entry_delta_bps=80400` and `delta_bps=12.5`
    must NOT return 80400 when asked for `delta_bps=` — that bug rendered
    "80400.00" in the v3 dashboard's Δbps column on 2026-05-09.
    """
    from polymarket_bot.dashboard.loaders import _float_marker

    rationale = (
        "strategy=spot_aware mode=aggressive entry_delta_bps=80400 "
        "delta_bps=12.5 p_win=0.54 ev=0.0123 ttl=18s side=UP"
    )
    assert _float_marker(rationale, "delta_bps=") == 12.5
    assert _float_marker(rationale, "p_win=") == 0.54
    assert _float_marker(rationale, "ev=") == 0.0123


def test_float_marker_returns_none_when_marker_absent() -> None:
    from polymarket_bot.dashboard.loaders import _float_marker

    assert _float_marker("strategy=spot_aware mode=aggressive", "delta_bps=") is None


def test_float_marker_negative_and_exponent() -> None:
    from polymarket_bot.dashboard.loaders import _float_marker

    rationale = "delta_bps=-12.5 ev=1.5e-3 p_win=0.54"
    assert _float_marker(rationale, "delta_bps=") == -12.5
    assert _float_marker(rationale, "ev=") == 0.0015


def test_float_marker_anchored_at_start_of_string() -> None:
    """Rationale starting with a marker (no leading whitespace) still parses."""
    from polymarket_bot.dashboard.loaders import _float_marker

    assert _float_marker("delta_bps=12.5 mode=aggressive", "delta_bps=") == 12.5


# ---------- systemd-aware paper-process fallback ----------


def test_read_process_systemd_fallback_inactive(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When pid file is absent and PMB_DASH_PAPER_SYSTEMD_UNIT is set
    but systemctl reports the unit inactive, return alive=False."""
    from polymarket_bot.dashboard.loaders import _read_process

    monkeypatch.setenv("PMB_DASH_PAPER_SYSTEMD_UNIT", "absolutely-not-a-real-unit.service")
    status = _read_process(tmp_path, "paper")
    assert status.alive is False


def test_read_process_systemd_fallback_unset(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No pid file + no PMB_DASH_*_SYSTEMD_UNIT env → alive=False, no
    systemctl call attempted."""
    from polymarket_bot.dashboard.loaders import _read_process

    monkeypatch.delenv("PMB_DASH_PAPER_SYSTEMD_UNIT", raising=False)
    status = _read_process(tmp_path, "paper")
    assert status.alive is False
    assert status.pid is None

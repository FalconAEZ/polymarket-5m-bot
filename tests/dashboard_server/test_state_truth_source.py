"""Tests for state.snapshot()'s truth-source selection.

When state/decisions-resolved/ is populated, snapshot() should read
from there (Polymarket-truth) rather than state/decisions/ (oracle-
truth). The new ``decisions_truth_source`` field labels which view the
operator is reading.

Regression value: catches the dashboard-truth-drift incident
(runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md) before
it can recur silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polymarket_bot.dashboard_server.state import snapshot


def _write_decision_pair(
    path: Path,
    *,
    decision_id: str,
    window_ts: int,
    side: str,
    resolution: str,
    pnl_usd: float,
    resolution_source: str,
) -> None:
    """Append one fired+settled JSONL pair to ``path``."""
    fired = json.dumps(
        {
            "kind": "fired",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "decision_ts_ns": window_ts * 1_000_000_000,
            "asset_id": "0x" + "ab" * 31,
            "side": side,
            "size_usd": 5.0,
            "price_limit": 0.5,
            "ttl_s": 30,
            "rationale": f"strategy=spot_aware mode=aggressive side={side}",
            "snapshot": {},
            "composite_pct": None,
            "fill": None,
        }
    )
    settled = json.dumps(
        {
            "kind": "settled",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "settled_ts_ns": (window_ts + 300) * 1_000_000_000,
            "open_oracle": 80000.0,
            "close_oracle": 80100.0,
            "resolution": resolution,
            "resolution_source": resolution_source,
            "fill_at_settle": {"size_filled": 10.0, "price_filled": 0.5, "fee_usd": 0.0},
            "pnl_usd": pnl_usd,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(fired + "\n" + settled + "\n")


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """A state dir with both raw (oracle, wrong) and resolved (PM, right)
    decisions for the SAME window. The two views disagree on PnL by $10
    so we can verify snapshot picked the right one.
    """
    raw = tmp_path / "decisions" / "2026-05-08.jsonl"
    resolved = tmp_path / "decisions-resolved" / "2026-05-08.jsonl"

    # Use yesterday so the lookback (14 days) catches it; the date in the
    # filename matters for load_decisions's date-prefix scan.
    import datetime as dt

    yday = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    raw = tmp_path / "decisions" / f"{yday}.jsonl"
    resolved = tmp_path / "decisions-resolved" / f"{yday}.jsonl"
    yday_window_ts = int(dt.datetime.fromisoformat(yday).replace(tzinfo=dt.UTC).timestamp())

    # Oracle (raw): says UP won, side was UP → +$5 (wrong but oracle).
    _write_decision_pair(
        raw,
        decision_id="d1",
        window_ts=yday_window_ts,
        side="UP",
        resolution="UP",
        pnl_usd=+5.0,
        resolution_source="chainlink-local",
    )
    # Polymarket (resolved): same trade, but truth was DOWN → side UP loses → -$5.
    _write_decision_pair(
        resolved,
        decision_id="d1",
        window_ts=yday_window_ts,
        side="UP",
        resolution="DOWN",
        pnl_usd=-5.0,
        resolution_source="polymarket",
    )
    return tmp_path


def test_snapshot_prefers_resolved_dir_when_present(state_dir: Path) -> None:
    snap = snapshot(state_dir)
    assert snap["decisions_truth_source"] == "polymarket"
    # PnL should be -$5 (Polymarket-truth), not +$5 (oracle).
    assert snap["bankroll"]["delta_usd"] == pytest.approx(-5.0)


def test_snapshot_falls_back_to_raw_when_resolved_dir_missing(
    state_dir: Path,
) -> None:
    """Delete the resolved dir → snapshot uses oracle-truth."""
    import shutil

    shutil.rmtree(state_dir / "decisions-resolved")
    snap = snapshot(state_dir)
    assert snap["decisions_truth_source"] == "oracle"
    # Now sees the wrong oracle PnL (+$5).
    assert snap["bankroll"]["delta_usd"] == pytest.approx(+5.0)


def test_snapshot_falls_back_to_raw_when_resolved_dir_empty(state_dir: Path) -> None:
    """Empty resolved dir (no JSONL files) → fall back to raw."""
    resolved_dir = state_dir / "decisions-resolved"
    for p in resolved_dir.glob("*.jsonl"):
        p.unlink()
    snap = snapshot(state_dir)
    assert snap["decisions_truth_source"] == "oracle"
    assert snap["bankroll"]["delta_usd"] == pytest.approx(+5.0)


def test_snapshot_truth_source_unknown_when_both_dirs_empty(tmp_path: Path) -> None:
    """No decisions at all → truth_source is 'unknown', not 'oracle'."""
    snap = snapshot(tmp_path)
    assert snap["decisions_truth_source"] == "unknown"
    assert snap["bankroll"]["delta_usd"] == 0.0

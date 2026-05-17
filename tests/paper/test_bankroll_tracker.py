"""Tests for polymarket_bot._paper.runner.BankrollTracker.

Per pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf §9.5 / design
spot_aware_v2_1.md. Covers the 4-test surface in the prompt plus the
two phantom-fill + multi-day edge cases the spec calls out
(cross-day boundary handling, phantom-fill neutralization).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from polymarket_bot._paper.runner import (
    BankrollTracker,
    replay_bankroll_from_log,
)


def test_bankroll_starts_at_decision_10_default() -> None:
    """Bare ``BankrollTracker()`` honors locked decision #10 — $1000 paper."""
    tracker = BankrollTracker()
    assert tracker.current() == 1000.0
    assert tracker.starting_usd == 1000.0
    assert tracker.realized_pnl_usd == 0.0


def test_bankroll_applies_settle() -> None:
    """apply_settle adds the settled pnl; current() reflects starting+realized."""
    tracker = BankrollTracker(starting_usd=1000.0)
    tracker.apply_settle(5.50)
    assert tracker.current() == 1005.50
    tracker.apply_settle(-2.75)
    assert tracker.current() == 1002.75


def test_bankroll_applies_correction() -> None:
    """Phase 15.5 overlay: a correction nets (corrected - original) onto
    the realized pnl. The example: original_pnl=+2 was already applied
    via apply_settle; correction says actual is -3; tracker should
    reflect a delta of -5."""
    tracker = BankrollTracker(starting_usd=1000.0)
    tracker.apply_settle(2.0)  # original settle landed
    assert tracker.current() == 1002.0
    tracker.apply_correction(original_pnl_usd=2.0, corrected_pnl_usd=-3.0)
    assert tracker.current() == 997.0
    # Sanity: explicit phantom-fill case (corrected_pnl_usd=0.0 neutralizes).
    tracker.apply_settle(161.0)  # phantom positive
    assert tracker.current() == 1158.0
    tracker.apply_correction(original_pnl_usd=161.0, corrected_pnl_usd=0.0)
    assert tracker.current() == 997.0


# ---------- replay-from-log ----------


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def test_bankroll_recovers_from_jsonl(tmp_path: Path) -> None:
    """Feed two days of settled records plus one correction; the replay
    must converge to starting + Σ(settled pnl) + Σ(correction deltas)."""
    log_root = tmp_path / "decisions"
    log_root.mkdir()
    day_a = date(2026, 5, 12)
    day_b = date(2026, 5, 13)
    _write_jsonl(
        log_root / f"{day_a.strftime('%Y-%m-%d')}.jsonl",
        [
            {"kind": "fired", "decision_id": "d1", "window_ts": 1, "pnl_usd": "ignored"},
            {"kind": "settled", "decision_id": "d1", "window_ts": 1, "pnl_usd": 5.0},
            {"kind": "settled", "decision_id": "d2", "window_ts": 2, "pnl_usd": -3.5},
        ],
    )
    _write_jsonl(
        log_root / f"{day_b.strftime('%Y-%m-%d')}.jsonl",
        [
            {"kind": "settled", "decision_id": "d3", "window_ts": 3, "pnl_usd": 7.25},
            # Correction overlay: d1's pnl was +5; gamma says it was -2.
            # Net delta on the tracker: (-2) - (+5) = -7.
            {
                "kind": "settled_correction",
                "decision_id": "d1",
                "window_ts": 1,
                "original_pnl_usd": 5.0,
                "corrected_pnl_usd": -2.0,
            },
            # Phantom-fill correction: d2's pnl was -3.5 (false negative
            # from over-fill); corrected to 0 to neutralize. Delta = 0 - (-3.5) = +3.5.
            {
                "kind": "settled_correction",
                "decision_id": "d2",
                "window_ts": 2,
                "original_pnl_usd": -3.5,
                "corrected_pnl_usd": 0.0,
                "phantom_fill": True,
            },
        ],
    )

    tracker = replay_bankroll_from_log(
        log_root=log_root,
        starting_usd=1000.0,
        today=day_b,
        lookback_days=2,
    )
    # Σ settled = 5 + -3.5 + 7.25 = 8.75
    # Σ correction deltas = -7 + 3.5 = -3.5
    # Net realized = 5.25; current = 1005.25
    assert tracker.current() == 1005.25


def test_bankroll_replay_handles_missing_log_root(tmp_path: Path) -> None:
    """Replay against a non-existent or empty log root degrades to
    starting bankroll. A redeploy onto a fresh VPS must not raise."""
    missing = tmp_path / "no_such_dir"
    tracker = replay_bankroll_from_log(log_root=missing, starting_usd=1234.0)
    assert tracker.current() == 1234.0


def test_bankroll_replay_skips_malformed_records(tmp_path: Path) -> None:
    """Defensive: a malformed pnl field (string, missing) doesn't crash;
    the well-formed records still apply. Preserves the runner's
    'fail-open' posture for log corruption."""
    log_root = tmp_path / "decisions"
    log_root.mkdir()
    d = date(2026, 5, 13)
    _write_jsonl(
        log_root / f"{d.strftime('%Y-%m-%d')}.jsonl",
        [
            {"kind": "settled", "decision_id": "d1", "window_ts": 1, "pnl_usd": "broken"},
            {"kind": "settled", "decision_id": "d2", "window_ts": 2},  # missing pnl
            {"kind": "settled", "decision_id": "d3", "window_ts": 3, "pnl_usd": 1.5},
        ],
    )
    tracker = replay_bankroll_from_log(
        log_root=log_root, starting_usd=1000.0, today=d, lookback_days=0
    )
    assert tracker.current() == 1001.50

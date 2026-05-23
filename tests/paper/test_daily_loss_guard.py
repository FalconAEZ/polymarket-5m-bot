"""Tests for polymarket_bot._paper.daily_loss_guard.DailyLossGuard.

Phase T Session 2 P1 — runner-level continuous daily-loss halt. Covers
the 7-test surface in design/phase-T-l5-runner-daily-loss-guard.md §9:
trip-when-crossed, no-trip-above, threshold-zero-disables, truth-
corrected anchor from log on restart mid-day, UTC rollover resets,
idempotent post-trip, correction overlay can trigger trip.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from polymarket_bot._paper.daily_loss_guard import DailyLossGuard, _today_realised_pnl


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _make_clock(
    initial: datetime,
) -> tuple[list[datetime], Callable[[], datetime]]:
    """Return a (mutable list, callable) pair. Mutate list[0] to advance
    the clock between evaluate() calls deterministically."""
    box = [initial]

    def now_utc() -> datetime:
        return box[0]

    return box, now_utc


def _writer_recorder() -> tuple[list[tuple[str, int]], Callable[[str, int], None]]:
    calls: list[tuple[str, int]] = []

    def writer(reason: str, ts_ns: int) -> None:
        calls.append((reason, ts_ns))

    return calls, writer


# ---------- _today_realised_pnl helper ----------


def test_today_realised_pnl_missing_file_is_zero(tmp_path: Path) -> None:
    """No log file for today -> 0.0, not a crash."""
    assert _today_realised_pnl(tmp_path, date(2026, 5, 23)) == 0.0


def test_today_realised_pnl_sums_settled_and_corrections(tmp_path: Path) -> None:
    """Sum of settled.pnl_usd + (corrected - original) overlay deltas for
    a single calendar day, matching replay_bankroll_from_log's per-day
    semantics."""
    today = date(2026, 5, 23)
    _write_jsonl(
        tmp_path / f"{today.strftime('%Y-%m-%d')}.jsonl",
        [
            {"kind": "fired", "decision_id": "d1", "window_ts": 1},  # ignored
            {"kind": "settled", "decision_id": "d1", "window_ts": 1, "pnl_usd": -50.0},
            {"kind": "settled", "decision_id": "d2", "window_ts": 2, "pnl_usd": 30.0},
            {
                "kind": "settled_correction",
                "decision_id": "d1",
                "original_pnl_usd": -50.0,
                "corrected_pnl_usd": 0.0,  # phantom-fill neutralize: +50 delta
            },
        ],
    )
    # net: -50 + 30 + (0 - -50) = +30
    assert _today_realised_pnl(tmp_path, today) == 30.0


# ---------- DailyLossGuard.evaluate ----------


def test_trip_when_threshold_crossed(tmp_path: Path) -> None:
    """Single bankroll observation that pushes today PnL below -threshold
    trips exactly once and writes the halt sentinel."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()

    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    # First call anchors day-start at 3000 (no prior log for today).
    assert guard.evaluate(bankroll_current=3000.0) is None
    assert calls == []

    # Drop to 2650 -> today PnL = -350 -> trips.
    result = guard.evaluate(bankroll_current=2650.0)
    assert result is not None
    assert result.tripped is True
    assert result.today_pnl_usd == -350.0
    assert result.threshold_usd == 300.0
    assert result.anchored_day == date(2026, 5, 23)
    assert len(calls) == 1
    reason, ts_ns = calls[0]
    assert "auto-halt-daily-loss" in reason
    assert "today_pnl=$-350.00" in reason
    assert "threshold=-$300.00" in reason
    assert ts_ns > 0


def test_no_trip_when_above_threshold(tmp_path: Path) -> None:
    """A bankroll loss above the -threshold magnitude does not trip."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    guard.evaluate(bankroll_current=3000.0)  # anchor
    assert guard.evaluate(bankroll_current=2800.0) is None  # -200, above -300
    assert guard.evaluate(bankroll_current=2701.0) is None  # -299
    assert calls == []


def test_threshold_zero_is_disabled(tmp_path: Path) -> None:
    """threshold_usd=0 disables the guard regardless of loss magnitude."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=0.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )
    assert guard.enabled is False
    guard.evaluate(bankroll_current=3000.0)
    assert guard.evaluate(bankroll_current=100.0) is None  # huge loss, no trip
    assert calls == []


def test_truth_corrected_anchor_on_restart_mid_day(tmp_path: Path) -> None:
    """On startup mid-day, today's log already shows prior losses.
    bankroll_replay_from_log has applied them to BankrollTracker, so the
    bankroll passed to evaluate() is post-loss. The guard must subtract
    today's-PnL-so-far to recover the pre-loss day-start anchor."""
    today = date(2026, 5, 23)
    # Prior -$200 already realised today and replayed into the bankroll.
    _write_jsonl(
        tmp_path / f"{today.strftime('%Y-%m-%d')}.jsonl",
        [
            {"kind": "settled", "decision_id": "d1", "window_ts": 1, "pnl_usd": -200.0},
        ],
    )
    _, clock = _make_clock(datetime(2026, 5, 23, 14, 30, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    # Bot just restarted; replay -> current bankroll is 3000 - 200 = 2800.
    # Day-start anchor must be 2800 - (-200) = 3000. -200 is already below
    # threshold? No: -200 > -300. Should NOT trip.
    assert guard.evaluate(bankroll_current=2800.0) is None
    assert calls == []

    # A further -$120 loss (bankroll 2680) takes today PnL to -320 -> trip.
    result = guard.evaluate(bankroll_current=2680.0)
    assert result is not None
    assert result.tripped is True
    assert result.today_pnl_usd == -320.0
    assert len(calls) == 1


def test_utc_rollover_resets_anchor(tmp_path: Path) -> None:
    """After a trip on day N, advancing the clock to day N+1 must re-
    anchor (with an empty new-day log -> anchor = current bankroll) and
    allow normal evaluation again."""
    clock_box, clock = _make_clock(datetime(2026, 5, 23, 23, 50, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    # Day 1: anchor + trip.
    guard.evaluate(bankroll_current=3000.0)
    result_a = guard.evaluate(bankroll_current=2650.0)
    assert result_a is not None
    assert result_a.tripped
    assert len(calls) == 1

    # Advance the clock past UTC midnight; bankroll stays at 2650.
    clock_box[0] = datetime(2026, 5, 24, 0, 30, 0, tzinfo=UTC)
    # First call on the new day re-anchors (no new-day log -> empty).
    # Anchor becomes 2650; small loss doesn't cross -300.
    assert guard.evaluate(bankroll_current=2550.0) is None  # -100, no trip
    assert len(calls) == 1  # still just the day-1 trip

    # A new-day -400 cross still trips fresh on day 2.
    result_b = guard.evaluate(bankroll_current=2240.0)  # -410 from 2650 anchor
    assert result_b is not None
    assert result_b.tripped
    assert result_b.anchored_day == date(2026, 5, 24)
    assert len(calls) == 2


def test_idempotent_after_trip(tmp_path: Path) -> None:
    """After tripping once on a given UTC day, subsequent evaluate()
    calls within the same day return None and do NOT re-write sentinel,
    even if the bankroll keeps falling."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    guard.evaluate(bankroll_current=3000.0)  # anchor
    first = guard.evaluate(bankroll_current=2650.0)  # trip
    assert first is not None
    assert first.tripped
    assert len(calls) == 1

    # Further losses on the same day must NOT write more sentinels.
    assert guard.evaluate(bankroll_current=2000.0) is None
    assert guard.evaluate(bankroll_current=1500.0) is None
    assert len(calls) == 1


def test_correction_overlay_can_trigger_trip(tmp_path: Path) -> None:
    """A post-hoc gamma correction that net-removes a prior winning
    settle (bankroll drops by the correction delta) is observable in
    the next evaluate() and trips when the cumulative day PnL crosses."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )

    # Anchor at 3000.
    guard.evaluate(bankroll_current=3000.0)
    # Series of small losses brings bankroll to 2750: today_pnl=-250, no trip.
    assert guard.evaluate(bankroll_current=2750.0) is None
    # A correction reveals that an earlier $80 "win" was phantom and
    # actually lost the premium; bankroll drops to 2670: today_pnl=-330 -> trip.
    result = guard.evaluate(bankroll_current=2670.0)
    assert result is not None
    assert result.tripped
    assert result.today_pnl_usd == -330.0
    assert len(calls) == 1


def test_negative_threshold_rejected(tmp_path: Path) -> None:
    """Constructor rejects negative thresholds (caller must pass a positive
    magnitude; sign is implicit in the semantic)."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    _, writer = _writer_recorder()
    with pytest.raises(ValueError, match="threshold_usd"):
        DailyLossGuard(
            threshold_usd=-100.0,
            log_root=tmp_path,
            halt_writer=writer,
            clock_utc=clock,
        )


def test_exact_threshold_match_trips(tmp_path: Path) -> None:
    """A loss exactly equal to -threshold trips (<= semantics)."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )
    guard.evaluate(bankroll_current=3000.0)
    result = guard.evaluate(bankroll_current=2700.0)  # exactly -300
    assert result is not None
    assert result.tripped
    assert result.today_pnl_usd == -300.0
    assert len(calls) == 1


def test_first_call_does_not_trip_even_if_below_threshold(tmp_path: Path) -> None:
    """First call within a UTC day anchors and returns None even if the
    current bankroll is already below what would be a tripping delta in
    isolation — there is no 'previous' to compare against until anchor."""
    today = date(2026, 5, 23)
    _, clock = _make_clock(datetime(2026, 5, 23, 8, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    # Empty log for today -> anchor will equal whatever bankroll is passed.
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )
    # Very low bankroll, but no day-start frame of reference yet.
    assert guard.evaluate(bankroll_current=500.0) is None
    assert calls == []
    assert guard._anchored_day == today  # type: ignore[attr-defined]


def test_anchor_survives_evaluate_with_no_bankroll_change(tmp_path: Path) -> None:
    """Repeated evaluates with unchanged bankroll never trip."""
    _, clock = _make_clock(datetime(2026, 5, 23, 12, 0, 0, tzinfo=UTC))
    calls, writer = _writer_recorder()
    guard = DailyLossGuard(
        threshold_usd=300.0,
        log_root=tmp_path,
        halt_writer=writer,
        clock_utc=clock,
    )
    for _ in range(10):
        assert guard.evaluate(bankroll_current=3000.0) is None
    assert calls == []

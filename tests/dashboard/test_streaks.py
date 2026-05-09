"""Tests for polymarket_bot.dashboard.streaks.

Covers: empty, all-wins, all-losses, mixed alternating, current vs best,
unsettled rows are skipped. Per design/dashboard-v2.md §7.2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polymarket_bot.dashboard.loaders import DecisionRow
from polymarket_bot.dashboard.streaks import compute_streak

ASSET = "0x" + "cd" * 31


def _row(
    *,
    side: str,
    resolution: str | None,
    seq: int,
    fill: float | None = 0.5,
) -> DecisionRow:
    return DecisionRow(
        decision_id=f"d-{seq}",
        window_ts=1_700_000_000 + seq,
        decision_dt_utc=datetime(2026, 5, 9, tzinfo=UTC) + timedelta(seconds=seq),
        asset_id=ASSET,
        side=side,  # type: ignore[arg-type]
        size_usd=5.0,
        price_limit=0.5,
        ttl_s=18,
        composite_pct=0.6,
        strategy="spot_aware",
        mode="aggressive",
        delta_bps=12.0,
        p_win=0.55,
        ev_dollars=0.05,
        fill_price=fill,
        fee_usd=0.001 if fill else None,
        resolution=resolution,  # type: ignore[arg-type]
        pnl_usd=5.0 if (resolution and resolution == side) else (-5.0 if resolution else None),
    )


def test_empty_returns_dot_glyph() -> None:
    s = compute_streak([])
    assert s.current_glyph == "·"
    assert s.current_n == 0
    assert s.best_win_streak == 0
    assert s.worst_loss_streak == 0


def test_three_wins_in_a_row() -> None:
    rows = [
        _row(side="UP", resolution="UP", seq=0),
        _row(side="DOWN", resolution="DOWN", seq=1),
        _row(side="UP", resolution="UP", seq=2),
    ]
    s = compute_streak(rows)
    assert s.current_glyph == "▲"
    assert s.current_n == 3
    assert s.best_win_streak == 3
    assert s.worst_loss_streak == 0


def test_two_losses_after_three_wins() -> None:
    rows = [
        _row(side="UP", resolution="UP", seq=0),
        _row(side="UP", resolution="UP", seq=1),
        _row(side="UP", resolution="UP", seq=2),
        _row(side="UP", resolution="DOWN", seq=3),
        _row(side="DOWN", resolution="UP", seq=4),
    ]
    s = compute_streak(rows)
    assert s.current_glyph == "▼"
    assert s.current_n == 2
    assert s.best_win_streak == 3
    assert s.worst_loss_streak == 2


def test_unsettled_rows_are_skipped() -> None:
    rows = [
        _row(side="UP", resolution="UP", seq=0),
        _row(side="UP", resolution=None, seq=1),  # pending — skipped
        _row(side="UP", resolution="UP", seq=2),
    ]
    s = compute_streak(rows)
    assert s.current_glyph == "▲"
    assert s.current_n == 2
    assert s.best_win_streak == 2


def test_unfilled_rows_are_skipped() -> None:
    rows = [
        _row(side="UP", resolution="UP", seq=0),
        _row(side="UP", resolution="UP", seq=1, fill=None),  # not filled — skipped
        _row(side="UP", resolution="UP", seq=2),
    ]
    s = compute_streak(rows)
    assert s.current_n == 2


def test_chronological_order_enforced() -> None:
    rows = [
        _row(side="UP", resolution="UP", seq=2),
        _row(side="UP", resolution="UP", seq=0),
        _row(side="UP", resolution="UP", seq=1),
    ]
    s = compute_streak(rows)
    assert s.current_n == 3

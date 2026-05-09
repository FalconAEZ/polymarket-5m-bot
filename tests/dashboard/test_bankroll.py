"""Tests for polymarket_bot.dashboard.bankroll.

Covers: empty rows, all-loss, all-win, mixed, rows with None pnl_usd,
custom starting capital. Per design/dashboard-v2.md §7.1.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polymarket_bot.dashboard.bankroll import DEFAULT_STARTING_USD, Bankroll, load_bankroll
from polymarket_bot.dashboard.loaders import DecisionRow

ASSET = "0x" + "ab" * 31


def _row(pnl: float | None, side: str = "UP") -> DecisionRow:
    return DecisionRow(
        decision_id=f"d-{pnl}",
        window_ts=1_700_000_000,
        decision_dt_utc=datetime(2026, 5, 9, 0, 0, tzinfo=UTC),
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
        fill_price=0.5,
        fee_usd=0.001,
        resolution=side,  # type: ignore[arg-type]
        pnl_usd=pnl,
    )


def test_empty_rows_returns_starting_capital() -> None:
    b = load_bankroll([])
    assert b == Bankroll(
        starting_usd=DEFAULT_STARTING_USD,
        current_usd=1000.0,
        delta_usd=0.0,
        delta_pct=0.0,
    )


def test_all_wins_increases_bankroll() -> None:
    rows = [_row(5.88), _row(2.50), _row(1.25)]
    b = load_bankroll(rows)
    assert b.current_usd == pytest.approx(1009.63)
    assert b.delta_usd == pytest.approx(9.63)
    assert b.delta_pct == pytest.approx(0.00963)


def test_all_losses_decreases_bankroll() -> None:
    rows = [_row(-5.0), _row(-2.0)]
    b = load_bankroll(rows)
    assert b.current_usd == pytest.approx(993.0)
    assert b.delta_usd == pytest.approx(-7.0)
    assert b.delta_pct == pytest.approx(-0.007)


def test_mixed_pnl_sums_correctly() -> None:
    rows = [_row(5.88), _row(-1.16), _row(None), _row(0.0)]
    b = load_bankroll(rows)
    assert b.current_usd == pytest.approx(1004.72)
    assert b.delta_usd == pytest.approx(4.72)


def test_custom_starting_capital() -> None:
    b = load_bankroll([_row(50.0)], starting_usd=2000.0)
    assert b.starting_usd == 2000.0
    assert b.current_usd == 2050.0
    assert b.delta_pct == 0.025


def test_zero_starting_capital_pct_is_zero() -> None:
    b = load_bankroll([_row(10.0)], starting_usd=0.0)
    assert b.delta_pct == 0.0

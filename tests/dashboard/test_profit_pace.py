"""Tests for polymarket_bot.dashboard.profit_pace.

Covers: empty window, normalization across window sizes, exclusion of
unsettled/unfilled rows, custom now-clock injection. Per design/
dashboard-v2.md §7.3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polymarket_bot.dashboard.loaders import DecisionRow
from polymarket_bot.dashboard.profit_pace import profit_pace_per_hour

ASSET = "0x" + "ef" * 31

NOW = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)


def _row(
    *,
    pnl: float | None,
    minutes_ago: float,
    settled: bool = True,
    filled: bool = True,
) -> DecisionRow:
    return DecisionRow(
        decision_id=f"d-{minutes_ago}",
        window_ts=int((NOW - timedelta(minutes=minutes_ago)).timestamp()),
        decision_dt_utc=NOW - timedelta(minutes=minutes_ago),
        asset_id=ASSET,
        side="UP",
        size_usd=5.0,
        price_limit=0.5,
        ttl_s=18,
        composite_pct=0.6,
        strategy="spot_aware",
        mode="aggressive",
        delta_bps=12.0,
        p_win=0.55,
        ev_dollars=0.05,
        fill_price=0.5 if filled else None,
        fee_usd=0.001 if filled else None,
        resolution="UP" if settled else None,
        pnl_usd=pnl,
    )


def test_empty_returns_zero() -> None:
    assert profit_pace_per_hour([], now=NOW) == (0.0, 0)


def test_one_hour_pace_sums_realized_pnl() -> None:
    rows = [
        _row(pnl=2.0, minutes_ago=10),
        _row(pnl=3.0, minutes_ago=30),
    ]
    rate, n = profit_pace_per_hour(rows, window_s=3600.0, now=NOW)
    assert n == 2
    assert rate == 5.0


def test_pace_normalizes_across_window_sizes() -> None:
    """A 30-minute window with $2.50 realized → $5/hr equivalent rate."""
    rows = [_row(pnl=2.50, minutes_ago=15)]
    rate, _ = profit_pace_per_hour(rows, window_s=1800.0, now=NOW)
    assert rate == 5.0


def test_old_rows_excluded_from_window() -> None:
    rows = [
        _row(pnl=10.0, minutes_ago=5),  # in 60m window
        _row(pnl=99.0, minutes_ago=120),  # outside 60m
    ]
    rate, n = profit_pace_per_hour(rows, window_s=3600.0, now=NOW)
    assert n == 1
    assert rate == 10.0


def test_unsettled_rows_excluded() -> None:
    rows = [
        _row(pnl=5.0, minutes_ago=10),
        _row(pnl=None, minutes_ago=5, settled=False),
    ]
    rate, n = profit_pace_per_hour(rows, window_s=3600.0, now=NOW)
    assert n == 1
    assert rate == 5.0


def test_zero_window_returns_zero() -> None:
    rows = [_row(pnl=10.0, minutes_ago=1)]
    assert profit_pace_per_hour(rows, window_s=0.0, now=NOW) == (0.0, 0)

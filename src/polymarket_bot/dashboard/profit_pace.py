"""Profit pace ($/hour) over a rolling window for the v2 satellite KPI.

Sums pnl_usd over the last `window_s` seconds and reports it as a per-
hour rate so the operator sees their current earning velocity at a
glance. Pure function; clock injectable for tests. Per design/
dashboard-v2.md §7.3.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from polymarket_bot.dashboard.loaders import DecisionRow


def profit_pace_per_hour(
    rows: Iterable[DecisionRow],
    *,
    window_s: float = 3600.0,
    now: datetime | None = None,
) -> tuple[float, int]:
    """Returns (usd_per_hour, n_settled_in_window).

    n_settled_in_window only counts rows whose resolution is set; rows
    that fired but haven't closed yet are excluded so the rate reflects
    realized pnl, not exposure. usd_per_hour is normalized so the value
    is comparable across window sizes.
    """
    if window_s <= 0:
        return (0.0, 0)
    cutoff = (now or datetime.now(tz=UTC)) - timedelta(seconds=window_s)
    in_window = [
        r
        for r in rows
        if r.decision_dt_utc >= cutoff and r.resolution is not None and r.pnl_usd is not None
    ]
    if not in_window:
        return (0.0, 0)
    pnl = sum((r.pnl_usd or 0.0) for r in in_window)
    rate = pnl * (3600.0 / window_s)
    return (rate, len(in_window))

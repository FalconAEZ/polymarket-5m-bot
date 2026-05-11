"""Win/loss streak computation for the v2 hero satellite KPI.

Walks settled decisions in chronological order to compute the operator's
current streak (positive for wins, negative for losses) plus the best-
ever winning and losing runs. Pure function; no I/O; deterministic given
a row list. Per design/dashboard-v2.md §7.2.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from polymarket_bot.dashboard.loaders import DecisionRow


@dataclass(frozen=True, slots=True)
class StreakInfo:
    current_glyph: str  # "▲" winning, "▼" losing, "·" no settled
    current_n: int
    best_win_streak: int
    worst_loss_streak: int


def _is_win(r: DecisionRow) -> bool | None:
    """Returns True/False for settled rows, None if unsettled."""
    if r.resolution is None or r.fill_price is None:
        return None
    return r.resolution == r.side


def compute_streak(rows: Iterable[DecisionRow]) -> StreakInfo:
    sorted_rows = sorted(rows, key=lambda r: r.decision_dt_utc)
    best_win = 0
    worst_loss = 0
    current = 0  # >0 = winning streak length, <0 = losing streak length
    for r in sorted_rows:
        outcome = _is_win(r)
        if outcome is None:
            continue
        if outcome:
            current = current + 1 if current >= 0 else 1
            if current > best_win:
                best_win = current
        else:
            current = current - 1 if current <= 0 else -1
            if -current > worst_loss:
                worst_loss = -current
    if current > 0:
        glyph = "▲"
    elif current < 0:
        glyph = "▼"
    else:
        glyph = "·"
    return StreakInfo(
        current_glyph=glyph,
        current_n=abs(current),
        best_win_streak=best_win,
        worst_loss_streak=worst_loss,
    )

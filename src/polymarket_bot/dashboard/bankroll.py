"""Bankroll loader for the v2 dashboard hero row.

Pure-function derivation of the operator's current balance from the
locked starting capital ($1,000 per locked decision #10) plus the sum
of settled-decision pnl_usd. No Streamlit imports; no I/O. Tests cover
empty rows, all-loss rows, all-win rows, and the running paper-soak
data shape. Per design/dashboard-v2.md §7.1.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from polymarket_bot.dashboard.loaders import DecisionRow

DEFAULT_STARTING_USD: float = 1000.0


@dataclass(frozen=True, slots=True)
class Bankroll:
    starting_usd: float
    current_usd: float
    delta_usd: float
    delta_pct: float


def load_bankroll(
    rows: Iterable[DecisionRow], starting_usd: float = DEFAULT_STARTING_USD
) -> Bankroll:
    pnl_total = sum((r.pnl_usd or 0.0) for r in rows)
    current = starting_usd + pnl_total
    delta = current - starting_usd
    pct = (delta / starting_usd) if starting_usd > 0 else 0.0
    return Bankroll(
        starting_usd=starting_usd,
        current_usd=current,
        delta_usd=delta,
        delta_pct=pct,
    )

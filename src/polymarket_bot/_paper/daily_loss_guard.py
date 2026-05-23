"""Runner-level daily-loss guard. design/phase-T-l5-runner-daily-loss-guard.md.

Strategy-agnostic continuous halt: after every bankroll-changing event
(settle + post-hoc correction), compare today's realised PnL against a
configurable negative threshold. On trip, write the standard
``state/halt.sentinel`` so the existing run_paper.py halt watcher exits
the bot gracefully — preserving in-flight settle/correction drain. The
day-start anchor is computed by subtracting today's realised PnL
(re-read from state/decisions/<today>.jsonl) from current bankroll, so
a mid-day restart cannot reset the day's loss-budget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from polymarket_bot._paper.decision_log import read_jsonl


@dataclass(slots=True, frozen=True)
class DailyLossGuardResult:
    """Result returned by ``DailyLossGuard.evaluate`` when (and only when)
    the call tripped the guard. ``today_pnl_usd`` is signed (negative on a
    losing day). ``threshold_usd`` is the positive magnitude configured."""

    tripped: bool
    today_pnl_usd: float
    threshold_usd: float
    reason: str
    anchored_day: date


def _today_realised_pnl(log_root: Path, today: date) -> float:
    """Sum today's realised PnL from the decisions log — settled +
    settled_correction overlay — mirroring replay_bankroll_from_log
    semantics scoped to one calendar day. Returns 0.0 if the file is
    missing or empty."""
    path = log_root / f"{today.strftime('%Y-%m-%d')}.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    for rec in read_jsonl(path):
        kind = rec.get("kind")
        if kind == "settled":
            pnl = rec.get("pnl_usd")
            if isinstance(pnl, int | float):
                total += float(pnl)
        elif kind == "settled_correction":
            orig = rec.get("original_pnl_usd")
            corr = rec.get("corrected_pnl_usd")
            if isinstance(orig, int | float) and isinstance(corr, int | float):
                total += float(corr) - float(orig)
    return total


class DailyLossGuard:
    """Continuous daily-loss halt for PaperRunner. See module docstring
    and design/phase-T-l5-runner-daily-loss-guard.md."""

    def __init__(
        self,
        *,
        threshold_usd: float,
        log_root: Path,
        halt_writer: Callable[[str, int], None],
        clock_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if threshold_usd < 0:
            raise ValueError(f"threshold_usd must be >= 0 (magnitude); got {threshold_usd}")
        self._threshold = float(threshold_usd)
        self._log_root = log_root
        self._halt_writer = halt_writer
        self._clock = clock_utc if clock_utc is not None else (lambda: datetime.now(tz=UTC))
        self._anchored_day: date | None = None
        self._bankroll_at_day_start: float | None = None
        self._tripped_today = False

    @property
    def enabled(self) -> bool:
        return self._threshold > 0.0

    def evaluate(self, *, bankroll_current: float) -> DailyLossGuardResult | None:
        if not self.enabled:
            return None

        now = self._clock()
        today = now.date()

        # First call ever OR UTC rollover: re-anchor day-start and reset trip.
        if self._anchored_day != today:
            today_pnl_so_far = _today_realised_pnl(self._log_root, today)
            self._bankroll_at_day_start = bankroll_current - today_pnl_so_far
            self._anchored_day = today
            self._tripped_today = False

        # Idempotent: only one halt write per UTC day.
        if self._tripped_today:
            return None

        # _bankroll_at_day_start is unconditionally set in the rollover
        # branch above whenever _anchored_day matches today, which is the
        # only way to reach this point. The explicit None-check both
        # narrows the type and survives an -O strip.
        day_start = self._bankroll_at_day_start
        if day_start is None:
            return None
        today_pnl = bankroll_current - day_start

        if today_pnl > -self._threshold:
            return None

        self._tripped_today = True
        reason = (
            f"auto-halt-daily-loss: today_pnl=${today_pnl:.2f} "
            f"threshold=-${self._threshold:.2f} day={today.isoformat()}"
        )
        self._halt_writer(reason, int(now.timestamp() * 1_000_000_000))
        return DailyLossGuardResult(
            tripped=True,
            today_pnl_usd=today_pnl,
            threshold_usd=self._threshold,
            reason=reason,
            anchored_day=today,
        )

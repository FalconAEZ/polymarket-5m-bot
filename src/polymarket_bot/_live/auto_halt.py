"""Daily-PnL auto-halt — close-of-UTC-day floor that writes halt.sentinel.

Phase M Session 2 (L.5) retrofit. Reads the day's settled fires from
state/decisions-resolved/YYYY-MM-DD.jsonl (with settled_correction priority,
matching scripts/research/phase_l_soak_audit.py truth model), sums realized
PnL, and if the day closed below DAILY_PNL_GATE_USD the function writes
state/halt.sentinel and publishes a Level.CRITICAL Alert. The check is
idempotent against the sentinel — once tripped, the bot halts until operator
clears the sentinel. Design lock: design/L.5-daily-pnl-auto-halt.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from polymarket_bot._live.alerter.halt import (
    DEFAULT_SENTINEL_PATH,
    halt_sentinel_present,
    write_halt_sentinel,
)
from polymarket_bot.alerts.protocols import AlertSink
from polymarket_bot.alerts.types import Alert, Level

LOG = logging.getLogger("polymarket_bot._live.auto_halt")

DEFAULT_DECISIONS_RESOLVED_DIR = Path("state/decisions-resolved")


@dataclass(frozen=True)
class AutoHaltResult:
    """Outcome of one check_daily_pnl_gate call."""

    halted: bool
    pnl_usd: float
    reason: str


class DailyPnlReader(Protocol):
    """Reads realized PnL for a UTC day, with settled_correction priority."""

    def read(self, day_utc: date) -> float: ...


class HaltWriter(Protocol):
    """Writes the halt.sentinel atomically."""

    def write(self, *, reason: str, ts_ns: int, by: str) -> None: ...


class JsonlDailyPnlReader:
    """Production DailyPnlReader — reads decisions-resolved/YYYY-MM-DD.jsonl.

    Returns sum of corrected_pnl_usd preferring settled_correction records
    over settled records, keyed by decision_id. Returns 0.0 if file missing
    or empty. Never raises — corrupt lines are skipped with a logged warning.
    """

    def __init__(self, *, resolved_dir: Path = DEFAULT_DECISIONS_RESOLVED_DIR) -> None:
        self._resolved_dir = resolved_dir

    def read(self, day_utc: date) -> float:
        path = self._resolved_dir / f"{day_utc.isoformat()}.jsonl"
        if not path.exists():
            return 0.0
        settled: dict[str, float] = {}
        corrections: dict[str, float] = {}
        try:
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        LOG.warning("auto_halt: skipping malformed line in %s", path)
                        continue
                    kind = rec.get("kind")
                    did = rec.get("decision_id")
                    if not isinstance(did, str):
                        continue
                    if kind == "settled":
                        settled[did] = float(rec.get("pnl_usd") or 0.0)
                    elif kind == "settled_correction":
                        corrections[did] = float(rec.get("corrected_pnl_usd") or 0.0)
        except OSError:
            LOG.warning("auto_halt: OSError reading %s", path)
            return 0.0
        total = 0.0
        for did, pnl in settled.items():
            total += corrections.get(did, pnl)
        # Include corrections without a matching settled record (shouldn't happen, but safe).
        for did, pnl in corrections.items():
            if did not in settled:
                total += pnl
        return total


class SentinelHaltWriter:
    """Production HaltWriter — wraps halt.py:write_halt_sentinel."""

    def __init__(self, *, path: Path = DEFAULT_SENTINEL_PATH) -> None:
        self._path = path

    def write(self, *, reason: str, ts_ns: int, by: str) -> None:
        write_halt_sentinel(reason, ts_ns, by=by, path=self._path)


def check_daily_pnl_gate(
    *,
    now_ns: int,
    today_utc: date,
    pnl_reader: DailyPnlReader,
    halt_writer: HaltWriter,
    alerts: AlertSink,
    threshold_usd: float,
) -> AutoHaltResult:
    """Read today's PnL; halt + alert if at-or-below threshold.

    Returns AutoHaltResult. Never raises — internal failures publish an
    ERROR alert and return halted=False (no false-positive halts).
    """
    # Read PnL (defensive — reader is meant to never raise, but we double-belt).
    try:
        pnl = pnl_reader.read(today_utc)
    except Exception as exc:
        LOG.exception("auto_halt: reader failed")
        _safe_publish(
            alerts,
            Alert(
                level=Level.ERROR,
                message=f"auto_halt: pnl reader failed for {today_utc}: {exc}",
                ts_ns=now_ns,
                source="auto_halt.daily_pnl_gate",
                fields={"day_utc": str(today_utc)},
            ),
        )
        return AutoHaltResult(halted=False, pnl_usd=0.0, reason="reader-failed")

    # Above threshold → no-op.
    if pnl > threshold_usd:
        return AutoHaltResult(halted=False, pnl_usd=pnl, reason="pnl-above-threshold")

    # At-or-below threshold → write sentinel.
    reason = (
        f"daily-pnl-gate-tripped day={today_utc} pnl=${pnl:+.2f} threshold=${threshold_usd:+.2f}"
    )
    try:
        halt_writer.write(reason=reason, ts_ns=now_ns, by="auto-halt-daily-pnl")
    except Exception as exc:
        LOG.exception("auto_halt: sentinel write failed")
        _safe_publish(
            alerts,
            Alert(
                level=Level.ERROR,
                message=f"auto_halt: sentinel write failed for {today_utc}: {exc}",
                ts_ns=now_ns,
                source="auto_halt.daily_pnl_gate",
                fields={"day_utc": str(today_utc), "pnl_usd": pnl},
            ),
        )
        return AutoHaltResult(halted=False, pnl_usd=pnl, reason="sentinel-write-failed")

    # Publish the CRITICAL alert. Halt is primary; alert is best-effort.
    _safe_publish(
        alerts,
        Alert(
            level=Level.CRITICAL,
            message=(
                f"DAILY PNL GATE TRIPPED — day {today_utc} closed at PnL ${pnl:+,.2f}, "
                f"threshold ${threshold_usd:+,.2f}. Bot halted via state/halt.sentinel. "
                "Operator: review decisions-resolved + clear sentinel to resume."
            ),
            ts_ns=now_ns,
            source="auto_halt.daily_pnl_gate",
            fields={
                "pnl_usd": pnl,
                "threshold_usd": threshold_usd,
                "day_utc": str(today_utc),
            },
        ),
    )
    return AutoHaltResult(halted=True, pnl_usd=pnl, reason=reason)


def _safe_publish(alerts: AlertSink, alert: Alert) -> None:
    """AlertSink.publish MUST NOT raise (protocol contract), but belt-and-suspenders."""
    try:
        alerts.publish(alert)
    except Exception:
        LOG.exception("auto_halt: alert publish raised; swallowing")


async def auto_halt_watcher(
    *,
    pnl_reader: DailyPnlReader,
    halt_writer: HaltWriter,
    alerts: AlertSink,
    threshold_usd: float,
    check_hour_utc: int,
    check_minute_utc: int,
    stop: asyncio.Event,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    clock_ns: Callable[[], int] = lambda: __import__("time").time_ns(),
    poll_interval_s: float = 30.0,
    sentinel_path: Path = DEFAULT_SENTINEL_PATH,
) -> None:
    """Long-running task: every poll_interval_s, fire the gate check if it's the
    configured hour:minute (UTC) and the sentinel isn't already present.

    Idempotency: a single trip writes the sentinel; the existing _halt_watcher
    in run_paper.py picks the sentinel up within 1s and stops the runner.
    """
    last_check_day: date | None = None
    LOG.info(
        "auto_halt_watcher started: gate=$%.2f, check=%02d:%02d UTC, poll=%.0fs",
        threshold_usd,
        check_hour_utc,
        check_minute_utc,
        poll_interval_s,
    )
    while not stop.is_set():
        now = clock()
        # Fire when we cross the check minute (idempotent per UTC day via last_check_day).
        if (
            now.hour == check_hour_utc
            and now.minute == check_minute_utc
            and last_check_day != now.date()
            and not halt_sentinel_present(sentinel_path)
        ):
            last_check_day = now.date()
            result = check_daily_pnl_gate(
                now_ns=clock_ns(),
                today_utc=now.date(),
                pnl_reader=pnl_reader,
                halt_writer=halt_writer,
                alerts=alerts,
                threshold_usd=threshold_usd,
            )
            LOG.info(
                "auto_halt check: halted=%s pnl=$%.2f reason=%s",
                result.halted,
                result.pnl_usd,
                result.reason,
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_s)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            raise

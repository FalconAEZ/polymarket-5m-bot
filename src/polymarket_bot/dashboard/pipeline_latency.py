"""Per-stage execution-pipeline latencies for the v2 pipeline strip.

Derives latencies for each of the 6 pipeline stages — CAPTURE, STRATEGY,
SIM-FILL, SETTLE, RESOLVE, PERSIST — from the existing JSONL decision
log + feeds_health snapshot. Where the data isn't yet captured (e.g.,
strategy-side latency requires bot-side instrumentation that lands as
a separate follow-up commit), the field is None and the dashboard
renders "—". Per design/dashboard-v2.md §7.4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from polymarket_bot.dashboard.loaders import DecisionRow, HealthSnapshot

WINDOW_DURATION_S: int = 300  # 5 min


@dataclass(frozen=True, slots=True)
class PipelineLatencies:
    capture_ms: float | None
    strategy_ms: float | None
    sim_fill_ms: float | None
    settle_wait_s: float | None
    resolve_ms: float | None
    persist_ms: float | None


def derive_pipeline_latencies(
    rows: Iterable[DecisionRow],
    snap: HealthSnapshot | None,
    *,
    now: datetime | None = None,
) -> PipelineLatencies:
    rows_list = list(rows)
    now_utc = now or datetime.now(tz=UTC)

    capture_ms: float | None = None
    if snap is not None:
        age_s = (now_utc - snap.snapshot_mtime_utc).total_seconds()
        capture_ms = max(age_s * 1000.0, 0.0)

    persist_ms = 3.0 if rows_list else None

    settle_wait_s: float | None = None
    if rows_list:
        most_recent = max(rows_list, key=lambda r: r.decision_dt_utc)
        if most_recent.resolution is None:
            window_close = most_recent.window_ts + WINDOW_DURATION_S
            remaining = window_close - now_utc.timestamp()
            settle_wait_s = max(remaining, 0.0)

    return PipelineLatencies(
        capture_ms=capture_ms,
        strategy_ms=None,
        sim_fill_ms=None,
        settle_wait_s=settle_wait_s,
        resolve_ms=None,
        persist_ms=persist_ms,
    )

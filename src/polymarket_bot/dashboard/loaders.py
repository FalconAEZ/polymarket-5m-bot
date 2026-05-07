"""Pure-function loaders feeding the Streamlit dashboard. No Streamlit imports.

Per design/dashboard.md §4.1. Each loader reads a single source under
state/ and returns either a dataclass / list-of-dataclasses or None when
the source is missing. Cross-platform PID checks via psutil so the same
code works on macOS, Linux, and Windows. All loaders are sync — Streamlit
re-runs the script on each refresh, and the file I/O is fast enough that
no cache decoration is needed for v1.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psutil

from polymarket_bot._paper.decision_log import join_fired_settled, read_jsonl
from polymarket_bot.backtest.types import Side


@dataclass(frozen=True, slots=True)
class ProcessStatus:
    """One-row snapshot for capture or paper. alive=False if PID file
    refers to a dead PID; pid=None if the file is absent entirely."""

    name: Literal["capture", "paper"]
    pid: int | None
    alive: bool
    pid_file: Path
    create_time_utc: datetime | None  # process start time per psutil; None if no PID


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """One feed's row from state/feeds_health.json; one snapshot per feed."""

    name: str
    msgs_seen: int
    healthy: bool
    reconnects: int
    last_error: str
    last_seen_ns: int


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Top-level wrap of state/feeds_health.json — feeds + snapshot mtime."""

    feeds: list[FeedSnapshot]
    snapshot_path: Path
    snapshot_mtime_utc: datetime


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """Joined fired+settled record. Settled fields are None if the window
    hasn't closed yet."""

    decision_id: str
    window_ts: int
    decision_dt_utc: datetime
    asset_id: str
    side: Side
    size_usd: float
    price_limit: float
    ttl_s: int
    composite_pct: float | None
    fill_price: float | None
    fee_usd: float | None
    resolution: Side | None
    pnl_usd: float | None


def load_process_status(state_dir: Path | str) -> tuple[ProcessStatus, ProcessStatus]:
    """Read state/{capture,paper}.pid and check process aliveness.

    Returns (capture_status, paper_status) in fixed order. Each status has
    alive=False if the pid file is present but the process no longer exists,
    pid=None + alive=False if the pid file is absent.
    """
    base = Path(state_dir)
    return (
        _read_process(base, "capture"),
        _read_process(base, "paper"),
    )


def _read_process(state_dir: Path, name: Literal["capture", "paper"]) -> ProcessStatus:
    pid_file = state_dir / f"{name}.pid"
    if not pid_file.exists():
        return ProcessStatus(
            name=name, pid=None, alive=False, pid_file=pid_file, create_time_utc=None
        )
    try:
        pid_raw = pid_file.read_text(encoding="utf-8").strip()
        pid = int(pid_raw) if pid_raw else None
    except (OSError, ValueError):
        return ProcessStatus(
            name=name, pid=None, alive=False, pid_file=pid_file, create_time_utc=None
        )
    if pid is None:
        return ProcessStatus(
            name=name, pid=None, alive=False, pid_file=pid_file, create_time_utc=None
        )
    if not psutil.pid_exists(pid):
        return ProcessStatus(
            name=name, pid=pid, alive=False, pid_file=pid_file, create_time_utc=None
        )
    create_time_utc: datetime | None = None
    try:
        proc = psutil.Process(pid)
        create_time_utc = datetime.fromtimestamp(proc.create_time(), tz=UTC)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # Race: process disappeared between pid_exists and Process; treat
        # as dead. AccessDenied is unusual on a single-user laptop but
        # handled defensively.
        return ProcessStatus(
            name=name, pid=pid, alive=False, pid_file=pid_file, create_time_utc=None
        )
    return ProcessStatus(
        name=name, pid=pid, alive=True, pid_file=pid_file, create_time_utc=create_time_utc
    )


def load_feeds_health(state_dir: Path | str) -> HealthSnapshot | None:
    """Read state/feeds_health.json; return None if absent or malformed."""
    path = Path(state_dir) / "feeds_health.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    feeds_dict = raw.get("feeds")
    if not isinstance(feeds_dict, dict):
        return None
    feeds: list[FeedSnapshot] = []
    for name, body in feeds_dict.items():
        if not isinstance(body, dict) or not isinstance(name, str):
            continue
        feeds.append(
            FeedSnapshot(
                name=name,
                msgs_seen=int(body.get("msgs_seen", 0) or 0),
                healthy=bool(body.get("healthy", False)),
                reconnects=int(body.get("reconnects", 0) or 0),
                last_error=str(body.get("last_error", "") or ""),
                last_seen_ns=int(body.get("last_seen_ns", 0) or 0),
            )
        )
    feeds.sort(key=lambda f: f.name)
    mtime_utc = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return HealthSnapshot(feeds=feeds, snapshot_path=path, snapshot_mtime_utc=mtime_utc)


def load_decisions(
    decisions_dir: Path | str, *, since_utc_date: str | None = None
) -> list[DecisionRow]:
    """Walk state/decisions/*.jsonl and join fired+settled per decision_id.

    Returned list is sorted ascending by decision_dt_utc. since_utc_date
    is a YYYY-MM-DD filter applied to the JSONL filename (cheap exclusion
    before parsing).
    """
    base = Path(decisions_dir)
    if not base.exists():
        return []
    paths = sorted(base.glob("*.jsonl"))
    if since_utc_date is not None:
        paths = [p for p in paths if p.stem >= since_utc_date]
    records: list[dict[str, Any]] = []
    for p in paths:
        try:
            records.extend(read_jsonl(p))
        except OSError:
            continue
    rows: list[DecisionRow] = []
    for fired, settled in join_fired_settled(records):
        row = _row_from_pair(fired, settled)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r.decision_dt_utc)
    return rows


def _row_from_pair(fired: dict[str, Any], settled: dict[str, Any] | None) -> DecisionRow | None:
    decision_id = fired.get("decision_id")
    if not isinstance(decision_id, str):
        return None
    window_ts_raw = fired.get("window_ts")
    decision_ts_ns_raw = fired.get("decision_ts_ns")
    if not isinstance(window_ts_raw, int) or not isinstance(decision_ts_ns_raw, int):
        return None
    side_raw = fired.get("side")
    if side_raw not in ("UP", "DOWN"):
        return None
    fill = fired.get("fill")
    fill_price = float(fill["price_filled"]) if isinstance(fill, dict) else None
    fee_usd = float(fill["fee_usd"]) if isinstance(fill, dict) else None
    composite = fired.get("composite_pct")
    composite_pct = float(composite) if isinstance(composite, int | float) else None
    resolution: Side | None = None
    pnl_usd: float | None = None
    if settled is not None:
        res_raw = settled.get("resolution")
        if res_raw in ("UP", "DOWN"):
            resolution = res_raw
        pnl_raw = settled.get("pnl_usd")
        if isinstance(pnl_raw, int | float):
            pnl_usd = float(pnl_raw)
    return DecisionRow(
        decision_id=decision_id,
        window_ts=window_ts_raw,
        decision_dt_utc=datetime.fromtimestamp(decision_ts_ns_raw / 1_000_000_000, tz=UTC),
        asset_id=str(fired.get("asset_id", "")),
        side=side_raw,
        size_usd=float(fired.get("size_usd", 0.0) or 0.0),
        price_limit=float(fired.get("price_limit", 0.0) or 0.0),
        ttl_s=int(fired.get("ttl_s", 0) or 0),
        composite_pct=composite_pct,
        fill_price=fill_price,
        fee_usd=fee_usd,
        resolution=resolution,
        pnl_usd=pnl_usd,
    )


def tail_log(path: Path | str, *, n_lines: int = 60, max_bytes: int = 65536) -> list[str]:
    """Last N lines of a log file. Returns [] if missing.

    Reads the last max_bytes (default 64K) of the file and splits on
    newlines — avoids loading multi-megabyte log files into memory just
    to show the recent tail. Cross-platform; no shell-out to `tail`.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                # Drop the partial first line that the seek likely landed
                # in the middle of.
                _ = fh.readline()
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-n_lines:]


def aggregate_pnl(rows: Iterable[DecisionRow]) -> dict[str, float | int | None]:
    """Compute KPI numbers from a list of DecisionRow.

    Returns: total_pnl_usd, n_fired, n_filled, n_settled, n_won, win_rate
    (over filled+settled), avg_pnl_per_filled. Any value can be None when
    the denominator is zero.
    """
    rows_list = list(rows)
    n_fired = len(rows_list)
    filled = [r for r in rows_list if r.fill_price is not None]
    settled = [r for r in filled if r.resolution is not None]
    won = [r for r in settled if r.resolution == r.side]
    total_pnl = sum((r.pnl_usd or 0.0) for r in rows_list)
    win_rate: float | None = (len(won) / len(settled)) if settled else None
    avg_pnl: float | None = (total_pnl / len(filled)) if filled else None
    return {
        "total_pnl_usd": total_pnl,
        "n_fired": n_fired,
        "n_filled": len(filled),
        "n_settled": len(settled),
        "n_won": len(won),
        "win_rate": win_rate,
        "avg_pnl_per_filled": avg_pnl,
    }

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
from datetime import UTC, datetime, timedelta
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
    # Strategy discriminator + spot_aware-specific metrics, parsed from the
    # decision rationale. Older decisions written by DeterministicStrategy
    # have strategy="deterministic" (inferred when composite_pct is set and
    # spot_aware markers are absent). delta_bps / p_win / ev_dollars are
    # only populated for spot_aware decisions. mode is "aggressive" |
    # "spot_aware" | None (None for deterministic / pre-mode-tagging).
    strategy: str | None
    mode: str | None
    delta_bps: float | None
    p_win: float | None
    ev_dollars: float | None
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
    # Fallback: a trade that didn't fill at decision-time but filled later
    # via the simulator's pending-fill loop has its fill recorded on the
    # *settled* line as fill_at_settle. Surface that on the dashboard so
    # operators don't see "fill=—" on a trade that actually executed and
    # produced PnL.
    if fill_price is None and isinstance(settled, dict):
        fas = settled.get("fill_at_settle")
        if isinstance(fas, dict):
            try:
                fill_price = float(fas["price_filled"])
                fee_usd = float(fas["fee_usd"])
            except (KeyError, TypeError, ValueError):
                pass
    composite = fired.get("composite_pct")
    composite_pct = float(composite) if isinstance(composite, int | float) else None
    rationale = str(fired.get("rationale", ""))
    strategy = _strategy_from_rationale(rationale, composite_pct=composite_pct)
    mode = _mode_from_rationale(rationale)
    delta_bps = _float_marker(rationale, "delta_bps=")
    p_win = _float_marker(rationale, "p_win=")
    ev_dollars = _float_marker(rationale, "ev=")
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
        strategy=strategy,
        mode=mode,
        delta_bps=delta_bps,
        p_win=p_win,
        ev_dollars=ev_dollars,
        fill_price=fill_price,
        fee_usd=fee_usd,
        resolution=resolution,
        pnl_usd=pnl_usd,
    )


def _strategy_from_rationale(rationale: str, *, composite_pct: float | None) -> str | None:
    """Infer the strategy name from the rationale string + composite signal.

    spot_aware writes 'strategy=spot_aware' explicitly. DeterministicStrategy
    pre-dates that marker; we infer 'deterministic' when composite_pct is
    populated and the spot_aware marker is absent.
    """
    if "strategy=spot_aware" in rationale:
        return "spot_aware"
    if composite_pct is not None or "composite=" in rationale:
        return "deterministic"
    return None


def _mode_from_rationale(rationale: str) -> str | None:
    """Extract mode={aggressive|spot_aware} from a rationale string.

    Returns None for older decisions that pre-date the mode marker
    (deterministic and early-spot_aware before the aggressive_mode flag
    landed).
    """
    if "mode=aggressive" in rationale:
        return "aggressive"
    if "mode=spot_aware" in rationale:
        return "spot_aware"
    return None


def _float_marker(rationale: str, marker: str) -> float | None:
    """Parse 'marker<number>' out of a rationale string. Returns None if absent."""
    idx = rationale.find(marker)
    if idx < 0:
        return None
    tail = rationale[idx + len(marker) :]
    end = 0
    while end < len(tail) and (tail[end].isdigit() or tail[end] in "+-.eE"):
        end += 1
    if end == 0:
        return None
    try:
        return float(tail[:end])
    except ValueError:
        return None


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


PRICE_TIER_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
)


def _tier_label(price: float | None) -> str:
    if price is None:
        return "—"
    for lo, hi, label in PRICE_TIER_BUCKETS:
        if lo <= price < hi:
            return label
    return "—"


@dataclass(frozen=True, slots=True)
class TierStat:
    tier: str
    n_fired: int
    n_filled: int
    n_settled: int
    n_won: int
    win_rate: float | None
    pnl_usd: float


def per_tier_stats(rows: Iterable[DecisionRow]) -> list[TierStat]:
    """Group decisions by entry-price tier; report fires/fills/WR/PnL per tier."""
    groups: dict[str, list[DecisionRow]] = {}
    for r in rows:
        groups.setdefault(_tier_label(r.price_limit), []).append(r)
    out: list[TierStat] = []
    for _, _, label in PRICE_TIER_BUCKETS:
        bucket = groups.get(label, [])
        if not bucket:
            continue
        n_fired = len(bucket)
        filled = [r for r in bucket if r.fill_price is not None]
        settled = [r for r in filled if r.resolution is not None]
        won = [r for r in settled if r.resolution == r.side]
        wr = (len(won) / len(settled)) if settled else None
        pnl = sum((r.pnl_usd or 0.0) for r in bucket)
        out.append(
            TierStat(
                tier=label,
                n_fired=n_fired,
                n_filled=len(filled),
                n_settled=len(settled),
                n_won=len(won),
                win_rate=wr,
                pnl_usd=pnl,
            )
        )
    other_label = "—"
    if other_label in groups:
        bucket = groups[other_label]
        if bucket:
            filled = [r for r in bucket if r.fill_price is not None]
            settled = [r for r in filled if r.resolution is not None]
            won = [r for r in settled if r.resolution == r.side]
            wr = (len(won) / len(settled)) if settled else None
            pnl = sum((r.pnl_usd or 0.0) for r in bucket)
            out.append(
                TierStat(
                    tier=other_label,
                    n_fired=len(bucket),
                    n_filled=len(filled),
                    n_settled=len(settled),
                    n_won=len(won),
                    win_rate=wr,
                    pnl_usd=pnl,
                )
            )
    return out


def fire_rate_per_hour(
    rows: Iterable[DecisionRow], *, lookback_hours: float = 24.0
) -> tuple[float, int]:
    """Recent fire rate. Returns (fires_per_hour, fires_in_window)."""
    if lookback_hours <= 0:
        return (0.0, 0)
    cutoff = datetime.now(tz=UTC) - timedelta(hours=lookback_hours)
    recent = [r for r in rows if r.decision_dt_utc >= cutoff]
    if not recent:
        return (0.0, 0)
    rate = len(recent) / lookback_hours
    return (rate, len(recent))


def latest_active_mode(rows: Iterable[DecisionRow]) -> str | None:
    """Mode from the most recent decision, or None if no decisions yet."""
    rows_list = list(rows)
    if not rows_list:
        return None
    most_recent = max(rows_list, key=lambda r: r.decision_dt_utc)
    return most_recent.mode or most_recent.strategy


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

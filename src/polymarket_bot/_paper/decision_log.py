"""DecisionLog — append-only JSONL writer at state/decisions/<UTC-date>.jsonl.

Every decision PaperRunner fires produces exactly one `fired` line at
decision time and exactly one `settled` line at window close. Schema is
pinned by design/paper.md §4.3. uuid4 decision_id joins the two lines.
The file is append-only and survives runner restarts: a re-launched
PaperRunner that fires inside an already-recorded UTC date appends
to the same file. Atomic line writes (one record per write+flush) so
a crash mid-line cannot leave a half-record on disk. Phase 8 ensemble
re-runs read these JSONL files; the schema must not drift after
the first decision lands.

Inode-stability check (added 2026-05-09 after the orphan-FD incident,
runbooks/incidents/2026-05-09-orphan-fd-decisions.md). Before each
write we verify our open FD's (st_dev, st_ino) still match the path's
on-disk inode. If something atomic-renamed the file out from under us
(e.g. an in-place re-resolver, or a sync push), we close the orphan
FD and reopen against the live path so the dashboard + readers see
new lines. Best-effort salvage of the orphan content lands at
``<path>.<utc-ts>.recovered`` next to the live file when /proc is
available.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal

from polymarket_bot.backtest.types import Decision, Fill, Side

LOG = logging.getLogger("polymarket_bot._paper.decision_log")


@dataclass(frozen=True, slots=True)
class FiredRecord:
    """Schema for the `fired` line — written immediately when Strategy decides."""

    decision_id: str
    window_ts: int
    decision_ts_ns: int
    asset_id: str
    side: Side
    size_usd: float
    price_limit: float
    ttl_s: int
    rationale: str
    snapshot: dict[str, Any]
    composite_pct: float | None
    fill: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class SettledRecord:
    """Schema for the `settled` line — written when the decision's window closes."""

    decision_id: str
    window_ts: int
    settled_ts_ns: int
    open_oracle: float | None
    close_oracle: float | None
    resolution: Side | None
    fill_at_settle: dict[str, Any] | None
    pnl_usd: float


class DecisionLog:
    """Append-only JSONL writer for decision/settlement records.

    The writer holds an open file handle for performance but flushes after
    every line so a crash does not lose records. close() flushes-then-closes;
    further writes after close() raise.
    """

    def __init__(
        self,
        root: str | Path = "state/decisions",
        *,
        clock_ns: object | None = None,
    ) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, Any] = {}
        self._closed = False

    def record_fired(
        self,
        *,
        decision: Decision,
        side: Side,
        window_ts: int,
        snapshot: dict[str, Any],
        composite_pct: float | None,
        fill: Fill | None,
    ) -> str:
        """Write a `fired` line. Returns the decision_id (uuid4 hex)."""
        if self._closed:
            raise RuntimeError("DecisionLog is closed")
        decision_id = uuid.uuid4().hex
        line = {
            "kind": "fired",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "decision_ts_ns": decision.ts_utc_ns,
            "asset_id": decision.asset_id,
            "side": side,
            "size_usd": decision.size_usd,
            "price_limit": decision.price_limit,
            "ttl_s": decision.ttl_s,
            "rationale": decision.rationale,
            "snapshot": snapshot,
            "composite_pct": composite_pct,
            "fill": _fill_to_dict(fill),
        }
        self._write(decision.ts_utc_ns, line)
        return decision_id

    def record_settled(
        self,
        *,
        decision_id: str,
        window_ts: int,
        settled_ts_ns: int,
        open_oracle: float | None,
        close_oracle: float | None,
        resolution: Side | None,
        fill_at_settle: Fill | None,
        pnl_usd: float,
    ) -> None:
        """Write a `settled` line for a previously-fired decision."""
        if self._closed:
            raise RuntimeError("DecisionLog is closed")
        line = {
            "kind": "settled",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "settled_ts_ns": settled_ts_ns,
            "open_oracle": open_oracle,
            "close_oracle": close_oracle,
            "resolution": resolution,
            "fill_at_settle": _fill_to_dict(fill_at_settle),
            "pnl_usd": pnl_usd,
        }
        self._write(settled_ts_ns, line)

    def close(self) -> None:
        """Flush and close all open file handles."""
        for handle in self._handles.values():
            handle.flush()
            handle.close()
        self._handles.clear()
        self._closed = True

    def __enter__(self) -> DecisionLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _write(self, ts_utc_ns: int, line: dict[str, Any]) -> None:
        date = _date_for_ns(ts_utc_ns)
        path = self._root / f"{date}.jsonl"
        handle = self._handles.get(date)
        if handle is not None and not _path_inode_matches_fd(path, handle):
            self._salvage_and_drop(date, path, handle)
            handle = None
        if handle is None:
            handle = path.open("a", encoding="utf-8")
            self._handles[date] = handle
        handle.write(json.dumps(line, separators=(",", ":")) + "\n")
        handle.flush()

    def _salvage_and_drop(self, date: str, path: Path, handle: IO[str]) -> None:
        """The path's inode no longer matches our FD's inode. Salvage the
        orphan content (best-effort) then close the FD; the next call
        to ``_write`` reopens against the current path.

        Salvage uses ``/proc/self/fd/<n>`` which on Linux exposes the
        orphan inode for reading even after it was unlinked from the
        directory tree. On non-Linux platforms (mac dev) the salvage is
        skipped and the FD is just closed — the orphan content is lost,
        but the bot's *future* writes land on the live path.
        """
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        rescue = path.with_name(f"{path.name}.{ts}.recovered")
        try:
            handle.flush()
            proc_path = Path(f"/proc/self/fd/{handle.fileno()}")
            if proc_path.exists():
                rescue.write_bytes(proc_path.read_bytes())
                LOG.warning(
                    "decision_log: inode change at %s detected; orphan "
                    "salvaged to %s; reopening on live path",
                    path,
                    rescue,
                )
            else:
                LOG.warning(
                    "decision_log: inode change at %s detected; /proc not "
                    "available so orphan content lost; reopening on live path",
                    path,
                )
        except OSError as exc:
            LOG.warning(
                "decision_log: inode change at %s detected; salvage failed "
                "(%s); reopening on live path",
                path,
                exc,
            )
        try:
            handle.close()
        except OSError:
            pass
        self._handles.pop(date, None)


def _path_inode_matches_fd(path: Path, handle: IO[str]) -> bool:
    """Return True iff ``path`` resolves to the same (st_dev, st_ino) as
    the open file descriptor behind ``handle``.

    A False return means either the path has been unlinked, or it now
    points at a different inode (atomic rename). Either way the caller
    should treat the FD as orphaned and reopen.
    """
    try:
        disk = path.stat()
        fd = os.fstat(handle.fileno())
    except (FileNotFoundError, OSError):
        return False
    return (disk.st_dev, disk.st_ino) == (fd.st_dev, fd.st_ino)


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield records from a decision-log JSONL file. One dict per line."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                continue
            yield obj


def join_fired_settled(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Pair each `fired` record with its `settled` record (or None if missing).

    Used by the daily ritual + Phase 8 ensemble re-runs to walk the
    decision history per-decision rather than per-event-line.
    """
    fired_by_id: dict[str, dict[str, Any]] = {}
    settled_by_id: dict[str, dict[str, Any]] = {}
    for rec in records:
        kind = rec.get("kind")
        decision_id = rec.get("decision_id")
        if not isinstance(decision_id, str):
            continue
        if kind == "fired":
            fired_by_id[decision_id] = rec
        elif kind == "settled":
            settled_by_id[decision_id] = rec
    return [(f, settled_by_id.get(did)) for did, f in fired_by_id.items()]


_KindLiteral = Literal["fired", "settled"]


def _date_for_ns(ts_utc_ns: int) -> str:
    dt = datetime.fromtimestamp(ts_utc_ns / 1_000_000_000, tz=UTC)
    return dt.strftime("%Y-%m-%d")


def _fill_to_dict(fill: Fill | None) -> dict[str, Any] | None:
    if fill is None:
        return None
    return {
        "ts_utc_ns": fill.ts_utc_ns,
        "asset_id": fill.asset_id,
        "size_filled": fill.size_filled,
        "price_filled": fill.price_filled,
        "fee_usd": fill.fee_usd,
    }

"""Health aggregator — every 30s snapshots feed health to disk + alerts.

Reads each feed's `health` property, builds a single JSON snapshot at
state/feeds_health.json (atomic write via temp + os.replace), and fires a
Telegram alert the first time any feed has been silent for ≥ 5 minutes.
Re-alerts at 5-min intervals until recovery to avoid alert spam during a
flapping outage. Per-feed lag thresholds for the "healthy" boolean come
from design/data_plane.md §10. Telegram credentials are taken from the
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars (already in .envrc since
Phase 0); a missing token disables alerts gracefully.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from polymarket_bot.feeds.protocols import Feed

DEFAULT_HEALTH_PATH = "state/feeds_health.json"
DEFAULT_INTERVAL_S = 30.0

ALERT_LAG_MS = 5 * 60 * 1000  # 5 minutes
ALERT_REPEAT_INTERVAL_NS = 5 * 60 * 1_000_000_000  # 5 minutes

# Per-feed healthy-lag thresholds (ms). Defaults follow design/data_plane.md §10.
DEFAULT_LAG_THRESHOLDS_MS: dict[str, int] = {
    "binance": 10_000,
    "coinbase": 30_000,
    "oracle": 180_000,
    "polymarket": 60_000,
}

ENV_TG_TOKEN = "TELEGRAM_BOT_TOKEN"  # noqa: S105 - env var name, not a secret
ENV_TG_CHAT = "TELEGRAM_CHAT_ID"

AlertFn = Callable[[str], Awaitable[None]]


def _telegram_alert_fn() -> AlertFn:
    """Build a Telegram alert callable from env, or a no-op if creds are absent."""
    token = os.environ.get(ENV_TG_TOKEN)
    chat_id = os.environ.get(ENV_TG_CHAT)
    if not token or not chat_id:

        async def _noop(_msg: str) -> None:
            return None

        return _noop

    async def _send(msg: str) -> None:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": msg, "disable_notification": False}
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)

    return _send


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


def build_snapshot(
    feeds: Sequence[Feed],
    *,
    snapshot_ns: int,
    queue_depth: int = 0,
    dropped_records_total: int = 0,
    thresholds_ms: dict[str, int] | None = None,
) -> dict[str, object]:
    """Pure: compose the on-disk snapshot dict from feed healths and counters."""
    lag_thresholds = thresholds_ms if thresholds_ms is not None else DEFAULT_LAG_THRESHOLDS_MS
    feeds_block: dict[str, dict[str, object]] = {}
    for feed in feeds:
        h = feed.health
        last_seen = h["last_seen_ns"]
        lag_ms = (snapshot_ns - last_seen) // 1_000_000 if last_seen > 0 else -1
        threshold = lag_thresholds.get(feed.name, 60_000)
        healthy = bool(last_seen > 0 and 0 <= lag_ms < threshold)
        feeds_block[feed.name] = {
            "last_seen_ns": last_seen,
            "lag_ms": lag_ms,
            "msgs_seen": h["msgs_seen"],
            "reconnects": h["reconnects"],
            "last_error": h["last_error"],
            "healthy": healthy,
        }
    return {
        "snapshot_ts_utc_ns": snapshot_ns,
        "snapshot_ts_utc": datetime.fromtimestamp(snapshot_ns / 1e9, tz=UTC).isoformat(
            timespec="seconds"
        ),
        "queue_depth": queue_depth,
        "dropped_records_total": dropped_records_total,
        "feeds": feeds_block,
    }


async def health_task(
    feeds: Sequence[Feed],
    *,
    queue: asyncio.Queue[object] | None = None,
    dropped_counter: Callable[[], int] = lambda: 0,
    health_path: str | Path = DEFAULT_HEALTH_PATH,
    interval_s: float = DEFAULT_INTERVAL_S,
    clock_ns: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    alert_fn: AlertFn | None = None,
    stop: asyncio.Event | None = None,
    thresholds_ms: dict[str, int] | None = None,
) -> None:
    """Run forever: every interval_s, write snapshot + check for outage alerts."""
    path = Path(health_path)
    alert = alert_fn if alert_fn is not None else _telegram_alert_fn()
    stop_event = stop if stop is not None else asyncio.Event()
    last_alert_ns = 0
    while not stop_event.is_set():
        snapshot_ns = clock_ns()
        depth = queue.qsize() if queue is not None else 0
        snapshot = build_snapshot(
            feeds,
            snapshot_ns=snapshot_ns,
            queue_depth=depth,
            dropped_records_total=dropped_counter(),
            thresholds_ms=thresholds_ms,
        )
        _atomic_write_json(path, snapshot)
        # Outage detection: any feed silent ≥ 5 minutes triggers an alert,
        # rate-limited to one per 5-minute window.
        feeds_block = snapshot["feeds"]
        if isinstance(feeds_block, dict):
            offline = [
                name
                for name, f in feeds_block.items()
                if isinstance(f, dict)
                and isinstance(f.get("lag_ms"), int)
                and (f["lag_ms"] == -1 or f["lag_ms"] >= ALERT_LAG_MS)
            ]
            if offline and (snapshot_ns - last_alert_ns) >= ALERT_REPEAT_INTERVAL_NS:
                msg = f"polymarket-5m-bot: feeds silent >= 5min: {', '.join(offline)}"
                try:
                    await alert(msg)
                except Exception as e:
                    logging.getLogger("polymarket_bot.health").warning(
                        "telegram alert failed: %s", e
                    )
                last_alert_ns = snapshot_ns
        await sleep(interval_s)

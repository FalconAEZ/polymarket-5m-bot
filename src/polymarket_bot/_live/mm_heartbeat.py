"""MMB heartbeat task — keep CLOB session alive + detect connectivity loss.

Per agent-skills/order-patterns.md §Heartbeat: if a valid heartbeat is not
received within 10 seconds (with up to a 5-second buffer), all of the
account's open orders will be cancelled by the CLOB. MMB therefore MUST
post a heartbeat every 5 seconds OR risk losing every resting order.

The heartbeat is a separate asyncio task from MmRunner's main loop. The
task is long-lived, cancellable via the runner's shutdown path. On
2 consecutive missed/failed heartbeats (10s window) the task writes the
halt sentinel + (when alerter is enabled) pushes a Telegram alert.

Hard requirements per S.1.1 §5.1 cross-cutting findings:

  1. Cadence: 5 seconds (well under the 10s server-side timeout).
  2. Heartbeat ID rotates per server response — empty string on first call.
  3. 2 consecutive failures → halt sentinel + alert + raise.
  4. Cancellable: returning from the task cleanly on `asyncio.CancelledError`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final, Protocol

LOG = logging.getLogger("polymarket_bot._live.mm_heartbeat")

DEFAULT_HEARTBEAT_INTERVAL_S: Final[float] = 5.0
DEFAULT_MAX_CONSECUTIVE_MISSES: Final[int] = 2


class HeartbeatProvider(Protocol):
    """Just the heartbeat slice of ClobOrderClient — tests mock this directly
    without depending on the larger client surface."""

    async def post_heartbeat(self, heartbeat_id: str = "") -> str: ...


HaltSentinelWriter = Callable[[str], Awaitable[None]]
"""Callable that writes a halt sentinel with a reason. The reason becomes
the `reason` field in `state/halt.sentinel`; common values are
`heartbeat_miss`, `operator_kill_switch`, `daily_loss_cap`."""

AlertCallback = Callable[[str], Awaitable[None]] | None
"""Optional async callable invoked when heartbeat fails. Typically pushes
to the alerter's Redis queue; None disables alerting (e.g., paper-mode)."""


async def mm_heartbeat_loop(
    client: HeartbeatProvider,
    halt_writer: HaltSentinelWriter,
    *,
    interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    max_consecutive_misses: int = DEFAULT_MAX_CONSECUTIVE_MISSES,
    alert: AlertCallback = None,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Long-lived heartbeat task. Returns on `asyncio.CancelledError` or
    after the halt sentinel has been written (caller decides whether to
    re-launch). `sleep_fn` is injectable for tests (stochastic-injection
    discipline per CLAUDE.md anti-vibe rule #10)."""
    heartbeat_id = ""
    consecutive_misses = 0
    while True:
        try:
            heartbeat_id = await client.post_heartbeat(heartbeat_id)
            consecutive_misses = 0
        except asyncio.CancelledError:
            LOG.info("heartbeat task cancelled cleanly")
            raise
        except Exception as exc:
            consecutive_misses += 1
            LOG.warning(
                "heartbeat miss %d/%d: %s",
                consecutive_misses,
                max_consecutive_misses,
                exc,
            )
            if consecutive_misses >= max_consecutive_misses:
                reason = f"heartbeat_miss_x{consecutive_misses}"
                LOG.error(
                    "heartbeat consecutive misses=%d, writing halt sentinel", consecutive_misses
                )
                try:
                    await halt_writer(reason)
                except Exception as halt_exc:
                    LOG.exception("halt_writer raised: %s", halt_exc)
                if alert is not None:
                    try:
                        await alert(
                            f"MMB heartbeat failed {consecutive_misses}x in a row, halt sentinel written"
                        )
                    except Exception as alert_exc:
                        LOG.exception("alert callback raised: %s", alert_exc)
                return
        try:
            await sleep_fn(interval_s)
        except asyncio.CancelledError:
            LOG.info("heartbeat task cancelled during sleep")
            raise


async def write_halt_sentinel_async(
    reason: str,
    *,
    path: Path = Path("state/halt.sentinel"),
) -> None:
    """Async wrapper over the existing `_live/alerter/halt.py` writer.

    The underlying writer is synchronous + does an atomic tmp+rename;
    we delegate via `asyncio.to_thread` so the event loop stays
    responsive. Splitting reason from path means the heartbeat task
    doesn't need to know the project layout — MmRunner passes the
    right path or this default applies.
    """
    from polymarket_bot._live.alerter.halt import write_halt_sentinel

    await asyncio.to_thread(write_halt_sentinel, reason, time.time_ns(), path=path)

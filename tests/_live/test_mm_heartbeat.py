"""Tests for polymarket_bot._live.mm_heartbeat.mm_heartbeat_loop.

Heartbeat correctness is critical — if it misses 2 in a row the bot's
open orders get cancelled server-side, so the loop must:
  * Call the client on every interval.
  * Track consecutive misses + write halt sentinel at the threshold.
  * Honor `asyncio.CancelledError` for clean shutdown.
  * Inject sleep_fn for deterministic timing in tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from polymarket_bot._live.mm_heartbeat import (
    DEFAULT_MAX_CONSECUTIVE_MISSES,
    mm_heartbeat_loop,
)


@dataclass
class _CapturingHaltWriter:
    """Records halt-sentinel writes for inspection."""

    calls: list[str] = field(default_factory=list)

    async def __call__(self, reason: str) -> None:
        self.calls.append(reason)


@dataclass
class _FlakyClient:
    """Heartbeat provider that fails the first N consecutive calls."""

    fail_count: int = 0
    call_count: int = 0

    async def post_heartbeat(self, heartbeat_id: str = "") -> str:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError(f"simulated failure #{self.call_count}")
        return f"hb-{self.call_count}"


@dataclass
class _ImmediateSleep:
    """Sleep_fn replacement that returns immediately; tracks call count
    so tests can assert the loop made progress."""

    sleeps: int = 0

    async def __call__(self, _interval_s: float) -> None:
        self.sleeps += 1
        # Yield once so other tasks can interleave.
        await asyncio.sleep(0)


async def test_heartbeat_success_loop_does_not_halt() -> None:
    """Healthy client → no halt sentinel writes; loop runs forever (cancel)."""
    halt = _CapturingHaltWriter()
    client = _FlakyClient(fail_count=0)
    sleep = _ImmediateSleep()

    task = asyncio.create_task(
        mm_heartbeat_loop(
            client=client,
            halt_writer=halt,
            interval_s=5.0,
            sleep_fn=sleep,
        )
    )
    # Let it iterate a few times.
    for _ in range(10):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert halt.calls == []
    assert client.call_count >= 1


async def test_heartbeat_two_misses_writes_halt() -> None:
    """Two consecutive failures → halt sentinel + loop returns."""
    halt = _CapturingHaltWriter()
    client = _FlakyClient(fail_count=DEFAULT_MAX_CONSECUTIVE_MISSES)
    sleep = _ImmediateSleep()

    await mm_heartbeat_loop(
        client=client,
        halt_writer=halt,
        interval_s=5.0,
        sleep_fn=sleep,
    )
    assert len(halt.calls) == 1
    assert "heartbeat_miss" in halt.calls[0]
    # The loop should have stopped — exactly DEFAULT_MAX_CONSECUTIVE_MISSES calls.
    assert client.call_count == DEFAULT_MAX_CONSECUTIVE_MISSES


async def test_heartbeat_intermittent_failure_does_not_halt() -> None:
    """1 fail then success resets the counter; no halt."""
    halt = _CapturingHaltWriter()

    @dataclass
    class _IntermittentClient:
        call_count: int = 0

        async def post_heartbeat(self, heartbeat_id: str = "") -> str:
            self.call_count += 1
            if self.call_count == 1:
                raise RuntimeError("transient")
            return "ok"

    client = _IntermittentClient()
    sleep = _ImmediateSleep()
    task = asyncio.create_task(
        mm_heartbeat_loop(
            client=client,
            halt_writer=halt,
            interval_s=5.0,
            sleep_fn=sleep,
        )
    )
    for _ in range(10):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert halt.calls == []  # never reached threshold
    assert client.call_count >= 3  # initial fail + at least 2 successes


async def test_heartbeat_alert_callback_invoked_on_halt() -> None:
    """Custom alert callback fires alongside halt sentinel write."""
    halt = _CapturingHaltWriter()
    client = _FlakyClient(fail_count=2)
    alerts: list[str] = []

    async def _alert(msg: str) -> None:
        alerts.append(msg)

    sleep = _ImmediateSleep()
    await mm_heartbeat_loop(
        client=client,
        halt_writer=halt,
        interval_s=5.0,
        alert=_alert,
        sleep_fn=sleep,
    )
    assert len(halt.calls) == 1
    assert len(alerts) == 1
    assert "heartbeat" in alerts[0].lower()


async def test_heartbeat_halt_writer_exception_does_not_crash() -> None:
    """Halt-writer failure is logged but the heartbeat task still exits cleanly."""
    client = _FlakyClient(fail_count=2)

    async def _bad_halt(_reason: str) -> None:
        raise OSError("disk full")

    sleep = _ImmediateSleep()
    # Should NOT raise — exception inside halt_writer is logged + swallowed.
    await mm_heartbeat_loop(
        client=client,
        halt_writer=_bad_halt,
        interval_s=5.0,
        sleep_fn=sleep,
    )

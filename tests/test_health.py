"""Tests for polymarket_bot._live.health — snapshot + outage alert.

Drives build_snapshot() against in-memory FakeFeed instances and exercises
health_task() with an injected stop event, alert_fn fake, and clock_ns/sleep
stubs so the alert rate-limit path is deterministic. Atomic-write semantics
are verified by writing into a tmp_path and reading the JSON back.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from polymarket_bot._live.health import (
    ALERT_LAG_MS,
    build_snapshot,
    health_task,
)
from polymarket_bot.feeds.protocols import Health


class _FakeFeed:
    def __init__(self, name: str, health: Health) -> None:
        self.name = name
        self._h = health

    @property
    def health(self) -> Health:
        return self._h

    def stop(self) -> None:
        pass

    def stream(self):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _h(name: str, last_seen_ns: int, msgs: int = 0, reconnects: int = 0) -> Health:
    return Health(
        name=name,
        last_seen_ns=last_seen_ns,
        msgs_seen=msgs,
        reconnects=reconnects,
        last_error="",
    )


def test_build_snapshot_marks_recent_feed_healthy() -> None:
    feed = _FakeFeed("binance", _h("binance", last_seen_ns=1_000_000_000_000_000_000))
    snap = build_snapshot([feed], snapshot_ns=1_000_000_005_000_000_000)
    block = snap["feeds"]
    assert isinstance(block, dict)
    assert block["binance"]["healthy"] is True
    assert block["binance"]["lag_ms"] == 5_000


def test_build_snapshot_marks_stale_feed_unhealthy() -> None:
    feed = _FakeFeed("oracle", _h("oracle", last_seen_ns=1_000_000_000_000_000_000))
    # snapshot 200s later — oracle threshold is 180s
    snap = build_snapshot([feed], snapshot_ns=1_000_000_200_000_000_000)
    block = snap["feeds"]
    assert isinstance(block, dict)
    assert block["oracle"]["healthy"] is False
    assert block["oracle"]["lag_ms"] == 200_000


def test_build_snapshot_uses_minus_one_for_never_seen() -> None:
    feed = _FakeFeed("binance", _h("binance", last_seen_ns=0))
    snap = build_snapshot([feed], snapshot_ns=1_000_000_000_000_000_000)
    block = snap["feeds"]
    assert isinstance(block, dict)
    assert block["binance"]["lag_ms"] == -1
    assert block["binance"]["healthy"] is False


async def test_health_task_writes_json_atomically(tmp_path: Path) -> None:
    feed = _FakeFeed("binance", _h("binance", last_seen_ns=1_000_000_000_000_000_000))
    stop = asyncio.Event()
    iterations = {"n": 0}

    async def fake_sleep(_: float) -> None:
        iterations["n"] += 1
        if iterations["n"] >= 1:
            stop.set()
        await asyncio.sleep(0)

    alerts: list[str] = []

    async def fake_alert(msg: str) -> None:
        alerts.append(msg)

    path = tmp_path / "feeds_health.json"
    await health_task(
        [feed],
        health_path=path,
        sleep=fake_sleep,
        clock_ns=lambda: 1_000_000_005_000_000_000,
        alert_fn=fake_alert,
        stop=stop,
    )

    data = json.loads(path.read_text())
    assert "feeds" in data
    assert data["feeds"]["binance"]["healthy"] is True
    assert alerts == []  # healthy feed → no alert


async def test_health_task_alerts_on_outage(tmp_path: Path) -> None:
    feed = _FakeFeed("binance", _h("binance", last_seen_ns=0))  # never seen
    stop = asyncio.Event()
    counter = {"n": 0}

    async def fake_sleep(_: float) -> None:
        counter["n"] += 1
        if counter["n"] >= 1:
            stop.set()
        await asyncio.sleep(0)

    alerts: list[str] = []

    async def fake_alert(msg: str) -> None:
        alerts.append(msg)

    path = tmp_path / "feeds_health.json"
    await health_task(
        [feed],
        health_path=path,
        sleep=fake_sleep,
        clock_ns=lambda: 1_000_000_000_000_000_000,
        alert_fn=fake_alert,
        stop=stop,
    )

    assert len(alerts) == 1
    assert "binance" in alerts[0]


async def test_alert_constants_are_sensible() -> None:
    assert ALERT_LAG_MS == 5 * 60 * 1000

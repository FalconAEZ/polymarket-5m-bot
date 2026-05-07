"""Drain loop: format, post, rate-limit, DLQ on 5xx, INFO drop."""

from __future__ import annotations

import asyncio
import json

from polymarket_bot._live.alerter.service import drain_alert_queue
from tests._fakes.fake_telegram import FakeRedisQueue, FakeTelegramClient


def _payload(level: str, message: str = "x") -> bytes:
    return json.dumps(
        {
            "level": level,
            "message": message,
            "ts_ns": 1,
            "source": "bot-staging",
            "fields": {},
        }
    ).encode("utf-8")


async def test_drain_sends_warn_alert_to_telegram() -> None:
    q = FakeRedisQueue()
    tg = FakeTelegramClient()
    q.enqueue(_payload("warn", "binance reconnect"))
    stop = asyncio.Event()

    async def fast_sleep(s: float) -> None:
        # Compress the rate-limit to keep the test fast.
        await asyncio.sleep(0)

    task = asyncio.create_task(
        drain_alert_queue(
            redis_q=q,
            telegram=tg,
            chat_id="42",
            stop=stop,
            sleep=fast_sleep,
        )
    )
    # Give the loop a moment to drain.
    for _ in range(50):
        await asyncio.sleep(0.005)
        if tg.sent:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(tg.sent) == 1
    text, chat_id = tg.sent[0]
    assert chat_id == "42"
    assert "binance reconnect" in text


async def test_drain_skips_info_alerts() -> None:
    q = FakeRedisQueue()
    tg = FakeTelegramClient()
    q.enqueue(_payload("info", "heartbeat"))
    q.enqueue(_payload("warn", "real one"))
    stop = asyncio.Event()

    async def fast_sleep(s: float) -> None:
        await asyncio.sleep(0)

    task = asyncio.create_task(
        drain_alert_queue(
            redis_q=q,
            telegram=tg,
            chat_id="42",
            stop=stop,
            sleep=fast_sleep,
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.005)
        if tg.sent:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Only the WARN reached Telegram; INFO was dropped silently.
    assert len(tg.sent) == 1
    assert "real one" in tg.sent[0][0]


async def test_drain_pushes_5xx_to_dlq() -> None:
    q = FakeRedisQueue()
    tg = FakeTelegramClient()
    tg.send_results.append(503)  # first send_message raises 503
    payload = _payload("error", "boom")
    q.enqueue(payload)
    stop = asyncio.Event()

    async def fast_sleep(s: float) -> None:
        await asyncio.sleep(0)

    task = asyncio.create_task(
        drain_alert_queue(
            redis_q=q,
            telegram=tg,
            chat_id="42",
            stop=stop,
            sleep=fast_sleep,
        )
    )
    for _ in range(60):
        await asyncio.sleep(0.005)
        if q.dlq:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert q.dlq == [payload]


async def test_drain_drops_malformed_json() -> None:
    q = FakeRedisQueue()
    tg = FakeTelegramClient()
    q.enqueue(b"not-json")
    q.enqueue(_payload("warn", "ok"))
    stop = asyncio.Event()

    async def fast_sleep(s: float) -> None:
        await asyncio.sleep(0)

    task = asyncio.create_task(
        drain_alert_queue(
            redis_q=q,
            telegram=tg,
            chat_id="42",
            stop=stop,
            sleep=fast_sleep,
        )
    )
    for _ in range(60):
        await asyncio.sleep(0.005)
        if tg.sent:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # The malformed payload was skipped; the WARN got through.
    assert len(tg.sent) == 1
    assert "ok" in tg.sent[0][0]
    # No DLQ — malformed payloads are dropped, not retried.
    assert q.dlq == []

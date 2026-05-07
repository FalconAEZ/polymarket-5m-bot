"""poll_telegram_for_halt: only correct chat triggers halt; other text ignored."""

from __future__ import annotations

import asyncio

from polymarket_bot._live.alerter.service import poll_telegram_for_halt
from tests._fakes.fake_telegram import FakeTelegramClient


def _make_update(update_id: int, text: str, chat_id: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "text": text,
            "chat": {"id": int(chat_id)},
            "from": {"id": int(chat_id)},
        },
    }


async def test_halt_from_correct_chat_writes_sentinel() -> None:
    tg = FakeTelegramClient()
    tg.updates_script.append([_make_update(1, "/halt", "42")])
    written: list[tuple[str, int]] = []

    def writer(reason: str, ts_ns: int) -> None:
        written.append((reason, ts_ns))

    stop = asyncio.Event()
    task = asyncio.create_task(
        poll_telegram_for_halt(
            telegram=tg,
            chat_id="42",
            halt_writer=writer,
            clock_ns=lambda: 99,
            stop=stop,
            sleep=asyncio.sleep,
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.005)
        if written:
            break
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(written) == 1
    reason, ts_ns = written[0]
    assert ts_ns == 99
    assert "operator" in reason


async def test_halt_from_wrong_chat_ignored() -> None:
    tg = FakeTelegramClient()
    tg.updates_script.append([_make_update(1, "/halt", "9999")])  # wrong chat
    written: list[tuple[str, int]] = []

    def writer(reason: str, ts_ns: int) -> None:
        written.append((reason, ts_ns))

    stop = asyncio.Event()
    task = asyncio.create_task(
        poll_telegram_for_halt(
            telegram=tg,
            chat_id="42",
            halt_writer=writer,
            clock_ns=lambda: 0,
            stop=stop,
            sleep=asyncio.sleep,
        )
    )
    # Give the loop time to process the (bogus) update.
    for _ in range(20):
        await asyncio.sleep(0.005)
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert written == []


async def test_halt_only_for_exact_command() -> None:
    tg = FakeTelegramClient()
    tg.updates_script.append([_make_update(1, "halt please", "42")])
    written: list[tuple[str, int]] = []

    def writer(reason: str, ts_ns: int) -> None:
        written.append((reason, ts_ns))

    stop = asyncio.Event()
    task = asyncio.create_task(
        poll_telegram_for_halt(
            telegram=tg,
            chat_id="42",
            halt_writer=writer,
            clock_ns=lambda: 0,
            stop=stop,
            sleep=asyncio.sleep,
        )
    )
    for _ in range(20):
        await asyncio.sleep(0.005)
    stop.set()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert written == []

"""Alerter service — drain alert queue + long-poll Telegram for /halt.

design/alerter.md §5: two concurrent asyncio tasks share one process.
`_drain_alert_queue` BRPOPs the producer queue, formats each alert, and posts
to Telegram. On Telegram 5xx the payload is pushed to the DLQ list (capped
FIFO). A 1-msg/sec sliding token bucket throttles the chat to stay under
Telegram's per-chat rate limit. `_poll_telegram_for_halt` long-polls
getUpdates; on `/halt` from `TELEGRAM_CHAT_ID` it writes the sentinel and
acknowledges in-chat. Other chats are silently ignored. Both loops are
cancellable via a shared asyncio.Event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

import httpx

from polymarket_bot._live.alerter.formatter import format_alert
from polymarket_bot._live.alerter.protocols import (
    ClockNs,
    HaltWriter,
    RedisQueue,
    TelegramClient,
)

LOG = logging.getLogger("polymarket_bot._live.alerter.service")

QUEUE_BRPOP_TIMEOUT_S = 30.0
RATE_LIMIT_INTERVAL_S = 1.0
HALT_COMMAND = "/halt"


async def _send_with_dlq(
    telegram: TelegramClient,
    redis_q: RedisQueue,
    chat_id: str,
    text: str,
    raw_payload: bytes,
) -> bool:
    """Try to post one message; on 5xx push raw bytes onto DLQ. Returns sent?"""
    try:
        await telegram.send_message(text, chat_id=chat_id)
        return True
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if 500 <= status < 600:
            LOG.warning("telegram 5xx (%s); pushing to DLQ", status)
            await redis_q.lpush_dlq(raw_payload)
            return False
        LOG.warning("telegram non-5xx (%s); dropping payload", status)
        return False
    except httpx.HTTPError as exc:
        LOG.warning("telegram transport error: %s; pushing to DLQ", exc)
        await redis_q.lpush_dlq(raw_payload)
        return False


async def drain_alert_queue(
    *,
    redis_q: RedisQueue,
    telegram: TelegramClient,
    chat_id: str,
    stop: asyncio.Event,
    sleep: Any = asyncio.sleep,
) -> None:
    """Long-running loop: BRPOP → format → send (with rate limit + DLQ)."""
    last_send_at: float = 0.0
    loop = asyncio.get_event_loop()
    while not stop.is_set():
        try:
            raw = await redis_q.brpop(timeout=QUEUE_BRPOP_TIMEOUT_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("redis brpop unexpected error; sleeping 1s")
            await sleep(1.0)
            continue
        if raw is None:
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOG.warning("alerter: dropping malformed payload")
            continue
        if not isinstance(payload, dict):
            continue
        text = format_alert(payload)
        if text is None:
            continue
        # Rate-limit: at most one Telegram message per second to the operator chat.
        now = loop.time()
        wait = RATE_LIMIT_INTERVAL_S - (now - last_send_at)
        if wait > 0:
            await sleep(wait)
        await _send_with_dlq(telegram, redis_q, chat_id, text, raw)
        last_send_at = loop.time()


def _extract_halt_command(updates: list[dict[str, Any]], chat_id: str) -> int | None:
    """Return the highest seen update_id from a /halt by chat_id, or None."""
    matched_id: int | None = None
    max_id: int | None = None
    for u in updates:
        uid = u.get("update_id")
        if isinstance(uid, int):
            max_id = uid if max_id is None else max(max_id, uid)
        msg = u.get("message")
        if not isinstance(msg, dict):
            continue
        text = msg.get("text")
        chat = msg.get("chat") or {}
        from_chat_id = str(chat.get("id")) if isinstance(chat, dict) else None
        if (
            isinstance(text, str)
            and text.strip().lower() == HALT_COMMAND
            and from_chat_id == chat_id
            and isinstance(uid, int)
        ):
            matched_id = uid if matched_id is None else max(matched_id, uid)
    if matched_id is not None:
        return matched_id
    return max_id


async def poll_telegram_for_halt(
    *,
    telegram: TelegramClient,
    chat_id: str,
    halt_writer: HaltWriter,
    clock_ns: ClockNs,
    stop: asyncio.Event,
    sleep: Any = asyncio.sleep,
) -> None:
    """Long-poll getUpdates; on /halt from chat_id, write sentinel + ack."""
    next_offset: int | None = None
    while not stop.is_set():
        try:
            updates = await telegram.get_updates(offset=next_offset, timeout=25)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("telegram get_updates failed; sleeping 5s")
            await sleep(5.0)
            continue
        if not updates:
            continue
        last_id = _extract_halt_command(updates, chat_id)
        # Advance offset past every update we've seen, even ones we ignore.
        max_seen = max(
            (u["update_id"] for u in updates if isinstance(u.get("update_id"), int)), default=None
        )
        if max_seen is not None:
            next_offset = max_seen + 1
        # Decide if we saw a /halt for our chat by re-walking updates.
        for u in updates:
            msg = u.get("message")
            if not isinstance(msg, dict):
                continue
            text = msg.get("text")
            chat = msg.get("chat") or {}
            from_chat_id = str(chat.get("id")) if isinstance(chat, dict) else None
            if (
                isinstance(text, str)
                and text.strip().lower() == HALT_COMMAND
                and from_chat_id == chat_id
            ):
                LOG.warning("/halt received from operator chat; writing sentinel")
                halt_writer("operator request via telegram", clock_ns())
                try:
                    await telegram.send_message(
                        "halt sentinel set; bot will exit on next 1s tick",
                        chat_id=chat_id,
                    )
                except Exception:
                    LOG.exception("telegram ack failed; sentinel still written")
                # Sentinel persists; bot will exit. Do not return — keep
                # polling so the operator can /halt again after a manual
                # restart (sentinel removed) without restarting the alerter.
        _ = last_id


def _register_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows / restricted environments — tests rarely hit this branch.
            pass


async def main(
    *,
    redis_q: RedisQueue,
    telegram: TelegramClient,
    chat_id: str,
    halt_writer: HaltWriter,
    clock_ns: ClockNs,
) -> int:
    """Run both loops until SIGTERM/SIGINT."""
    stop = asyncio.Event()
    _register_signal_handlers(stop)
    drain_task = asyncio.create_task(
        drain_alert_queue(
            redis_q=redis_q,
            telegram=telegram,
            chat_id=chat_id,
            stop=stop,
        ),
        name="alerter-drain",
    )
    poll_task = asyncio.create_task(
        poll_telegram_for_halt(
            telegram=telegram,
            chat_id=chat_id,
            halt_writer=halt_writer,
            clock_ns=clock_ns,
            stop=stop,
        ),
        name="alerter-halt-poll",
    )
    await stop.wait()
    drain_task.cancel()
    poll_task.cancel()
    await asyncio.gather(drain_task, poll_task, return_exceptions=True)
    await redis_q.aclose()
    await telegram.aclose()
    return 0

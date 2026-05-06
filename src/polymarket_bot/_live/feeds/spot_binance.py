"""Binance BTC/USDT trade feed — `wss://stream.binance.com:9443/ws/btcusdt@trade`.

Anonymous read-only WS stream of every BTC/USDT trade. Implements the Feed
protocol from polymarket_bot.feeds.protocols. Reconnect policy and Record
schema are pinned in design/data_plane.md §4 and §6. Stochastic inputs
(connect_fn, clock_ns, sleep) are injected per anti-vibe rule #10 so tests
exercise the full reconnect/parse path with a FakeWSClient and zero network.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator

import websockets

from polymarket_bot.feeds.protocols import (
    ClockNs,
    Feed,
    Health,
    Record,
    SleepFn,
    WSConnectFn,
)

DEFAULT_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"
ENV_URL = "BINANCE_WS_URL"
SOURCE = "binance"
KIND = "trade"
MAX_BACKOFF_S = 60.0


class BinanceTradeFeed:
    """Yields one Record per Binance BTC/USDT trade, indefinitely until stop().

    Trade payload shape (Binance docs): {"e":"trade","E":<ms>,"s":"BTCUSDT",
    "t":<id>,"p":"<price>","q":"<qty>","T":<trade_ms>,"m":<bool>,"M":<bool>}.
    We use T (trade time, ms) as event-time, falling back to E (event time)
    or recv-time. The full raw text is archived in payload_json with no
    transformation — Phase 3 mines fields from there.
    """

    name: str = SOURCE

    def __init__(
        self,
        *,
        url: str | None = None,
        connect_fn: WSConnectFn | None = None,
        clock_ns: ClockNs = time.time_ns,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._url: str = url if url is not None else os.environ.get(ENV_URL, DEFAULT_URL)
        self._connect: WSConnectFn = connect_fn if connect_fn is not None else websockets.connect  # type: ignore[assignment]
        self._clock_ns: ClockNs = clock_ns
        self._sleep: SleepFn = sleep
        self._stop = asyncio.Event()
        self._health_state: Health = {
            "name": SOURCE,
            "last_seen_ns": 0,
            "msgs_seen": 0,
            "reconnects": 0,
            "last_error": "",
        }

    @property
    def health(self) -> Health:
        return Health(
            name=self._health_state["name"],
            last_seen_ns=self._health_state["last_seen_ns"],
            msgs_seen=self._health_state["msgs_seen"],
            reconnects=self._health_state["reconnects"],
            last_error=self._health_state["last_error"],
        )

    def stop(self) -> None:
        self._stop.set()

    def stream(self) -> AsyncIterator[Record]:
        return self._stream_impl()

    async def _stream_impl(self) -> AsyncIterator[Record]:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with self._connect(self._url) as ws:
                    attempt = 0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        recv_ns = self._clock_ns()
                        self._health_state["last_seen_ns"] = recv_ns
                        self._health_state["msgs_seen"] += 1
                        ts_ns = _extract_event_ts_ns(msg, recv_ns)
                        yield Record(
                            ts_utc_ns=ts_ns,
                            received_at_ns=recv_ns,
                            source=SOURCE,
                            kind=KIND,
                            payload_json=msg,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._health_state["reconnects"] += 1
                self._health_state["last_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            if self._stop.is_set():
                return
            attempt += 1
            delay = min(2.0 ** (attempt - 1), MAX_BACKOFF_S)
            await self._sleep(delay)


def _extract_event_ts_ns(raw_msg: str, fallback_ns: int) -> int:
    """Pull Binance trade time T (or E) in ms, return ns, fall back on parse fail."""
    try:
        data = json.loads(raw_msg)
    except (json.JSONDecodeError, TypeError):
        return fallback_ns
    if not isinstance(data, dict):
        return fallback_ns
    ts_ms = data.get("T") or data.get("E")
    if not isinstance(ts_ms, int):
        return fallback_ns
    return ts_ms * 1_000_000


_: type[Feed] = BinanceTradeFeed

"""Coinbase BTC-USD matches feed — `wss://ws-feed.exchange.coinbase.com`.

Anonymous read-only WS feed. Sends a `{"type":"subscribe", "channels":[...]}`
message after connect. Implements the Feed protocol from
polymarket_bot.feeds.protocols. Reconnect policy and Record schema are pinned
in design/data_plane.md §4 and §6. Stochastic inputs (connect_fn, clock_ns,
sleep) are injected so tests exercise the full subscribe/parse/reconnect path
with a FakeWSClient and zero network.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import websockets

from polymarket_bot.feeds.protocols import (
    ClockNs,
    Feed,
    Health,
    Record,
    SleepFn,
    WSConnectFn,
)

DEFAULT_URL = "wss://ws-feed.exchange.coinbase.com"
ENV_URL = "COINBASE_WS_URL"
SOURCE = "coinbase"
KIND = "match"
MAX_BACKOFF_S = 60.0

SUBSCRIBE_PAYLOAD = json.dumps(
    {"type": "subscribe", "channels": [{"name": "matches", "product_ids": ["BTC-USD"]}]},
    separators=(",", ":"),
)


class CoinbaseMatchFeed:
    """Yields one Record per Coinbase BTC-USD match. Indefinite until stop().

    Match payload shape (Coinbase WS): {"type":"match","trade_id":...,
    "maker_order_id":...,"taker_order_id":...,"side":"buy",...,"size":"...",
    "price":"...","product_id":"BTC-USD","sequence":...,"time":"<ISO-8601>"}.
    We parse the time field (microsecond precision, trailing Z) to ns;
    other type values ("subscriptions", "heartbeat") are skipped silently
    but counted as msgs_seen so the lag metric stays accurate.
    """

    name: str = SOURCE

    def __init__(
        self,
        *,
        url: str | None = None,
        connect_fn: WSConnectFn | None = None,
        clock_ns: ClockNs = time.time_ns,
        sleep: SleepFn = asyncio.sleep,
        subscribe_payload: str = SUBSCRIBE_PAYLOAD,
    ) -> None:
        self._url: str = url if url is not None else os.environ.get(ENV_URL, DEFAULT_URL)
        self._connect: WSConnectFn = connect_fn if connect_fn is not None else websockets.connect  # type: ignore[assignment]
        self._clock_ns: ClockNs = clock_ns
        self._sleep: SleepFn = sleep
        self._subscribe_payload = subscribe_payload
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
                    await ws.send(self._subscribe_payload)
                    attempt = 0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        recv_ns = self._clock_ns()
                        self._health_state["last_seen_ns"] = recv_ns
                        self._health_state["msgs_seen"] += 1
                        kind = _classify(msg)
                        if kind != KIND:
                            continue
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


def _classify(raw_msg: str) -> str:
    """Return the Coinbase 'type' field, or empty string on parse fail."""
    try:
        data = json.loads(raw_msg)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    t = data.get("type")
    return t if isinstance(t, str) else ""


def _extract_event_ts_ns(raw_msg: str, fallback_ns: int) -> int:
    """Parse Coinbase 'time' (ISO-8601 UTC, microsecond precision) → ns. Fallback safely."""
    try:
        data = json.loads(raw_msg)
    except (json.JSONDecodeError, TypeError):
        return fallback_ns
    if not isinstance(data, dict):
        return fallback_ns
    t = data.get("time")
    if not isinstance(t, str) or not t:
        return fallback_ns
    iso = t[:-1] + "+00:00" if t.endswith("Z") else t
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return fallback_ns
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    seconds = dt.timestamp()
    return int(seconds * 1_000_000_000)


_: type[Feed] = CoinbaseMatchFeed

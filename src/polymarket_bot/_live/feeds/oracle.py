"""Chainlink BTC/USD oracle watcher (Polygon, AnswerUpdated events).

Subscribes via raw JSON-RPC over Polygon WSS to AnswerUpdated logs from the
underlying aggregator behind the public proxy
0xc907E116054Ad103354f2D350FD2514433D57F6f. The proxy address is the stable,
documented entry point, but events fire from its current implementation, so
we resolve underlying = proxy.aggregator() at every connect cycle. Event
topic is computed in code as keccak256("AnswerUpdated(int256,uint256,uint256)")
so the constant cannot drift from the signature. Stochastic inputs injected
per anti-vibe rule #10. Pre-flight evidence in design/data_plane.md §16.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import websockets
from eth_utils import keccak  # type: ignore[attr-defined]

from polymarket_bot.feeds.protocols import (
    ClockNs,
    Feed,
    Health,
    Record,
    SleepFn,
    WSConnectFn,
)

DEFAULT_PROXY = "0xc907E116054Ad103354f2D350FD2514433D57F6f"
ENV_PROXY = "CHAINLINK_BTC_USD_AGGREGATOR"
ENV_RPC = "POLYGON_RPC_URL"
SOURCE = "oracle"
KIND = "AnswerUpdated"
MAX_BACKOFF_S = 60.0

EVENT_SIGNATURE = "AnswerUpdated(int256,uint256,uint256)"
EVENT_TOPIC = "0x" + keccak(text=EVENT_SIGNATURE).hex()

AGGREGATOR_FN_SIGNATURE = "aggregator()"
AGGREGATOR_FN_SELECTOR = "0x" + keccak(text=AGGREGATOR_FN_SIGNATURE)[:4].hex()


class OracleFeed:
    """Yields one Record per Chainlink AnswerUpdated event. Indefinite until stop().

    Each connection cycle: resolves the proxy's current underlying via
    eth_call(aggregator()); subscribes to logs filtered by underlying address
    and AnswerUpdated topic; pumps subscription notifications into Records.
    Decoded ts_utc_ns is taken from the event's updatedAt field (uint256
    seconds since epoch); on decode failure we fall back to recv-clock so a
    bad payload never silently corrupts the timestamp axis.
    """

    name: str = SOURCE

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        proxy_address: str | None = None,
        connect_fn: WSConnectFn | None = None,
        clock_ns: ClockNs = time.time_ns,
        sleep: SleepFn = asyncio.sleep,
        rpc_timeout_s: float = 10.0,
    ) -> None:
        self._rpc_url: str = rpc_url if rpc_url is not None else os.environ[ENV_RPC]
        self._proxy: str = (
            proxy_address if proxy_address is not None else os.environ.get(ENV_PROXY, DEFAULT_PROXY)
        ).lower()
        self._connect: WSConnectFn = connect_fn if connect_fn is not None else websockets.connect  # type: ignore[assignment]
        self._clock_ns: ClockNs = clock_ns
        self._sleep: SleepFn = sleep
        self._rpc_timeout_s = rpc_timeout_s
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
                async with self._connect(self._rpc_url) as ws:
                    underlying = await self._resolve_underlying(ws)
                    sub_id = await self._subscribe_logs(ws, underlying)
                    attempt = 0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        log = _extract_subscription_log(msg, sub_id)
                        if log is None:
                            continue
                        recv_ns = self._clock_ns()
                        self._health_state["last_seen_ns"] = recv_ns
                        self._health_state["msgs_seen"] += 1
                        ts_ns = _extract_event_ts_ns(log, recv_ns)
                        yield Record(
                            ts_utc_ns=ts_ns,
                            received_at_ns=recv_ns,
                            source=SOURCE,
                            kind=KIND,
                            payload_json=json.dumps(log, separators=(",", ":")),
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

    async def _resolve_underlying(self, ws: Any) -> str:
        """eth_call proxy.aggregator() → underlying aggregator address (lower-cased)."""
        request_id = 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "eth_call",
            "params": [{"to": self._proxy, "data": AGGREGATOR_FN_SELECTOR}, "latest"],
        }
        await ws.send(json.dumps(request, separators=(",", ":")))
        async with asyncio.timeout(self._rpc_timeout_s):
            async for raw in ws:
                msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                try:
                    resp = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if isinstance(resp, dict) and resp.get("id") == request_id:
                    if "error" in resp:
                        raise RuntimeError(f"eth_call(aggregator) error: {resp['error']}")
                    result = resp.get("result")
                    if not isinstance(result, str) or len(result) < 2 + 64:
                        raise RuntimeError(f"unexpected aggregator() result: {result!r}")
                    return ("0x" + result[-40:]).lower()
        raise RuntimeError("aggregator() resolution timed out")

    async def _subscribe_logs(self, ws: Any, underlying: str) -> str:
        """eth_subscribe(logs, {address: underlying, topics: [EVENT_TOPIC]}) → subscription id."""
        request_id = 2
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "eth_subscribe",
            "params": ["logs", {"address": underlying, "topics": [EVENT_TOPIC]}],
        }
        await ws.send(json.dumps(request, separators=(",", ":")))
        async with asyncio.timeout(self._rpc_timeout_s):
            async for raw in ws:
                msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                try:
                    resp = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if isinstance(resp, dict) and resp.get("id") == request_id:
                    if "error" in resp:
                        raise RuntimeError(f"eth_subscribe error: {resp['error']}")
                    sub_id = resp.get("result")
                    if not isinstance(sub_id, str):
                        raise RuntimeError(f"unexpected eth_subscribe result: {sub_id!r}")
                    return sub_id
        raise RuntimeError("eth_subscribe timed out")


def _extract_subscription_log(raw_msg: str, expected_sub_id: str) -> dict[str, Any] | None:
    """Parse a JSON-RPC message; return the log dict if it's our subscription, else None."""
    try:
        msg = json.loads(raw_msg)
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict):
        return None
    if msg.get("method") != "eth_subscription":
        return None
    params = msg.get("params")
    if not isinstance(params, dict):
        return None
    if params.get("subscription") != expected_sub_id:
        return None
    result = params.get("result")
    if not isinstance(result, dict):
        return None
    return result


def _extract_event_ts_ns(log: dict[str, Any], fallback_ns: int) -> int:
    """Decode AnswerUpdated.updatedAt (uint256 seconds) → ns, or recv-time fallback.

    The event signature has 3 args (int256 current, uint256 roundId, uint256 updatedAt).
    Chainlink declares all three as `indexed` on its modern aggregators and as
    `current/roundId indexed, updatedAt unindexed` on older ones. We support both:
    if data has ≥32 bytes, the first 32 bytes are updatedAt; else if there are 4
    topics, topics[3] is updatedAt. Otherwise fallback.
    """
    data_hex = log.get("data")
    if isinstance(data_hex, str) and data_hex.startswith("0x") and len(data_hex) >= 2 + 64:
        try:
            updated_at = int(data_hex[2 : 2 + 64], 16)
            if 1_000_000_000 <= updated_at <= 4_102_444_800:  # sane unix-seconds range
                return updated_at * 1_000_000_000
        except ValueError:
            pass
    topics = log.get("topics")
    if isinstance(topics, list) and len(topics) >= 4 and isinstance(topics[3], str):
        try:
            updated_at = int(topics[3][2:], 16)
            if 1_000_000_000 <= updated_at <= 4_102_444_800:
                return updated_at * 1_000_000_000
        except ValueError:
            pass
    return fallback_ns


_: type[Feed] = OracleFeed

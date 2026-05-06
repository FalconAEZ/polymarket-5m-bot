"""Polymarket 5m BTC up/down WS feed — book + trade + price-change archive.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market and
subscribes by asset_id (the two CTF token IDs of the active 5m BTC up/down
market). The active window is computed deterministically from the wall
clock per MASTERPLAN.md line 27. Token IDs are resolved through the public
Gamma API (no auth) at every window rotation. PINGs at 9s intervals satisfy
the 10s heartbeat expected by the server. Stochastic inputs (gamma_fetch_fn,
connect_fn, clock_ns, sleep) injected per anti-vibe rule #10.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import websockets

from polymarket_bot.feeds.protocols import (
    ClockNs,
    Feed,
    Health,
    Record,
    SleepFn,
    WSConnectFn,
)
from polymarket_bot.resolver import WINDOW_SECONDS, active_slug, active_window_ts

DEFAULT_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
DEFAULT_GAMMA_BASE = "https://gamma-api.polymarket.com"
ENV_WS = "POLYMARKET_WS_URL"
ENV_GAMMA = "GAMMA_API_BASE"
SOURCE = "polymarket"
MAX_BACKOFF_S = 60.0
PING_INTERVAL_S = 9.0
HTTP_TIMEOUT_S = 10.0

GammaFetchFn = Callable[[str], Awaitable[dict[str, Any] | None]]
"""Async function: takes an event slug, returns the Gamma event dict or None.

None signals the slug does not (yet) have a market on Gamma. The feed
treats this as a transient miss; it is logged and retried at the next
window boundary.
"""


def extract_token_ids(event: dict[str, Any]) -> list[str]:
    """Pull the two ERC1155 token IDs (Up + Down outcomes) from a Gamma event.

    The Gamma response stores token IDs as a JSON-encoded string under
    markets[0].clobTokenIds; outcomes is also stringified JSON. Returns []
    if the field is missing or malformed so the feed can surface a clean
    "gamma miss" rather than crashing.
    """
    markets = event.get("markets")
    if not isinstance(markets, list) or not markets:
        return []
    raw = markets[0].get("clobTokenIds") if isinstance(markets[0], dict) else None
    if not isinstance(raw, str):
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [tid for tid in decoded if isinstance(tid, str)]


class GammaClient:
    """Default GammaFetchFn implementation backed by httpx.AsyncClient."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = HTTP_TIMEOUT_S,
    ) -> None:
        self._base_url = base_url or os.environ.get(ENV_GAMMA, DEFAULT_GAMMA_BASE)
        self._client = client
        self._timeout_s = timeout_s

    async def fetch_event(self, slug: str) -> dict[str, Any] | None:
        url = f"{self._base_url.rstrip('/')}/events"
        params = {"slug": slug}
        headers = {"User-Agent": "polymarket-5m-bot/0.1"}
        async with httpx.AsyncClient(timeout=self._timeout_s, headers=headers) as client:
            resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"gamma /events {slug} returned {resp.status_code}")
        data = resp.json()
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        return first if isinstance(first, dict) else None


class PolymarketFeed:
    """Yields Records from Polymarket's market WS for the active 5m window.

    On each connection cycle: (1) resolve token IDs for the current window
    via Gamma; (2) send the subscribe message; (3) drain WS messages,
    skipping PONG and emitting a Record per real event; (4) a background
    task sends PING every 9s and re-subscribes when a new 5m window opens.
    Window boundaries are computed from clock_ns, not from server messages.
    """

    name: str = SOURCE

    def __init__(
        self,
        *,
        ws_url: str | None = None,
        gamma_fetch_fn: GammaFetchFn | None = None,
        connect_fn: WSConnectFn | None = None,
        clock_ns: ClockNs = time.time_ns,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._ws_url: str = ws_url if ws_url is not None else os.environ.get(ENV_WS, DEFAULT_WS_URL)
        if gamma_fetch_fn is not None:
            self._gamma = gamma_fetch_fn
        else:
            client = GammaClient()
            self._gamma = client.fetch_event
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
                async with self._connect(self._ws_url) as ws:
                    now_s = self._clock_ns() // 1_000_000_000
                    current_window = active_window_ts(now_s)
                    tokens = await self._fetch_tokens(current_window)
                    if not tokens:
                        self._health_state["last_error"] = (
                            f"gamma-miss: slug={active_slug(current_window)}"
                        )
                        await self._sleep_to_next_boundary()
                        continue
                    await ws.send(_build_subscribe(tokens, initial=True))
                    bg_stop = asyncio.Event()
                    bg = asyncio.create_task(
                        self._background(ws, current_window, bg_stop), name="poly-bg"
                    )
                    attempt = 0
                    try:
                        async for raw in ws:
                            if self._stop.is_set():
                                break
                            msg = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                            if msg.strip() in ("PONG", "pong"):
                                continue
                            recv_ns = self._clock_ns()
                            self._health_state["last_seen_ns"] = recv_ns
                            self._health_state["msgs_seen"] += 1
                            for kind, payload_json, evt_ts_ns in _parse_records(msg):
                                yield Record(
                                    ts_utc_ns=evt_ts_ns if evt_ts_ns > 0 else recv_ns,
                                    received_at_ns=recv_ns,
                                    source=SOURCE,
                                    kind=kind,
                                    payload_json=payload_json,
                                )
                    finally:
                        bg_stop.set()
                        bg.cancel()
                        await asyncio.gather(bg, return_exceptions=True)
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

    async def _fetch_tokens(self, window_ts: int) -> list[str]:
        slug = active_slug(window_ts)
        try:
            event = await self._gamma(slug)
        except Exception as e:
            self._health_state["last_error"] = f"gamma-err: {type(e).__name__}: {str(e)[:200]}"
            return []
        if not isinstance(event, dict):
            return []
        return extract_token_ids(event)

    async def _sleep_to_next_boundary(self) -> None:
        now_s = self._clock_ns() // 1_000_000_000
        seconds_to_next = WINDOW_SECONDS - (now_s % WINDOW_SECONDS)
        await self._sleep(float(max(seconds_to_next, 1)))

    async def _background(
        self,
        ws: Any,
        starting_window_ts: int,
        bg_stop: asyncio.Event,
    ) -> None:
        last_ping_s = 0.0
        next_rotate_s = float(starting_window_ts + WINDOW_SECONDS)
        while not bg_stop.is_set() and not self._stop.is_set():
            await self._sleep(1.0)
            if bg_stop.is_set() or self._stop.is_set():
                return
            now_s = self._clock_ns() / 1_000_000_000
            if now_s - last_ping_s >= PING_INTERVAL_S:
                try:
                    await ws.send("PING")
                except Exception:
                    return
                last_ping_s = now_s
            if now_s >= next_rotate_s:
                new_tokens = await self._fetch_tokens(int(next_rotate_s))
                if new_tokens:
                    try:
                        await ws.send(_build_subscribe(new_tokens, initial=False))
                    except Exception:
                        return
                next_rotate_s += WINDOW_SECONDS


def _build_subscribe(tokens: list[str], *, initial: bool) -> str:
    """Build the subscribe message. initial=True is the first connect-time
    subscribe; initial=False is the dynamic (post-connect) operation that
    adds tokens to an already-open subscription per the WS docs."""
    payload: dict[str, Any] = {
        "type": "market",
        "assets_ids": tokens,
        "custom_feature_enabled": True,
    }
    if not initial:
        payload["operation"] = "subscribe"
    return json.dumps(payload, separators=(",", ":"))


_VALID_KINDS = frozenset(
    {"book", "price_change", "last_trade_price", "tick_size_change", "best_bid_ask"}
)


def _parse_records(raw_msg: str) -> list[tuple[str, str, int]]:
    """Parse a Polymarket WS message into (kind, payload_json, event_ts_ns) tuples.

    Polymarket wraps messages in JSON arrays — one element per asset_id when
    multiple assets are subscribed. The initial subscribe response, for
    example, is `[{...book for token_a...}, {...book for token_b...}]`. We
    flatten arrays here so each archived Record corresponds to one logical
    event for one asset_id, and payload_json is just that element (not the
    enclosing array). Single-dict messages are also accepted for forward
    compatibility. Returns an empty list for unknown event_types or
    unparseable messages so the caller never silently archives noise.
    """
    try:
        data = json.loads(raw_msg)
    except json.JSONDecodeError:
        return []
    items: list[object] = data if isinstance(data, list) else [data]
    out: list[tuple[str, str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("event_type")
        if not isinstance(kind, str) or kind not in _VALID_KINDS:
            continue
        evt_ns = _extract_event_ts_ns_from_dict(item)
        payload = json.dumps(item, separators=(",", ":"))
        out.append((kind, payload, evt_ns))
    return out


def _extract_event_ts_ns_from_dict(item: dict[str, object]) -> int:
    """Polymarket's `timestamp` is a digit string of unix-millis. Returns 0 on miss."""
    ts = item.get("timestamp")
    if isinstance(ts, str) and ts.isdigit():
        return int(ts) * 1_000_000
    if isinstance(ts, int):
        return ts * 1_000_000
    return 0


_: type[Feed] = PolymarketFeed

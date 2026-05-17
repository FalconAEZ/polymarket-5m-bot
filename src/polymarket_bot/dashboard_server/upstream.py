"""Live upstream WebSocket subscribers — Binance kline + depth20.

Maintains an in-memory UpstreamCache populated by background asyncio
tasks. The dashboard server's snapshot() reads the cache; the WS pump
relays cache changes to the React frontend off-cadence (immediate push
on update, not on the 1Hz heartbeat).

These subscriptions are SEPARATE from the bot's own _live/feeds/* —
the dashboard is read-only and never interferes with bot WS state.
Per design/dashboard-v3.md §3.6.

Polymarket CTF book is fetched via REST polling (the existing
dashboard.polymarket_orderbook reader, called every 2s). WS for
Polymarket is deferred to v3.1.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

import httpx
import websockets
import websockets.exceptions

from polymarket_bot.dashboard.polymarket_orderbook import fetch_ctf_orderbook
from polymarket_bot.dashboard_server.state import UpstreamCache

log = logging.getLogger("dashboard_server.upstream")

BINANCE_STREAM_URL = (
    "wss://stream.binance.com:9443/stream?streams=btcusdt@kline_5m/btcusdt@depth20@100ms"
)
RECONNECT_BASE_S: float = 1.0
RECONNECT_MAX_S: float = 30.0
CTF_POLL_INTERVAL_S: float = 2.0
KLINE_HISTORY_FETCH_LIMIT: int = 60
CANDLES_KEPT: int = 90


async def fetch_initial_klines(client: httpx.AsyncClient) -> list[dict[str, float]]:
    """Bootstraps the chart with the last KLINE_HISTORY_FETCH_LIMIT 5m
    candles via REST so the chart isn't empty on first paint."""
    try:
        resp = await client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "5m", "limit": KLINE_HISTORY_FETCH_LIMIT},
            timeout=10.0,
        )
        resp.raise_for_status()
        raw = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    out: list[dict[str, float]] = []
    for k in raw:
        try:
            out.append(
                {
                    "ts": float(k[0]) / 1000,
                    "o": float(k[1]),
                    "h": float(k[2]),
                    "l": float(k[3]),
                    "c": float(k[4]),
                    "v": float(k[5]),
                }
            )
        except (IndexError, ValueError, TypeError):
            continue
    return out


def _apply_kline(cache: UpstreamCache, k: dict[str, Any]) -> None:
    """Apply a single Binance kline message to the cache. The kline
    payload arrives every ~2s while a candle is forming and once when
    it closes."""
    try:
        candle = {
            "ts": float(k["t"]) / 1000,
            "o": float(k["o"]),
            "h": float(k["h"]),
            "l": float(k["l"]),
            "c": float(k["c"]),
            "v": float(k["v"]),
        }
    except (KeyError, ValueError, TypeError):
        return
    if cache.btc_candles and cache.btc_candles[-1]["ts"] == candle["ts"]:
        cache.btc_candles[-1] = candle
    else:
        cache.btc_candles.append(candle)
        if len(cache.btc_candles) > CANDLES_KEPT:
            del cache.btc_candles[0 : len(cache.btc_candles) - CANDLES_KEPT]
    cache.btc_last_price = candle["c"]
    if len(cache.btc_candles) >= 2:
        first = cache.btc_candles[0]["c"]
        if first > 0:
            cache.btc_change_pct = (candle["c"] - first) / first * 100.0


def _apply_depth(cache: UpstreamCache, d: dict[str, Any]) -> None:
    """Apply a depth20@100ms snapshot from Binance."""
    try:
        asks = [(float(p), float(s)) for p, s in d.get("asks", []) if float(s) > 0]
        bids = [(float(p), float(s)) for p, s in d.get("bids", []) if float(s) > 0]
    except (ValueError, TypeError):
        return
    asks.sort(key=lambda r: r[0])
    bids.sort(key=lambda r: r[0], reverse=True)
    cache.spot_book_asks = asks[:10]
    cache.spot_book_bids = bids[:10]
    if asks and bids:
        cache.spot_book_mid = (asks[0][0] + bids[0][0]) / 2.0
    cache.spot_book_ts_ns = time.time_ns()


async def _binance_loop(cache: UpstreamCache, *, on_update: asyncio.Event | None = None) -> None:
    """Long-running Binance WS loop. Writes to cache; sets on_update
    after each message so the WS pump can wake immediately."""
    backoff = RECONNECT_BASE_S
    async with httpx.AsyncClient() as client:
        cache.btc_candles = await fetch_initial_klines(client)
        if cache.btc_candles:
            cache.btc_last_price = cache.btc_candles[-1]["c"]
    while True:
        try:
            async with websockets.connect(BINANCE_STREAM_URL, ping_interval=20) as ws:
                log.info("binance ws connected")
                backoff = RECONNECT_BASE_S
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                    except (TypeError, ValueError):
                        continue
                    payload = data.get("data") or data
                    stream = data.get("stream", "")
                    if "kline" in stream:
                        kline = payload.get("k")
                        if isinstance(kline, dict):
                            _apply_kline(cache, kline)
                    elif "depth" in stream:
                        _apply_depth(cache, payload)
                    if on_update is not None:
                        on_update.set()
        except (
            TimeoutError,
            websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException,
            OSError,
        ) as exc:
            log.warning("binance ws disconnected: %s; backoff %.1fs", exc, backoff)
        except Exception as exc:  # never crash the loop
            log.exception("binance ws unexpected error: %s", exc)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, RECONNECT_MAX_S)


async def _ctf_loop(
    cache: UpstreamCache,
    *,
    state_dir_resolver: Any,
    on_update: asyncio.Event | None = None,
) -> None:
    """Polls Polymarket CTF orderbook every CTF_POLL_INTERVAL_S for the
    current 5m window's most-recent decision side."""
    while True:
        try:
            window_ts, side = state_dir_resolver()
            if window_ts is not None and side is not None:
                snap = await asyncio.to_thread(fetch_ctf_orderbook, window_ts, side, throttle_s=0.0)
                if snap is not None:
                    cache.ctf_window_ts = (
                        snap.market_slug.split("-")[-1].isdigit()
                        and int(snap.market_slug.split("-")[-1])
                    ) or window_ts
                    cache.ctf_side = side
                    cache.ctf_slug = snap.market_slug
                    cache.ctf_asks = [(r.price, r.size) for r in snap.rows_ask]
                    cache.ctf_bids = [(r.price, r.size) for r in snap.rows_bid]
                    cache.ctf_mid = snap.mid
                    cache.ctf_ts_ns = time.time_ns()
                    if on_update is not None:
                        on_update.set()
        except Exception as exc:  # never crash the loop
            log.exception("ctf poll error: %s", exc)
        await asyncio.sleep(CTF_POLL_INTERVAL_S)


def spawn_upstream_tasks(
    cache: UpstreamCache,
    *,
    state_dir_resolver: Any,
    on_update: asyncio.Event | None = None,
) -> list[asyncio.Task[None]]:
    """Start the upstream subscriber tasks. Caller is responsible for
    awaiting cancellation on shutdown."""
    tasks = [
        asyncio.create_task(_binance_loop(cache, on_update=on_update), name="binance"),
        asyncio.create_task(
            _ctf_loop(cache, state_dir_resolver=state_dir_resolver, on_update=on_update),
            name="ctf-poll",
        ),
    ]
    return tasks


async def cancel_upstream_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t

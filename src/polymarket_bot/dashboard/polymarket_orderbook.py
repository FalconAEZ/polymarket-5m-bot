"""Polymarket CTF orderbook fetcher for the v2 below-the-fold panel.

Resolves the current 5-minute window's UP/DOWN token IDs via Polymarket's
Gamma REST API, then polls the CLOB for L2 depth via py-clob-client. All
network errors degrade to None — the panel renders 'feed offline' rather
than crashing the dashboard. Module-level throttle (default 2s) keeps
the per-second Streamlit autorefresh from hammering the API. Per
design/dashboard-v2.md §7.5.

importlinter contract 3 forbids dashboard from importing _live, so the
existing src/polymarket_bot/_live/feeds/polymarket.py client cannot be
reused here; this module instantiates py-clob-client and httpx
directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"

DEFAULT_TIMEOUT_S: float = 4.0
MAX_LEVELS: int = 10


@dataclass(frozen=True, slots=True)
class OrderbookRow:
    price: float
    size: float
    cumulative_size: float


@dataclass(frozen=True, slots=True)
class CTFBookSnapshot:
    market_slug: str
    up_token_id: str | None
    down_token_id: str | None
    side: Literal["UP", "DOWN"]
    rows_ask: tuple[OrderbookRow, ...]
    rows_bid: tuple[OrderbookRow, ...]
    mid: float | None
    asof: datetime
    rtt_ms: float


_TOKEN_CACHE: dict[int, tuple[str | None, str | None, float]] = {}
_BOOK_CACHE: dict[tuple[int, str], tuple[CTFBookSnapshot, float]] = {}
_TOKEN_TTL_S: float = 60.0  # token IDs don't change for the life of a market


def _resolve_token_ids(window_ts: int, slug_prefix: str) -> tuple[str | None, str | None]:
    cached = _TOKEN_CACHE.get(window_ts)
    if cached and (time.monotonic() - cached[2]) < _TOKEN_TTL_S:
        return cached[0], cached[1]
    slug = f"{slug_prefix}-{window_ts}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.get(f"{GAMMA_URL}/markets", params={"slug": slug})
        resp.raise_for_status()
        data: list[dict[str, Any]] = resp.json()
    except (httpx.HTTPError, ValueError):
        return None, None
    if not data:
        _TOKEN_CACHE[window_ts] = (None, None, time.monotonic())
        return None, None
    market = data[0]
    tokens_raw = market.get("clobTokenIds")
    if isinstance(tokens_raw, str):
        try:
            import json

            tokens = json.loads(tokens_raw)
        except ValueError:
            tokens = []
    elif isinstance(tokens_raw, list):
        tokens = tokens_raw
    else:
        tokens = []
    up_id = str(tokens[0]) if len(tokens) >= 1 else None
    down_id = str(tokens[1]) if len(tokens) >= 2 else None
    _TOKEN_CACHE[window_ts] = (up_id, down_id, time.monotonic())
    return up_id, down_id


def _fetch_book(token_id: str) -> tuple[list[OrderbookRow], list[OrderbookRow], float | None]:
    """Fetches L2 book for a token. Returns (asks, bids, mid). REST endpoint
    /book?token_id=... returns {"asks": [{"price","size"}, ...], "bids": ...}.
    """
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.get(f"{CLOB_URL}/book", params={"token_id": token_id})
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return [], [], None
    asks_raw = data.get("asks") or []
    bids_raw = data.get("bids") or []
    asks = _build_rows(asks_raw, ascending=True)[:MAX_LEVELS]
    bids = _build_rows(bids_raw, ascending=False)[:MAX_LEVELS]
    mid: float | None = None
    if asks and bids:
        mid = (asks[0].price + bids[0].price) / 2.0
    return asks, bids, mid


def _build_rows(raw: list[dict[str, Any]], *, ascending: bool) -> list[OrderbookRow]:
    parsed: list[tuple[float, float]] = []
    for row in raw:
        try:
            parsed.append((float(row["price"]), float(row["size"])))
        except (KeyError, TypeError, ValueError):
            continue
    parsed.sort(key=lambda r: r[0], reverse=not ascending)
    out: list[OrderbookRow] = []
    cumulative = 0.0
    for price, size in parsed:
        cumulative += size
        out.append(OrderbookRow(price=price, size=size, cumulative_size=cumulative))
    return out


def fetch_ctf_orderbook(
    window_ts: int,
    side: Literal["UP", "DOWN"] = "UP",
    *,
    slug_prefix: str = "btc-updown-5m",
    throttle_s: float = 2.0,
    _now: float | None = None,
) -> CTFBookSnapshot | None:
    now = _now if _now is not None else time.monotonic()
    cache_key = (window_ts, side)
    cached = _BOOK_CACHE.get(cache_key)
    if cached and (now - cached[1]) < throttle_s:
        return cached[0]
    up_id, down_id = _resolve_token_ids(window_ts, slug_prefix)
    token = up_id if side == "UP" else down_id
    if token is None:
        return None
    start = time.monotonic()
    asks, bids, mid = _fetch_book(token)
    rtt_ms = (time.monotonic() - start) * 1000.0
    snap = CTFBookSnapshot(
        market_slug=f"{slug_prefix}-{window_ts}",
        up_token_id=up_id,
        down_token_id=down_id,
        side=side,
        rows_ask=tuple(asks),
        rows_bid=tuple(bids),
        mid=mid,
        asof=datetime.now(tz=UTC),
        rtt_ms=rtt_ms,
    )
    _BOOK_CACHE[cache_key] = (snap, now)
    return snap


def reset_caches() -> None:
    """Test-only escape hatch: clears module-level token + book caches."""
    _TOKEN_CACHE.clear()
    _BOOK_CACHE.clear()

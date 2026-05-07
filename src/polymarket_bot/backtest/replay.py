"""Replay engine — captured Parquet → ordered MarketEvent stream.

Reads ticks/<UTC-date>/<source>_<launch_id>.parquet for the requested date
range, decodes payloads into typed MarketEvents (SpotTick, OracleUpdate,
BookUpdate, WindowBoundary), sorts by ts_utc_ns, and yields in event-time
order. WindowBoundary events are synthesised at every 300s mark inside the
date range so strategies see clean per-window state without doing window
arithmetic themselves.

Polymarket side resolution (token_id → "UP" | "DOWN") is injected at
construction time. Tests pass a StaticTokenSideResolver with a known mapping;
production code will pass a Gamma-backed resolver in a follow-up phase. If
the resolver returns None for an asset_id, the corresponding events are
skipped — the strategy depends on knowing the side, so emitting unknown-side
events would be silently incorrect.

In-memory load is intentional at this scale: a 7-day archive is roughly
1.7M events x ~200 bytes = ~340 MB peak, well under the laptop's RAM.
Streaming via polars LazyFrame can replace this if memory becomes an issue.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import polars as pl

from polymarket_bot.backtest.types import (
    BookUpdate,
    MarketEvent,
    OracleUpdate,
    Side,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.resolver import WINDOW_SECONDS, active_window_ts

CHAINLINK_BTC_USD_DECIMALS = 8

POLYMARKET_KINDS_WITH_TOP_OF_BOOK = frozenset({"book", "best_bid_ask", "price_change"})


SideResolver = Callable[[str], Side | None]
"""token_id → "UP" | "DOWN" | None. None ⇒ skip that event."""


class StaticTokenSideResolver:
    """Resolver backed by a fixed dict — used by tests and CLI runs.

    Production replay will use a Gamma-backed resolver that calls the
    Gamma events API for each window in the date range and caches
    asset_id → side internally. That's a follow-up phase; this static
    resolver is sufficient for unit tests and for backtests where the
    operator pre-builds an index.
    """

    def __init__(self, mapping: dict[str, Side]) -> None:
        self._map = dict(mapping)

    def __call__(self, token_id: str) -> Side | None:
        return self._map.get(token_id)


class ReplayEngine:
    """Reads captured Parquet and emits MarketEvents in ts_utc_ns order."""

    def __init__(
        self,
        ticks_root: str | Path,
        dates: list[str],
        *,
        side_resolver: SideResolver,
    ) -> None:
        if not dates:
            raise ValueError("ReplayEngine requires at least one date")
        self._ticks_root = Path(ticks_root)
        self._dates = list(dates)
        self._side_resolver = side_resolver

    def stream(self) -> AsyncIterator[MarketEvent]:
        return self._stream_impl()

    async def _stream_impl(self) -> AsyncIterator[MarketEvent]:
        events = self._load_all_events()
        boundaries = _synthesise_boundaries(self._dates, events)
        merged = _merge_sorted(events, boundaries)
        for event in merged:
            yield event

    def _load_all_events(self) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for date in self._dates:
            day_dir = self._ticks_root / date
            if not day_dir.exists():
                continue
            # Each row's `source` column is the canonical truth; we group
            # files by per-source glob mainly so we don't load unrelated
            # parquets in the directory. The decoder picks behaviour from
            # the row's source column, not the file name.
            for path in sorted(day_dir.glob("*.parquet")):
                out.extend(self._decode_file(path))
        out.sort(key=lambda e: e.ts_utc_ns)
        return out

    def _decode_file(self, path: Path) -> list[MarketEvent]:
        try:
            df = pl.read_parquet(path)
        except Exception:
            # Open-but-unreadable parquet is normal during a live capture
            # (the writer hasn't finalised the footer yet). Skip the file
            # and continue; subsequent backtests will pick it up after
            # the capture closes it cleanly.
            return []
        events: list[MarketEvent] = []
        for row in df.iter_rows(named=True):
            source = row.get("source")
            if not isinstance(source, str):
                continue
            decoded = _decode_row(source, row, self._side_resolver)
            events.extend(decoded)
        return events


def decode_record(record: object, side_resolver: SideResolver) -> list[MarketEvent]:
    """Public wrapper: decode a feeds.protocols.Record into MarketEvents.

    Phase 4 paper-mode (polymarket_bot._paper.runner) reuses the same
    decoder the backtest uses for Parquet rows, by passing live Records
    straight through. record must expose .ts_utc_ns, .source, .payload_json
    attributes — the production Record dataclass and any test fake do.
    Empty list when the record is malformed or has no top-of-book content.
    """
    source = getattr(record, "source", None)
    if not isinstance(source, str):
        return []
    row: dict[str, Any] = {
        "ts_utc_ns": getattr(record, "ts_utc_ns", 0),
        "payload_json": getattr(record, "payload_json", ""),
    }
    return _decode_row(source, row, side_resolver)


def _decode_row(source: str, row: dict[str, Any], side_resolver: SideResolver) -> list[MarketEvent]:
    """Decode one Parquet row into zero or more MarketEvents.

    A polymarket `price_change` row can contain multiple per-asset
    BookUpdates; everything else returns a single event or empty list.
    """
    ts = int(row["ts_utc_ns"])
    payload_str = row["payload_json"]
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return []

    if source == "binance":
        price = _safe_float(payload.get("p") if isinstance(payload, dict) else None)
        if price is None:
            return []
        return [SpotTick(ts_utc_ns=ts, source="binance", price=price)]

    if source == "coinbase":
        price = _safe_float(payload.get("price") if isinstance(payload, dict) else None)
        if price is None:
            return []
        return [SpotTick(ts_utc_ns=ts, source="coinbase", price=price)]

    if source == "oracle":
        decoded = _decode_oracle_log(payload)
        if decoded is None:
            return []
        current_scaled, round_id, updated_at_s = decoded
        return [
            OracleUpdate(
                ts_utc_ns=ts,
                price=current_scaled,
                round_id=round_id,
                updated_at_s=updated_at_s,
            )
        ]

    if source == "polymarket":
        return _decode_polymarket(ts, payload, side_resolver)

    return []


def _decode_oracle_log(payload: object) -> tuple[float, int, int] | None:
    if not isinstance(payload, dict):
        return None
    topics = payload.get("topics")
    data_hex = payload.get("data")
    if not isinstance(topics, list) or len(topics) < 3:
        return None
    if not isinstance(data_hex, str) or not data_hex.startswith("0x"):
        return None
    try:
        current_raw = int.from_bytes(bytes.fromhex(topics[1][2:]), "big", signed=True)
        round_id = int.from_bytes(bytes.fromhex(topics[2][2:]), "big", signed=False)
        updated_at_s = int(data_hex[2 : 2 + 64], 16)
    except (ValueError, IndexError):
        return None
    price = current_raw / (10**CHAINLINK_BTC_USD_DECIMALS)
    return price, round_id, updated_at_s


def _decode_polymarket(ts: int, payload: object, side_resolver: SideResolver) -> list[MarketEvent]:
    if not isinstance(payload, dict):
        return []
    kind = payload.get("event_type")
    if kind not in POLYMARKET_KINDS_WITH_TOP_OF_BOOK:
        return []

    if kind == "book":
        asset_id = _str(payload.get("asset_id"))
        if asset_id is None:
            return []
        side = side_resolver(asset_id)
        if side is None:
            return []
        best_bid, bid_size = _top_of_side(payload.get("bids"), best="max")
        best_ask, ask_size = _top_of_side(payload.get("asks"), best="min")
        return [
            BookUpdate(
                ts_utc_ns=ts,
                asset_id=asset_id,
                side=side,
                best_bid=best_bid,
                best_ask=best_ask,
                bid_size_top=bid_size,
                ask_size_top=ask_size,
            )
        ]

    if kind == "best_bid_ask":
        asset_id = _str(payload.get("asset_id"))
        if asset_id is None:
            return []
        side = side_resolver(asset_id)
        if side is None:
            return []
        return [
            BookUpdate(
                ts_utc_ns=ts,
                asset_id=asset_id,
                side=side,
                best_bid=_safe_float(payload.get("best_bid")),
                best_ask=_safe_float(payload.get("best_ask")),
                bid_size_top=None,
                ask_size_top=None,
            )
        ]

    # price_change: one or more per-asset book updates inside the message.
    out: list[MarketEvent] = []
    changes = payload.get("price_changes")
    if not isinstance(changes, list):
        return []
    for change in changes:
        if not isinstance(change, dict):
            continue
        asset_id = _str(change.get("asset_id"))
        if asset_id is None:
            continue
        side = side_resolver(asset_id)
        if side is None:
            continue
        out.append(
            BookUpdate(
                ts_utc_ns=ts,
                asset_id=asset_id,
                side=side,
                best_bid=_safe_float(change.get("best_bid")),
                best_ask=_safe_float(change.get("best_ask")),
                bid_size_top=None,
                ask_size_top=None,
            )
        )
    return out


def _top_of_side(levels: object, *, best: str) -> tuple[float | None, float | None]:
    if not isinstance(levels, list) or not levels:
        return None, None
    parsed = []
    for lvl in levels:
        if not isinstance(lvl, dict):
            continue
        price = _safe_float(lvl.get("price"))
        size = _safe_float(lvl.get("size"))
        if price is None or size is None:
            continue
        parsed.append((price, size))
    if not parsed:
        return None, None
    chosen = max(parsed, key=lambda x: x[0]) if best == "max" else min(parsed, key=lambda x: x[0])
    return chosen[0], chosen[1]


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _synthesise_boundaries(dates: list[str], events: list[MarketEvent]) -> list[WindowBoundary]:
    """Emit a `WindowBoundary(open)` at every 300s mark covered by the date range.

    Close is implicit at the next open. Open events are placed at exactly
    `window_ts * 1_000_000_000` ns so the merge sort puts them just before
    natural events that share the same window-open second.
    """
    if not events:
        return []
    first_ts_s = events[0].ts_utc_ns // 1_000_000_000
    last_ts_s = events[-1].ts_utc_ns // 1_000_000_000
    first_window = active_window_ts(first_ts_s)
    out: list[WindowBoundary] = []
    w = first_window
    while w <= last_ts_s:
        out.append(
            WindowBoundary(
                ts_utc_ns=w * 1_000_000_000,
                window_ts=w,
                kind="open",
            )
        )
        w += WINDOW_SECONDS
    return out


def _merge_sorted(events: list[MarketEvent], boundaries: list[WindowBoundary]) -> list[MarketEvent]:
    """Stable merge — boundary events placed before natural events on tie."""
    out: list[MarketEvent] = []
    i = j = 0
    while i < len(events) and j < len(boundaries):
        e_ts = events[i].ts_utc_ns
        b_ts = boundaries[j].ts_utc_ns
        if b_ts <= e_ts:  # boundary before tied real events
            out.append(boundaries[j])
            j += 1
        else:
            out.append(events[i])
            i += 1
    out.extend(boundaries[j:])
    out.extend(events[i:])
    return out

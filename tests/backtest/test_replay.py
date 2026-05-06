"""Tests for polymarket_bot.backtest.replay.ReplayEngine.

Drive the engine against synthetic Parquet fixtures written into tmp_path.
Cover: per-source decoding (binance trade, coinbase match, oracle log,
polymarket book/best_bid_ask/price_change), side resolver gating
(unknown asset_id → event skipped), event ordering (sort by ts_utc_ns),
WindowBoundary synthesis at every 300s mark, multi-launch parquet glob
(same date, multiple launch IDs).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import polars as pl

from polymarket_bot.backtest.replay import (
    ReplayEngine,
    StaticTokenSideResolver,
)
from polymarket_bot.backtest.types import (
    BookUpdate,
    MarketEvent,
    OracleUpdate,
    SpotTick,
    WindowBoundary,
)

WINDOW_TS = 1_715_000_100  # 300 * 5_716_667 — exact multiple
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20
TOKEN_UNKNOWN = "999" * 20


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = {
        "ts_utc_ns": [int(r["ts_utc_ns"]) for r in rows],
        "received_at_ns": [int(r.get("received_at_ns", r["ts_utc_ns"])) for r in rows],
        "source": [str(r["source"]) for r in rows],
        "kind": [str(r["kind"]) for r in rows],
        "payload_json": [str(r["payload_json"]) for r in rows],
    }
    pl.DataFrame(table).write_parquet(path)


def _binance_payload(price: float, ts_ms: int) -> str:
    return json.dumps(
        {"e": "trade", "E": ts_ms, "T": ts_ms, "s": "BTCUSDT", "p": str(price), "q": "0.001"},
        separators=(",", ":"),
    )


def _coinbase_payload(price: float, when_iso: str) -> str:
    return json.dumps(
        {
            "type": "match",
            "price": str(price),
            "size": "0.001",
            "product_id": "BTC-USD",
            "time": when_iso,
        },
        separators=(",", ":"),
    )


def _oracle_payload(price_scaled: int, round_id: int, updated_at: int) -> str:
    """Build a Chainlink AnswerUpdated log payload as the oracle feed archives it.

    price_scaled is the int256 'current' value pre-division (so 60_000.50 USD
    BTC ⇒ 60_000_50_000_000 with 8-decimal scaling).
    """
    if price_scaled < 0:
        topic1 = ((1 << 256) + price_scaled).to_bytes(32, "big").hex()
    else:
        topic1 = price_scaled.to_bytes(32, "big").hex()
    topic2 = round_id.to_bytes(32, "big").hex()
    data = updated_at.to_bytes(32, "big").hex()
    log = {
        "address": "0x" + "ab" * 20,
        "topics": [
            "0x0559884fd3a460db3073b7fc896cc77986f16e378210ded43186175bf646fc5f",
            "0x" + topic1,
            "0x" + topic2,
        ],
        "data": "0x" + data,
        "blockHash": "0x" + "11" * 32,
        "blockNumber": "0x1",
        "transactionHash": "0x" + "22" * 32,
        "transactionIndex": "0x0",
        "logIndex": "0x0",
        "removed": False,
    }
    return json.dumps(log, separators=(",", ":"))


def _polymarket_book_payload(asset_id: str, ts_ms: int) -> str:
    return json.dumps(
        {
            "event_type": "book",
            "asset_id": asset_id,
            "market": "0xabc",
            "bids": [
                {"price": "0.40", "size": "100"},
                {"price": "0.45", "size": "50"},
                {"price": "0.42", "size": "30"},
            ],
            "asks": [
                {"price": "0.55", "size": "100"},
                {"price": "0.50", "size": "50"},
                {"price": "0.52", "size": "30"},
            ],
            "timestamp": str(ts_ms),
            "hash": "0x" + "11" * 16,
        },
        separators=(",", ":"),
    )


def _polymarket_bba_payload(asset_id: str, best_bid: float, best_ask: float, ts_ms: int) -> str:
    return json.dumps(
        {
            "event_type": "best_bid_ask",
            "asset_id": asset_id,
            "market": "0xabc",
            "best_bid": str(best_bid),
            "best_ask": str(best_ask),
            "spread": str(best_ask - best_bid),
            "timestamp": str(ts_ms),
        },
        separators=(",", ":"),
    )


def _polymarket_pc_payload(asset_ids: list[str], ts_ms: int) -> str:
    return json.dumps(
        {
            "event_type": "price_change",
            "market": "0xabc",
            "price_changes": [
                {
                    "asset_id": aid,
                    "price": "0.50",
                    "size": "100",
                    "side": "BUY",
                    "hash": f"hash-{i}",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                }
                for i, aid in enumerate(asset_ids)
            ],
            "timestamp": str(ts_ms),
        },
        separators=(",", ":"),
    )


def _row(ts: int, source: str, kind: str, payload: str) -> dict[str, object]:
    return {
        "ts_utc_ns": ts,
        "received_at_ns": ts,
        "source": source,
        "kind": kind,
        "payload_json": payload,
    }


async def _collect(stream: object) -> list[MarketEvent]:
    out: list[MarketEvent] = []
    async for ev in stream:  # type: ignore[attr-defined]
        out.append(ev)
    return out


def _of_type(events: Iterable[MarketEvent], cls: type) -> list[MarketEvent]:
    return [e for e in events if isinstance(e, cls)]


async def test_decodes_binance_trade(tmp_path: Path) -> None:
    rows = [
        _row(
            WINDOW_OPEN_NS + 5_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_000.5, WINDOW_TS * 1000 + 5000),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "binance_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    spots = _of_type(events, SpotTick)

    assert len(spots) == 1
    spot = spots[0]
    assert isinstance(spot, SpotTick)
    assert spot.source == "binance"
    assert spot.price == 60_000.5
    assert spot.ts_utc_ns == WINDOW_OPEN_NS + 5_000_000_000


async def test_decodes_coinbase_match(tmp_path: Path) -> None:
    rows = [
        _row(
            WINDOW_OPEN_NS + 7_000_000_000,
            "coinbase",
            "match",
            _coinbase_payload(60_001.0, "2026-05-07T00:00:07Z"),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "coinbase_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    spots = _of_type(events, SpotTick)

    assert len(spots) == 1
    spot = spots[0]
    assert isinstance(spot, SpotTick)
    assert spot.source == "coinbase"
    assert spot.price == 60_001.0


async def test_decodes_oracle_log_with_correct_price_scaling(tmp_path: Path) -> None:
    # Chainlink BTC/USD scales by 1e8 — so 60_000.50 USD ⇒ 60_000_50_000_000.
    price_scaled = 60_000_50_000_000
    rows = [
        _row(
            WINDOW_OPEN_NS + 30_000_000_000,
            "oracle",
            "AnswerUpdated",
            _oracle_payload(
                price_scaled, round_id=18_446_744_073_709_551_616, updated_at=WINDOW_TS + 30
            ),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "oracle_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    oracles = _of_type(events, OracleUpdate)

    assert len(oracles) == 1
    o = oracles[0]
    assert isinstance(o, OracleUpdate)
    assert o.price == 60_000.5
    assert o.round_id == 18_446_744_073_709_551_616
    assert o.updated_at_s == WINDOW_TS + 30


async def test_decodes_polymarket_book_with_top_of_book(tmp_path: Path) -> None:
    rows = [
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "polymarket",
            "book",
            _polymarket_book_payload(TOKEN_UP, WINDOW_TS * 1000 + 1000),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "polymarket_test.parquet", rows)
    engine = ReplayEngine(
        tmp_path,
        ["2026-05-07"],
        side_resolver=StaticTokenSideResolver({TOKEN_UP: "UP"}),
    )

    events = await _collect(engine.stream())
    books = _of_type(events, BookUpdate)

    assert len(books) == 1
    b = books[0]
    assert isinstance(b, BookUpdate)
    assert b.side == "UP"
    assert b.asset_id == TOKEN_UP
    # bids/asks fixture: bids prices [0.40, 0.45, 0.42], asks prices [0.55, 0.50, 0.52]
    # best_bid = max(bids) = 0.45;  best_ask = min(asks) = 0.50
    assert b.best_bid == 0.45
    assert b.best_ask == 0.50


async def test_polymarket_event_with_unknown_asset_id_is_skipped(tmp_path: Path) -> None:
    rows = [
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "polymarket",
            "book",
            _polymarket_book_payload(TOKEN_UNKNOWN, WINDOW_TS * 1000 + 1000),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "polymarket_test.parquet", rows)
    engine = ReplayEngine(
        tmp_path,
        ["2026-05-07"],
        side_resolver=StaticTokenSideResolver({TOKEN_UP: "UP"}),  # TOKEN_UNKNOWN absent
    )

    events = await _collect(engine.stream())
    books = _of_type(events, BookUpdate)

    assert books == []


async def test_polymarket_price_change_emits_one_event_per_known_asset(tmp_path: Path) -> None:
    # Three asset_ids in the price_change; only TWO are in the resolver.
    payload = _polymarket_pc_payload([TOKEN_UP, TOKEN_DOWN, TOKEN_UNKNOWN], WINDOW_TS * 1000 + 2000)
    rows = [_row(WINDOW_OPEN_NS + 2_000_000_000, "polymarket", "price_change", payload)]
    _write_parquet(tmp_path / "2026-05-07" / "polymarket_test.parquet", rows)
    engine = ReplayEngine(
        tmp_path,
        ["2026-05-07"],
        side_resolver=StaticTokenSideResolver({TOKEN_UP: "UP", TOKEN_DOWN: "DOWN"}),
    )

    events = await _collect(engine.stream())
    books = _of_type(events, BookUpdate)

    assert len(books) == 2
    sides = {b.side for b in books if isinstance(b, BookUpdate)}
    assert sides == {"UP", "DOWN"}


async def test_events_yield_in_ts_utc_ns_order(tmp_path: Path) -> None:
    rows = [
        _row(
            WINDOW_OPEN_NS + 9_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_000.0, WINDOW_TS * 1000 + 9000),
        ),
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_010.0, WINDOW_TS * 1000 + 1000),
        ),
        _row(
            WINDOW_OPEN_NS + 5_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_020.0, WINDOW_TS * 1000 + 5000),
        ),
    ]
    _write_parquet(tmp_path / "2026-05-07" / "binance_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    spots = [e for e in events if isinstance(e, SpotTick)]

    timestamps = [e.ts_utc_ns for e in spots]
    assert timestamps == sorted(timestamps)


async def test_synthesises_window_boundaries_at_300s_marks(tmp_path: Path) -> None:
    # One event very early, one event 700s later → boundaries at WINDOW_TS, +300, +600.
    rows = [
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_000.0, WINDOW_TS * 1000 + 1000),
        ),
        _row(
            WINDOW_OPEN_NS + 700_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_010.0, (WINDOW_TS + 700) * 1000),
        ),
    ]
    _write_parquet(tmp_path / "2026-05-07" / "binance_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    boundaries = [e for e in events if isinstance(e, WindowBoundary)]

    boundary_windows = [b.window_ts for b in boundaries]
    assert boundary_windows == [WINDOW_TS, WINDOW_TS + 300, WINDOW_TS + 600]
    for b in boundaries:
        assert isinstance(b, WindowBoundary)
        assert b.kind == "open"


async def test_boundary_emitted_before_natural_event_at_same_second(tmp_path: Path) -> None:
    """When a boundary and a natural event share the same ts, the boundary fires first."""
    rows = [_row(WINDOW_OPEN_NS, "binance", "trade", _binance_payload(60_000.0, WINDOW_TS * 1000))]
    _write_parquet(tmp_path / "2026-05-07" / "binance_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())

    assert len(events) == 2
    assert isinstance(events[0], WindowBoundary)
    assert isinstance(events[1], SpotTick)


async def test_multi_launch_files_for_same_date_both_loaded(tmp_path: Path) -> None:
    """Two parquet files for the same date (laptop sleep restart) ⇒ both load."""
    rows1 = [
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_000.0, WINDOW_TS * 1000 + 1000),
        )
    ]
    rows2 = [
        _row(
            WINDOW_OPEN_NS + 50_000_000_000,
            "binance",
            "trade",
            _binance_payload(60_010.0, WINDOW_TS * 1000 + 50_000),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "binance_aaa.parquet", rows1)
    _write_parquet(tmp_path / "2026-05-07" / "binance_bbb.parquet", rows2)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    spots = [e for e in events if isinstance(e, SpotTick)]

    assert len(spots) == 2
    prices = {s.price for s in spots if isinstance(s, SpotTick)}
    assert prices == {60_000.0, 60_010.0}


async def test_negative_oracle_price_decoded_as_signed(tmp_path: Path) -> None:
    """int256 'current' can be negative for some Chainlink feeds; verify sign."""
    price_scaled = -1_500_00_000_000  # -1500.00 USD scaled
    rows = [
        _row(
            WINDOW_OPEN_NS + 1_000_000_000,
            "oracle",
            "AnswerUpdated",
            _oracle_payload(price_scaled, round_id=1, updated_at=WINDOW_TS + 1),
        )
    ]
    _write_parquet(tmp_path / "2026-05-07" / "oracle_test.parquet", rows)
    engine = ReplayEngine(tmp_path, ["2026-05-07"], side_resolver=StaticTokenSideResolver({}))

    events = await _collect(engine.stream())
    oracles = [e for e in events if isinstance(e, OracleUpdate)]

    assert len(oracles) == 1
    assert isinstance(oracles[0], OracleUpdate)
    assert oracles[0].price == -1_500.0


def test_static_resolver_returns_none_for_unknown() -> None:
    r = StaticTokenSideResolver({TOKEN_UP: "UP"})
    assert r(TOKEN_UP) == "UP"
    assert r(TOKEN_DOWN) is None

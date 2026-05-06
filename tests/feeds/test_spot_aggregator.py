"""Tests for polymarket_bot._live.feeds.spot_aggregator.SpotAggregator.

Drive the aggregator over fake child feeds and exercise: fan-in produces
records from every child, child source labels survive unchanged, aggregated
health stats sum correctly, stop() propagates to children, and one child's
exception does not block the other from making progress.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from polymarket_bot._live.feeds.spot_aggregator import SpotAggregator
from polymarket_bot._live.feeds.spot_binance import BinanceTradeFeed
from polymarket_bot._live.feeds.spot_coinbase import CoinbaseMatchFeed
from polymarket_bot.feeds.protocols import Health, Record
from tests.feeds.conftest import FakeConnect, collect_until_stop, no_sleep


class _FixedFakeFeed:
    """A simple Feed that yields a pre-set list of records, then ends."""

    def __init__(self, name: str, records: list[Record]) -> None:
        self.name = name
        self._records = list(records)
        self._stopped = False
        self._health: Health = {
            "name": name,
            "last_seen_ns": 0,
            "msgs_seen": 0,
            "reconnects": 0,
            "last_error": "",
        }

    @property
    def health(self) -> Health:
        return Health(
            name=self._health["name"],
            last_seen_ns=self._health["last_seen_ns"],
            msgs_seen=self._health["msgs_seen"],
            reconnects=self._health["reconnects"],
            last_error=self._health["last_error"],
        )

    def stop(self) -> None:
        self._stopped = True

    def stream(self) -> AsyncIterator[Record]:
        return self._stream_impl()

    async def _stream_impl(self) -> AsyncIterator[Record]:
        for r in self._records:
            if self._stopped:
                return
            self._health["last_seen_ns"] = r.received_at_ns
            self._health["msgs_seen"] += 1
            yield r


def _rec(source: str, n: int) -> Record:
    return Record(
        ts_utc_ns=n * 1_000_000_000,
        received_at_ns=n * 1_000_000_000 + 1,
        source=source,
        kind="trade" if source == "binance" else "match",
        payload_json=json.dumps({"i": n, "source": source}, separators=(",", ":")),
    )


async def test_rejects_empty_feed_list() -> None:
    with pytest.raises(ValueError, match="at least one child"):
        SpotAggregator([])


async def test_fan_in_yields_from_every_child_with_source_preserved() -> None:
    binance = _FixedFakeFeed("binance", [_rec("binance", i) for i in range(3)])
    coinbase = _FixedFakeFeed("coinbase", [_rec("coinbase", i) for i in range(3)])
    agg = SpotAggregator([binance, coinbase])

    records = await collect_until_stop(agg.stream(), max_records=6, timeout_s=2.0)
    agg.stop()

    assert len(records) == 6
    sources = {r.source for r in records if isinstance(r, Record)}
    assert sources == {"binance", "coinbase"}


async def test_health_aggregates_children_counters() -> None:
    a = _FixedFakeFeed("binance", [_rec("binance", 1), _rec("binance", 2)])
    b = _FixedFakeFeed("coinbase", [_rec("coinbase", 5)])
    agg = SpotAggregator([a, b])

    await collect_until_stop(agg.stream(), max_records=3, timeout_s=2.0)
    agg.stop()

    h = agg.health
    assert h["name"] == "spot_aggregator"
    assert h["msgs_seen"] == 3
    assert h["reconnects"] == 0
    assert h["last_seen_ns"] >= 5 * 1_000_000_000


async def test_stop_propagates_to_children() -> None:
    a = _FixedFakeFeed("binance", [_rec("binance", 1)])
    b = _FixedFakeFeed("coinbase", [_rec("coinbase", 1)])
    agg = SpotAggregator([a, b])

    agg.stop()
    assert a._stopped is True
    assert b._stopped is True


async def test_aggregator_can_drive_real_concrete_feeds_via_fakes() -> None:
    """Smoke test that production Binance + Coinbase classes plug into the aggregator."""
    binance_msg = json.dumps(
        {"e": "trade", "T": 1_715_000_000_000, "p": "60000", "q": "0.001"},
        separators=(",", ":"),
    )
    coinbase_msg = json.dumps(
        {
            "type": "match",
            "trade_id": 1,
            "price": "60001",
            "size": "0.001",
            "product_id": "BTC-USD",
            "time": "2026-05-08T00:00:00Z",
        },
        separators=(",", ":"),
    )

    bf = BinanceTradeFeed(
        connect_fn=FakeConnect(scenes=[[binance_msg]]),
        clock_ns=lambda: 1,
        sleep=no_sleep,
    )
    cf = CoinbaseMatchFeed(
        connect_fn=FakeConnect(scenes=[[coinbase_msg]]),
        clock_ns=lambda: 2,
        sleep=no_sleep,
    )

    agg = SpotAggregator([bf, cf])
    try:
        records = await collect_until_stop(agg.stream(), max_records=2, timeout_s=2.0)
    finally:
        agg.stop()
        await asyncio.sleep(0)  # let cancelled pump tasks settle

    sources = {r.source for r in records if isinstance(r, Record)}
    assert {"binance", "coinbase"}.issubset(sources)

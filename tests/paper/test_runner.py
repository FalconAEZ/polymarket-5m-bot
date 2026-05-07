"""Tests for polymarket_bot._paper.runner.PaperRunner.

Drive PaperRunner with a FakeFeed that yields a synthetic Record sequence
(spot, oracle, polymarket book, then a 300s rollover). A FakeStrategy
returns one Decision when asked. Asserts: decision_log captures both a
fired and a settled line; the snapshot contains the expected fields;
P&L is non-zero when the resolution agrees with the bet side; multiple
decisions in one window are dropped with a warning. No real network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from polymarket_bot._paper.decision_log import DecisionLog, read_jsonl
from polymarket_bot._paper.runner import PaperRunner
from polymarket_bot._paper.shadow_book import ShadowBook
from polymarket_bot.backtest.replay import StaticTokenSideResolver
from polymarket_bot.backtest.types import Decision, MarketEvent
from polymarket_bot.feeds.protocols import Feed, Health, Record


def _list_jsonl(root: Path) -> list[Path]:
    """Sync helper — async tests cannot call Path.glob directly under ruff ASYNC240."""
    return sorted(root.glob("*.jsonl"))


ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32
WINDOW_TS = 1_762_540_500
WINDOW_TS_NEXT = WINDOW_TS + 300


class FakeFeed:
    """Yields a fixed list of Records from a list."""

    name: str = "fake"

    def __init__(self, records: list[Record]) -> None:
        self._records = records
        self._stopped = asyncio.Event()
        self._health: Health = Health(
            name=self.name,
            last_seen_ns=0,
            msgs_seen=0,
            reconnects=0,
            last_error="",
        )

    @property
    def health(self) -> Health:
        return self._health

    def stop(self) -> None:
        self._stopped.set()

    async def stream(self) -> AsyncIterator[Record]:
        for record in self._records:
            if self._stopped.is_set():
                return
            yield record
            await asyncio.sleep(0)


_: type[Feed] = FakeFeed


def _record(
    *,
    ts_utc_ns: int,
    source: str,
    payload: dict[str, Any],
    kind: str = "msg",
) -> Record:
    return Record(
        ts_utc_ns=ts_utc_ns,
        received_at_ns=ts_utc_ns,
        source=source,
        kind=kind,
        payload_json=json.dumps(payload, separators=(",", ":")),
    )


def _spot_record(ts_s: int, price: float) -> Record:
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000,
        source="binance",
        payload={"p": str(price), "T": ts_s * 1000},
    )


def _oracle_record(ts_s: int, price_usd: float) -> Record:
    """Build a Chainlink AnswerUpdated log with correct topics encoding."""
    raw = int(price_usd * 1e8)
    topics_1 = "0x" + raw.to_bytes(32, "big", signed=True).hex()
    topics_2 = "0x" + (1).to_bytes(32, "big", signed=False).hex()
    data = "0x" + ts_s.to_bytes(32, "big").hex()
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + 1,
        source="oracle",
        payload={"topics": ["0x...sig...", topics_1, topics_2], "data": data},
    )


def _book_record(
    ts_s: int,
    asset_id: str,
    *,
    best_bid: float = 0.49,
    best_ask: float = 0.50,
    ask_size: float = 10_000.0,
) -> Record:
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + 2,
        source="polymarket",
        payload={
            "event_type": "book",
            "asset_id": asset_id,
            "bids": [{"price": str(best_bid), "size": str(ask_size)}],
            "asks": [{"price": str(best_ask), "size": str(ask_size)}],
        },
    )


class FakeStrategy:
    """Fires exactly one Decision on the second BookUpdate it sees."""

    name: str = "fake_strategy"

    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self._fired = False
        self._book_count = 0
        self.events_seen: list[MarketEvent] = []

    async def on_event(self, event: MarketEvent) -> Decision | None:
        from polymarket_bot.backtest.types import BookUpdate

        self.events_seen.append(event)
        if isinstance(event, BookUpdate):
            self._book_count += 1
        if not self._fired and self._book_count >= 2:
            self._fired = True
            return self._decision
        return None

    def reset(self) -> None:
        self._fired = False
        self._book_count = 0


class MultiFireStrategy:
    """Fires two Decisions in the same window; runner must drop the second."""

    name: str = "multi_fire"

    def __init__(self, first: Decision, second: Decision) -> None:
        self._first = first
        self._second = second
        self._book_count = 0

    async def on_event(self, event: MarketEvent) -> Decision | None:
        from polymarket_bot.backtest.types import BookUpdate

        if isinstance(event, BookUpdate):
            self._book_count += 1
            if self._book_count == 2:
                return self._first
            if self._book_count == 3:
                return self._second
        return None

    def reset(self) -> None:
        self._book_count = 0


def _resolver() -> StaticTokenSideResolver:
    return StaticTokenSideResolver({ASSET_UP: "UP", ASSET_DOWN: "DOWN"})


def _decision_in_window(
    *,
    asset_id: str = ASSET_UP,
    side_marker: str = "side=UP",
    decision_ts_s: int = WINDOW_TS + 12,
    price_limit: float = 0.55,
    ttl_s: int = 60,
) -> Decision:
    return Decision(
        ts_utc_ns=decision_ts_s * 1_000_000_000,
        asset_id=asset_id,
        side="BUY",
        size_usd=5.0,
        price_limit=price_limit,
        ttl_s=ttl_s,
        rationale=f"composite=+0.612pct (|.|>=0.60) ttl={ttl_s}s {side_marker}",
    )


@pytest.mark.asyncio
async def test_paper_runner_emits_fired_and_settled(tmp_path: Path) -> None:
    """Records flow: spot -> oracle (window open) -> book -> book (decision fires)
    -> oracle (T+30) -> spot at next window (rollover) -> close, settle, log."""
    records = [
        _spot_record(WINDOW_TS + 5, 67400.00),
        _oracle_record(WINDOW_TS + 6, 67400.00),
        _book_record(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book_record(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),  # FakeStrategy fires
        _oracle_record(WINDOW_TS + 250, 67500.00),  # close oracle (UP wins)
        _spot_record(WINDOW_TS_NEXT + 1, 67510.00),  # rollover trigger
    ]
    feed = FakeFeed(records)
    strategy = FakeStrategy(
        _decision_in_window(decision_ts_s=WINDOW_TS + 12, ttl_s=60, price_limit=0.55)
    )
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
    )
    await runner.run()

    files = _list_jsonl(tmp_path)
    assert len(files) == 1
    entries = list(read_jsonl(files[0]))
    fired = [e for e in entries if e["kind"] == "fired"]
    settled = [e for e in entries if e["kind"] == "settled"]
    assert len(fired) == 1
    assert len(settled) == 1
    f, s = fired[0], settled[0]
    assert f["decision_id"] == s["decision_id"]
    assert f["window_ts"] == WINDOW_TS
    assert f["side"] == "UP"
    assert f["asset_id"] == ASSET_UP
    assert f["composite_pct"] == pytest.approx(0.612)
    # fill happens immediately because the limit (0.55) >= effective ask (~0.50).
    assert f["fill"] is not None
    assert f["fill"]["price_filled"] == pytest.approx(0.50, abs=0.01)
    # settled line: UP resolution (close oracle 67500 > open 67400) -> won
    assert s["resolution"] == "UP"
    assert s["pnl_usd"] > 0


@pytest.mark.asyncio
async def test_paper_runner_records_pnl_loss_on_wrong_side(tmp_path: Path) -> None:
    """Same scenario, but oracle moves DOWN — UP bet loses."""
    records = [
        _spot_record(WINDOW_TS + 5, 67400.00),
        _oracle_record(WINDOW_TS + 6, 67400.00),
        _book_record(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book_record(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle_record(WINDOW_TS + 250, 67200.00),  # DOWN
        _spot_record(WINDOW_TS_NEXT + 1, 67200.00),
    ]
    feed = FakeFeed(records)
    strategy = FakeStrategy(_decision_in_window(decision_ts_s=WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
    )
    await runner.run()

    entries = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    settled = next(e for e in entries if e["kind"] == "settled")
    assert settled["resolution"] == "DOWN"
    assert settled["pnl_usd"] < 0  # paid for UP shares; UP lost


@pytest.mark.asyncio
async def test_paper_runner_drops_second_decision_in_same_window(
    tmp_path: Path,
) -> None:
    """Phase-3 invariant: at most one Decision per window; second is dropped."""
    records = [
        _oracle_record(WINDOW_TS + 1, 67400.00),
        _book_record(WINDOW_TS + 5, ASSET_UP, best_ask=0.50),
        _book_record(WINDOW_TS + 10, ASSET_UP, best_ask=0.50),  # 1st fire
        _book_record(WINDOW_TS + 20, ASSET_UP, best_ask=0.50),  # 2nd fire (dropped)
        _oracle_record(WINDOW_TS + 250, 67500.00),
        _spot_record(WINDOW_TS_NEXT + 1, 67500.00),
    ]
    feed = FakeFeed(records)
    first = _decision_in_window(decision_ts_s=WINDOW_TS + 10)
    second = _decision_in_window(decision_ts_s=WINDOW_TS + 20)
    strategy = MultiFireStrategy(first, second)
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000,
    )
    await runner.run()

    entries = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fired = [e for e in entries if e["kind"] == "fired"]
    settled = [e for e in entries if e["kind"] == "settled"]
    # exactly one fired, one settled — second decision was dropped
    assert len(fired) == 1
    assert len(settled) == 1
    assert fired[0]["decision_ts_ns"] == first.ts_utc_ns


@pytest.mark.asyncio
async def test_paper_runner_no_fire_no_settled_line(tmp_path: Path) -> None:
    """If the strategy never fires, no decision lines are written."""

    class SilentStrategy:
        name = "silent"

        async def on_event(self, _event: MarketEvent) -> Decision | None:
            return None

        def reset(self) -> None: ...

    records = [
        _oracle_record(WINDOW_TS + 1, 67400.00),
        _spot_record(WINDOW_TS + 5, 67400.00),
        _book_record(WINDOW_TS + 10, ASSET_UP),
        _spot_record(WINDOW_TS_NEXT + 1, 67500.00),  # rollover
    ]
    feed = FakeFeed(records)
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=SilentStrategy(),
        side_resolver=_resolver(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000,
    )
    await runner.run()
    files = _list_jsonl(tmp_path)
    # Nothing fired -> nothing written -> no file created at all.
    assert files == []


@pytest.mark.asyncio
async def test_paper_runner_handles_no_fill_within_ttl(tmp_path: Path) -> None:
    """A decision whose limit is below the ask never fills; settled fill_at_settle is None."""
    records = [
        _oracle_record(WINDOW_TS + 1, 67400.00),
        _book_record(WINDOW_TS + 5, ASSET_UP, best_ask=0.50),
        _book_record(WINDOW_TS + 10, ASSET_UP, best_ask=0.50),  # decision fires (limit too low)
        _book_record(WINDOW_TS + 30, ASSET_UP, best_ask=0.50),  # still no fill
        _oracle_record(WINDOW_TS + 250, 67500.00),
        _spot_record(WINDOW_TS_NEXT + 1, 67500.00),
    ]
    feed = FakeFeed(records)
    strategy = FakeStrategy(
        _decision_in_window(decision_ts_s=WINDOW_TS + 10, price_limit=0.40, ttl_s=15)
    )
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000,
    )
    await runner.run()

    entries = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fired = next(e for e in entries if e["kind"] == "fired")
    settled = next(e for e in entries if e["kind"] == "settled")
    assert fired["fill"] is None
    assert settled["fill_at_settle"] is None
    assert settled["pnl_usd"] == 0.0

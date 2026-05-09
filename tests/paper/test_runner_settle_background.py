"""Tests for PaperRunner background-settle architecture.

Per runbooks/incidents/2026-05-09-instant-settle-queue-overflow.md and
~/.claude/projects/.../memory/feedback_test_under_load.md. The previous
inline-await settle blocked the main loop for up to 30s on every window
boundary; under live feed traffic the queue overflowed and ~4,600 records
were dropped. The fix is fire-and-forget asyncio tasks driven by a state
snapshot. These tests verify the four invariants from the postmortem:

1. Main loop keeps draining the queue while a slow settle is in flight
   (the queue-doesn't-overflow assertion — the explicit lesson from the
   incident; without this test, the fix isn't done).
2. A settle-task exception never propagates to / kills the runner.
3. Shutdown awaits in-flight settles so settled records aren't lost.
4. Settle reads from the snapshot — not live `self._state` — so the next
   window's mutations don't corrupt the in-flight settle's record.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from polymarket_bot._paper.decision_log import DecisionLog, read_jsonl
from polymarket_bot._paper.runner import PaperRunner
from polymarket_bot._paper.shadow_book import ShadowBook
from polymarket_bot.backtest.replay import StaticTokenSideResolver
from polymarket_bot.backtest.types import Decision
from polymarket_bot.feeds.protocols import Feed, Health, Record


def _list_jsonl(root: Path) -> list[Path]:
    return sorted(root.glob("*.jsonl"))


ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32
WINDOW_TS = 1_762_540_500
WINDOW_TS_NEXT = WINDOW_TS + 300
WINDOW_TS_NEXT_2 = WINDOW_TS + 600


class _FakeFeed:
    """Yields records optionally with a small per-record delay so the
    runner gets to interleave its consumer loop with a slow settle."""

    name: str = "fake"

    def __init__(self, records: list[Record], *, delay_per_record_s: float = 0.0) -> None:
        self._records = records
        self._delay = delay_per_record_s
        self._stopped = asyncio.Event()
        self._health: Health = Health(
            name=self.name, last_seen_ns=0, msgs_seen=0, reconnects=0, last_error=""
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
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            else:
                await asyncio.sleep(0)


_: type[Feed] = _FakeFeed


def _record(*, ts_utc_ns: int, source: str, payload: dict[str, Any]) -> Record:
    return Record(
        ts_utc_ns=ts_utc_ns,
        received_at_ns=ts_utc_ns,
        source=source,
        kind="msg",
        payload_json=json.dumps(payload, separators=(",", ":")),
    )


def _spot(ts_s: int, price: float, *, ns_offset: int = 0) -> Record:
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + ns_offset,
        source="binance",
        payload={"p": str(price), "T": ts_s * 1000},
    )


def _oracle(ts_s: int, price_usd: float) -> Record:
    raw = int(price_usd * 1e8)
    topics_1 = "0x" + raw.to_bytes(32, "big", signed=True).hex()
    topics_2 = "0x" + (1).to_bytes(32, "big", signed=False).hex()
    data = "0x" + ts_s.to_bytes(32, "big").hex()
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + 1,
        source="oracle",
        payload={"topics": ["0x...sig...", topics_1, topics_2], "data": data},
    )


def _book(ts_s: int, asset_id: str, *, best_ask: float = 0.50) -> Record:
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + 2,
        source="polymarket",
        payload={
            "event_type": "book",
            "asset_id": asset_id,
            "bids": [{"price": str(best_ask - 0.01), "size": "10000"}],
            "asks": [{"price": str(best_ask), "size": "10000"}],
        },
    )


class _FakeStrategy:
    """Returns one Decision the first time a matching book event arrives;
    can be re-armed with `arm_for_next_window` to fire again in window 2."""

    name: str = "fake"

    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self._fired = False

    def arm(self, decision: Decision) -> None:
        self._decision = decision
        self._fired = False

    async def on_event(self, event: Any) -> Decision | None:
        from polymarket_bot.backtest.types import BookUpdate

        if isinstance(event, BookUpdate) and not self._fired and event.asset_id == ASSET_UP:
            self._fired = True
            return self._decision
        return None


def _resolver() -> StaticTokenSideResolver:
    return StaticTokenSideResolver(
        {
            ASSET_UP: ("UP", WINDOW_TS, 1),
            ASSET_DOWN: ("DOWN", WINDOW_TS, 1),
        }
    )


def _decision_at(ts_s: int) -> Decision:
    return Decision(
        ts_utc_ns=ts_s * 1_000_000_000,
        asset_id=ASSET_UP,
        side="BUY",
        size_usd=5.0,
        price_limit=0.55,
        ttl_s=60,
        rationale="composite=+0.612pct ttl=60s side=UP",
    )


def _gamma_resolves(resolution: str, *, sleep_s: float = 0.0) -> httpx.MockTransport:
    """Mock gamma transport. If sleep_s>0, blocks the calling THREAD for
    that long before returning — simulating a slow Polymarket Gamma reply.
    The runner's poll wraps this in asyncio.to_thread so the event loop
    keeps running, but a synchronous sleep here exercises the I/O wait
    just like a real network roundtrip would."""

    payload = [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["1", "0"] if resolution == "UP" else ["0", "1"],
                }
            ]
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if sleep_s > 0:
            time.sleep(sleep_s)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


# ----------------------------------------------------------------------
# Test 1 — the queue-doesn't-overflow check (the explicit lesson from
# feedback_test_under_load.md). The OLD inline-await settle blocked the
# main loop while gamma slept; under feed traffic the bounded queue
# overflowed and dropped market events. With the background-task fix,
# the main loop returns to queue.get() the instant the settle is
# scheduled, so it keeps draining records throughout the slow gamma poll.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_loop_processes_records_during_slow_settle(tmp_path: Path) -> None:
    """During a slow gamma poll, the main loop must keep pulling from the
    queue. With the OLD inline-await code path, this test would drop
    records (queue overflow). With the NEW background-task path, zero
    drops are tolerated."""

    # Window 1: spot, oracle (open), book that triggers a fire, oracle
    # (close), spot at next window (rolls over → settle scheduled).
    # Window 2: a burst of spot records that the main loop must drain
    # WHILE the slow settle is in flight.
    burst = [_spot(WINDOW_TS_NEXT + 5 + i, 67510.00 + i, ns_offset=i) for i in range(80)]
    records = [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # rolls window 1 → settle starts
        *burst,
    ]

    feed = _FakeFeed(records, delay_per_record_s=0.005)  # ~80 * 5ms = 400ms
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # 600ms gamma sleep: long enough that the entire 400ms feed burst
    # would land during the await with the old inline code. queue_size=8
    # makes the bound tight: 80 records arriving while main loop is
    # blocked would absolutely overflow an 8-slot queue (drop-oldest
    # policy → dropped > 0). Background-task fix: main loop drains in
    # parallel → dropped == 0.
    transport = _gamma_resolves("UP", sleep_s=0.6)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        queue_size=8,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=2.0,
        instant_settle_interval_s=0.05,
    )
    await runner.run()

    assert runner.dropped_records_total == 0, (
        f"main loop blocked during settle — {runner.dropped_records_total} "
        "records dropped (this is the queue-overflow regression)"
    )
    settled = next(e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled")
    assert settled["resolution_source"] == "polymarket"
    assert settled["resolution"] == "UP"


# ----------------------------------------------------------------------
# Test 2 — a settle-task exception must not kill the runner. The next
# window's settle still runs, and the main loop keeps processing records.
# ----------------------------------------------------------------------


class _RaisingOnceLog(DecisionLog):
    """DecisionLog that raises a non-OSError exception on the FIRST call
    to record_settled, then behaves normally. Used to verify the settle
    background task's blanket exception handler doesn't propagate up to
    the main runner loop. RuntimeError (not OSError) is chosen because
    OSError is already individually caught and alerted in _do_settle —
    the test must exercise the outer try/except in _settle_window_background."""

    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self._raised = False

    def record_settled(self, **kwargs: Any) -> None:  # type: ignore[override]
        if not self._raised:
            self._raised = True
            raise RuntimeError("simulated settle blowup")
        super().record_settled(**kwargs)


@pytest.mark.asyncio
async def test_settle_task_failure_doesnt_kill_runner(tmp_path: Path) -> None:
    """If a settle background task raises, the runner's main loop must
    continue uninterrupted: subsequent records process, the next
    window's decision fires, and that window's settle runs normally."""

    class _AlwaysFireStrategy:
        name = "always-fire"

        def __init__(self) -> None:
            self._last_fire_window: int | None = None

        async def on_event(self, event: Any) -> Decision | None:
            from polymarket_bot.backtest.types import BookUpdate, WindowBoundary

            if isinstance(event, WindowBoundary) and event.kind == "open":
                self._last_fire_window = None
                return None
            if isinstance(event, BookUpdate) and event.asset_id == ASSET_UP:
                w = (event.ts_utc_ns // 1_000_000_000) // 300 * 300
                if self._last_fire_window != w:
                    self._last_fire_window = w
                    return _decision_at(event.ts_utc_ns // 1_000_000_000)
            return None

    records = [
        # Window 1 — fires; W1 settle will raise (record_settled blows up)
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # rolls → W1 settle (raises)
        # Window 2 — fires + closes; W2 settle succeeds (log no longer raising)
        _oracle(WINDOW_TS_NEXT + 5, 67510.00),
        _book(WINDOW_TS_NEXT + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS_NEXT + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS_NEXT + 250, 67600.00),
        _spot(WINDOW_TS_NEXT_2 + 1, 67620.00),  # rolls → W2 settle (writes)
    ]

    feed = _FakeFeed(records)
    strategy = _AlwaysFireStrategy()
    log = _RaisingOnceLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT_2 * 1_000_000_000 + 5_000_000_000,
        # instant-settle off so the path goes straight through chainlink
        # and into the raising record_settled — keeps the test fast.
    )

    # Must complete without propagating the RuntimeError.
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fired = [e for e in events if e["kind"] == "fired"]
    settled = [e for e in events if e["kind"] == "settled"]
    # Both windows fired (proving main loop wasn't killed by W1's settle raise).
    assert len(fired) == 2, f"expected 2 fires, got {len(fired)}: {fired}"
    # W1's settle raised → no settled record for W1.
    # W2's settle succeeded → exactly one settled record, for W2.
    assert len(settled) == 1
    assert settled[0]["window_ts"] == WINDOW_TS_NEXT


# ----------------------------------------------------------------------
# Test 3 — shutdown awaits in-flight settles so we don't lose settled
# records when the runner stops mid-flight.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_awaits_in_flight_settles(tmp_path: Path) -> None:
    """Trigger a window rollover (which kicks off a slow background
    settle), then signal stop while gamma is still polling. run() must
    not return until the in-flight settle completes and writes its
    settled record."""

    records = [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # rolls → settle starts
    ]
    feed = _FakeFeed(records)
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # 400ms slow gamma — long enough that we can kick stop in between.
    transport = _gamma_resolves("UP", sleep_s=0.4)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=2.0,
        instant_settle_interval_s=0.05,
    )

    stop = asyncio.Event()

    async def trigger_stop() -> None:
        # Wait briefly so the settle task has been scheduled but
        # has not yet completed; then signal stop.
        await asyncio.sleep(0.1)
        stop.set()
        runner.stop()

    await asyncio.gather(runner.run(stop=stop), trigger_stop())

    settled = [e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled"]
    # Despite the early stop, the in-flight settle should have completed.
    assert len(settled) == 1
    assert settled[0]["window_ts"] == WINDOW_TS
    assert settled[0]["resolution_source"] == "polymarket"


# ----------------------------------------------------------------------
# Test 4 — settle reads from the snapshot, not from live `_state`. By
# the time the background task runs, `start_window` has reset window_ts
# / decision_id for the next window. The settle must still write the
# CLOSING window's identifiers, not the new ones.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_uses_snapshot_not_live_state(tmp_path: Path) -> None:
    """When a slow settle for window 1 is in flight, the main loop has
    already advanced `_state` to window 2. The settled record must
    reference the window-1 decision_id and window_ts (snapshot), not the
    live window-2 values."""

    # Window 1 fires, rolls to W2 (settle begins, slow gamma keeps it in
    # flight). Then in W2 we observe more records that mutate _state
    # (start_window already cleared decision_id; further oracles update
    # close_oracle for W2). When the background settle for W1 finally
    # writes, it must use W1's decision_id even though _state.window_ts
    # is now WINDOW_TS_NEXT.
    records = [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # rolls W1 → background settle
        # W2 mutations during the in-flight settle:
        _oracle(WINDOW_TS_NEXT + 10, 99999.00),  # corrupt close_oracle
        _spot(WINDOW_TS_NEXT + 20, 99999.00),
    ]
    feed = _FakeFeed(records, delay_per_record_s=0.05)
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    transport = _gamma_resolves("UP", sleep_s=0.4)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=2.0,
        instant_settle_interval_s=0.05,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fired = [e for e in events if e["kind"] == "fired"]
    settled = [e for e in events if e["kind"] == "settled"]
    assert len(fired) == 1
    assert len(settled) == 1
    # Snapshot semantics: the settled record references the W1 decision
    # and the W1 oracle samples, NOT the corrupted W2 99999.00 oracle.
    assert settled[0]["decision_id"] == fired[0]["decision_id"]
    assert settled[0]["window_ts"] == WINDOW_TS
    assert settled[0]["open_oracle"] == 67400.00
    assert settled[0]["close_oracle"] == 67500.00  # NOT 99999.00 — that's W2

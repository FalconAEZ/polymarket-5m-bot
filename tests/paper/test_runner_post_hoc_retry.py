"""Tests for the post-hoc gamma re-resolution background task.

After the chainlink-local-fallback writes a `settled` record, the runner
schedules a background task that polls gamma a few minutes later. If
gamma's truth disagrees with the recorded chainlink resolution, a
`settled_correction` record is appended. Per phase prompt
phase-prompts/phase-5-settle-resolution-bug-2026-05-11.txt and the
2026-05-10 audit (chainlink-local disagrees with gamma on ~33% of windows).

Invariants verified here:
  1. Correction fires when chainlink-fallback wrote one resolution and
     gamma later returns the opposite.
  2. NO correction is written when gamma agrees with chainlink-fallback.
  3. NO correction is written when gamma never resolves (gracefully gives up).
  4. NO correction (and no retry task at all) when the kill-switch is off.
  5. Under feed-burst load, scheduling many post-hoc retries does not
     starve the main loop -- the queue-doesn't-overflow lesson from
     ~/.claude/projects/.../memory/feedback_test_under_load.md applied
     to the new background task class.
  6. Shutdown awaits in-flight retries so the correction record is not
     lost on stop.
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


class _FakeFeed:
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
    name: str = "fake"

    def __init__(self, decision: Decision) -> None:
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


def _records_window_with_close() -> list[Record]:
    """Window 1: open, fire, close + roll-over to W2 to trigger settle."""
    return [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),  # chainlink-local says UP
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # roll -> W1 settle starts
    ]


def _payload(res: str | None) -> Any:
    if res is None:
        return []
    return [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["1", "0"] if res == "UP" else ["0", "1"],
                }
            ]
        }
    ]


def _gamma_transport_resolves_after(
    *, after_s: float, resolution: str | None
) -> httpx.MockTransport:
    """Returns empty until `after_s` seconds have elapsed since transport
    creation, then returns the given resolution. Models the production
    pattern: instant-settle's short timeout returns empty (chainlink
    fallback fires); the post-hoc retry, scheduled for later, gets the
    real answer."""
    t0 = time.monotonic()

    def handler(request: httpx.Request) -> httpx.Response:
        if time.monotonic() - t0 < after_s:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=_payload(resolution))

    return httpx.MockTransport(handler)


# ----------------------------------------------------------------------
# Test 1 — correction fires when chainlink and gamma disagree.
# Chainlink-local: open=67400, close=67500 -> UP. Gamma later returns
# DOWN. The runner should write a settled_correction with resolution
# DOWN and a recomputed pnl.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hoc_retry_writes_correction_when_truths_disagree(
    tmp_path: Path,
) -> None:
    feed = _FakeFeed(_records_window_with_close())
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # Instant fails (timeout) -> chainlink path -> resolution_source =
    # "chainlink-local-fallback". Post-hoc gamma returns DOWN (disagrees
    # with chainlink's UP).
    # Gamma stays empty for 0.5s (so instant-settle's 0.2s timeout falls
    # through to chainlink), then resolves DOWN (disagrees with chainlink's UP).
    transport = _gamma_transport_resolves_after(after_s=0.5, resolution="DOWN")
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.2,  # short -> falls through to chainlink
        instant_settle_interval_s=0.05,
        post_hoc_gamma_retry_enabled=True,
        # Wait until the transport has flipped to DOWN before the first poll.
        post_hoc_retry_initial_delay_s=0.6,
        post_hoc_retry_interval_s=0.05,
        post_hoc_retry_max_attempts=5,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    settled = [e for e in events if e["kind"] == "settled"]
    corrections = [e for e in events if e["kind"] == "settled_correction"]
    assert len(settled) == 1
    assert settled[0]["resolution"] == "UP"
    assert settled[0]["resolution_source"] == "chainlink-local-fallback"
    assert len(corrections) == 1
    c = corrections[0]
    assert c["decision_id"] == settled[0]["decision_id"]
    assert c["original_resolution"] == "UP"
    assert c["corrected_resolution"] == "DOWN"
    # Side was UP, corrected resolution DOWN -> pnl is the loss.
    assert c["corrected_pnl_usd"] < 0
    assert c["original_pnl_usd"] > 0
    assert c["resolution_source"] == "polymarket-post-hoc"


# ----------------------------------------------------------------------
# Test 2 — no correction when chainlink and gamma agree.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hoc_retry_no_correction_when_truths_agree(tmp_path: Path) -> None:
    feed = _FakeFeed(_records_window_with_close())
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # Instant gamma stays empty -> chainlink path -> UP. Post-hoc retry
    # later sees UP, agrees, writes nothing.
    transport = _gamma_transport_resolves_after(after_s=0.5, resolution="UP")
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.2,
        instant_settle_interval_s=0.05,
        post_hoc_gamma_retry_enabled=True,
        post_hoc_retry_initial_delay_s=0.6,
        post_hoc_retry_interval_s=0.05,
        post_hoc_retry_max_attempts=5,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    corrections = [e for e in events if e["kind"] == "settled_correction"]
    assert (
        corrections == []
    ), "post-hoc retry must not write a correction when gamma agrees with chainlink"


# ----------------------------------------------------------------------
# Test 3 — graceful give-up when gamma never resolves during the retry
# window. No correction record; no exception propagated.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hoc_retry_gives_up_when_gamma_never_resolves(tmp_path: Path) -> None:
    feed = _FakeFeed(_records_window_with_close())
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # Never resolves -- transport always returns empty (after_s very large).
    transport = _gamma_transport_resolves_after(after_s=999.0, resolution="UP")
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.1,
        instant_settle_interval_s=0.05,
        post_hoc_gamma_retry_enabled=True,
        post_hoc_retry_initial_delay_s=0.05,
        post_hoc_retry_interval_s=0.02,
        post_hoc_retry_max_attempts=3,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    corrections = [e for e in events if e["kind"] == "settled_correction"]
    assert corrections == []


# ----------------------------------------------------------------------
# Test 4 — kill-switch off => no retry task scheduled, no correction.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hoc_retry_disabled_skips_task_entirely(tmp_path: Path) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    feed = _FakeFeed(_records_window_with_close())
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        # instant-settle stays on so we hit the chainlink-fallback path,
        # but post-hoc retry is OFF so no extra gamma calls fire.
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.1,
        instant_settle_interval_s=0.05,
        post_hoc_gamma_retry_enabled=False,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    corrections = [e for e in events if e["kind"] == "settled_correction"]
    assert corrections == []
    # Instant-settle made some gamma calls during its short timeout, but
    # the post-hoc retry path must add ZERO additional calls. We can't
    # easily distinguish source by inspecting the mock; instead assert no
    # leftover task.
    assert not runner._pending_post_hoc_retries  # type: ignore[attr-defined]


# ----------------------------------------------------------------------
# Test 5 — main loop keeps draining the queue while a post-hoc retry is
# in flight (queue-doesn't-overflow). Mirrors the
# test_main_loop_processes_records_during_slow_settle pattern from
# test_runner_settle_background.py applied to the new task class.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_hoc_retry_does_not_starve_main_loop(tmp_path: Path) -> None:
    burst = [_spot(WINDOW_TS_NEXT + 5 + i, 67510.00 + i, ns_offset=i) for i in range(80)]
    records = [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),
        _oracle(WINDOW_TS + 250, 67500.00),
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # roll -> W1 settle starts
        *burst,
    ]
    feed = _FakeFeed(records, delay_per_record_s=0.005)  # 80 * 5ms = 400ms

    # Slow gamma reply on every call -- if the post-hoc task were inline
    # in the main loop it would block for ~600ms per call. With the fix
    # it runs in to_thread and the main loop keeps consuming.
    def handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.6)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)

    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        queue_size=8,  # tight bound: a blocked main loop would overflow
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.05,  # fail fast so we hit the chainlink path
        instant_settle_interval_s=0.02,
        post_hoc_gamma_retry_enabled=True,
        post_hoc_retry_initial_delay_s=0.02,
        post_hoc_retry_interval_s=0.05,
        post_hoc_retry_max_attempts=2,
    )
    await runner.run()

    assert runner.dropped_records_total == 0, (
        f"main loop blocked during post-hoc retry — "
        f"{runner.dropped_records_total} records dropped"
    )


# ----------------------------------------------------------------------
# Test 6 — shutdown awaits in-flight post-hoc retries, so a stop signal
# while a retry is sleeping does not lose the eventual correction.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_awaits_in_flight_post_hoc_retry(tmp_path: Path) -> None:
    feed = _FakeFeed(_records_window_with_close())
    strategy = _FakeStrategy(_decision_at(WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    # Gamma stays empty for 0.4s (instant-settle's 0.2s timeout falls
    # through to chainlink), then resolves DOWN. Post-hoc retry initial
    # delay 0.5s ensures the retry is still sleeping when stop() fires.
    transport = _gamma_transport_resolves_after(after_s=0.4, resolution="DOWN")
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.2,
        instant_settle_interval_s=0.05,
        post_hoc_gamma_retry_enabled=True,
        # 0.5s initial delay -- run() returns first, then shutdown's
        # await must hold open for the retry to wake up + poll.
        post_hoc_retry_initial_delay_s=0.5,
        post_hoc_retry_interval_s=0.05,
        post_hoc_retry_max_attempts=5,
    )

    stop = asyncio.Event()

    async def trigger_stop() -> None:
        # Enough for the main run() to process records, hit the window
        # rollover, run the (failing) instant-settle, write chainlink
        # settled, schedule the post-hoc task -- but leave the task
        # itself still sleeping in initial_delay_s when stop fires.
        await asyncio.sleep(0.3)
        stop.set()
        runner.stop()

    await asyncio.gather(runner.run(stop=stop), trigger_stop())

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    corrections = [e for e in events if e["kind"] == "settled_correction"]
    assert len(corrections) == 1
    assert corrections[0]["corrected_resolution"] == "DOWN"

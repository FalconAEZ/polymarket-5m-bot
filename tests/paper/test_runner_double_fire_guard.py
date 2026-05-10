"""Tests for cross-restart double-fire guard.

Operator-observed bug 2026-05-10 03:55 UTC: bot was restarted at
03:59:44 UTC. Window 1778385300 (opened 03:55:00) had already been
fired by the OLD bot at 03:55:00 (DOWN, tier 85-100%, limit 0.990).
The NEW bot started with fresh `_state` and didn't know about the
prior fire. When the strategy emitted a new candidate at 03:59:46
(UP, tier 30-50%, limit 0.430), the runner accepted it. Net result:
two opposing bets on the same 5m market, guaranteed -$5 loss on
whichever side resolves wrong.

Orphan recovery only handles PAST windows. The CURRENT window is
legitimately pending — orphan recovery (correctly) skips it. Fix:
PaperRunner._prime_active_window_state() reads the decision_log for
fires in the active 5m window and pre-populates `_state` so
_on_decision's duplicate-fire guard rejects the new candidate.
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
    return sorted(root.glob("*.jsonl"))


ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32

# Pick the same window the bug landed in: 1778385300 (2026-05-10 03:55 UTC).
ACTIVE_WINDOW_TS = 1778385300
ACTIVE_WINDOW_OPEN_NS = ACTIVE_WINDOW_TS * 1_000_000_000


def _now_ns_inside_active_window() -> int:
    """Clock that returns a time INSIDE ACTIVE_WINDOW_TS (T+150s),
    so active_window_ts(now_s) == ACTIVE_WINDOW_TS."""
    return (ACTIVE_WINDOW_TS + 150) * 1_000_000_000


def _seed_prior_fire_in_log(
    log_root: Path,
    *,
    decision_id: str = "prior-fire-aaa",
    side: str = "DOWN",
    price_limit: float = 0.990,
    ts_ns: int = ACTIVE_WINDOW_OPEN_NS,
) -> None:
    """Write a `fired` record for the active window (no settled match)."""
    fired = {
        "kind": "fired",
        "decision_id": decision_id,
        "window_ts": ACTIVE_WINDOW_TS,
        "decision_ts_ns": ts_ns,
        "asset_id": ASSET_DOWN if side == "DOWN" else ASSET_UP,
        "side": side,
        "size_usd": 5.0,
        "price_limit": price_limit,
        "ttl_s": 30,
        "rationale": f"strategy=stub side={side}",
        "snapshot": {},
        "composite_pct": None,
        "fill": None,
    }
    from datetime import UTC, datetime

    date = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")
    log_root.mkdir(parents=True, exist_ok=True)
    path = log_root / f"{date}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fired, separators=(",", ":")) + "\n")


class _FakeFeed:
    """Yields records produced after the active window is open. Drives
    the runner through one event sequence in the active window."""

    name: str = "fake"

    def __init__(self, records: list[Record]) -> None:
        self._records = records
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


def _spot(ts_offset_s: int, price: float) -> Record:
    ts_s = ACTIVE_WINDOW_TS + ts_offset_s
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000,
        source="binance",
        payload={"p": str(price), "T": ts_s * 1000},
    )


def _book(ts_offset_s: int, asset_id: str, *, best_ask: float = 0.50) -> Record:
    ts_s = ACTIVE_WINDOW_TS + ts_offset_s
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000 + 2,
        source="polymarket",
        payload={
            "event_type": "book",
            "asset_id": asset_id,
            "bids": [{"price": str(max(0.01, best_ask - 0.02)), "size": "100"}],
            "asks": [{"price": str(best_ask), "size": "100"}],
        },
    )


class _AlwaysFireStrategy:
    """Fires UP on the first SpotTick that has a moving spot. Used to
    reproduce the post-restart double-fire behavior."""

    name = "always-fire"

    def __init__(self) -> None:
        self._fired_for_window: int | None = None

    async def on_event(self, event: MarketEvent) -> Decision | None:
        from polymarket_bot.backtest.types import BookUpdate as BU

        if isinstance(event, BU) and event.asset_id == ASSET_UP:
            window_ts = (event.ts_utc_ns // 1_000_000_000) // 300 * 300
            if self._fired_for_window == window_ts:
                return None
            self._fired_for_window = window_ts
            return Decision(
                ts_utc_ns=event.ts_utc_ns,
                asset_id=ASSET_UP,
                side="BUY",
                size_usd=5.0,
                price_limit=0.430,
                ttl_s=30,
                rationale="strategy=always-fire side=UP delta_bps=+10.0",
            )
        return None

    def reset(self) -> None:
        self._fired_for_window = None


def _resolver() -> StaticTokenSideResolver:
    return StaticTokenSideResolver(
        {
            ASSET_UP: ("UP", ACTIVE_WINDOW_TS, 1),
            ASSET_DOWN: ("DOWN", ACTIVE_WINDOW_TS, 1),
        }
    )


@pytest.mark.asyncio
async def test_runner_blocks_double_fire_when_prior_fire_exists_in_active_window(
    tmp_path: Path,
) -> None:
    """Operator's bug, codified: after a restart, if a prior fire
    exists for the active window in the decision log, the new runner
    must NOT accept a second fire from the strategy in that same
    window. This test would FAIL on the old code (no _prime_active_
    window_state); after the fix it passes by virtue of the existing
    duplicate-fire guard tripping on the primed state.

    Setup:
      1. Seed `state/decisions/<date>.jsonl` with a DOWN fire in
         ACTIVE_WINDOW_TS (no matching settled — simulates the
         bot crash mid-window).
      2. Construct a fresh PaperRunner pointed at the same log root.
      3. Drive it with events that would normally trigger an UP fire
         from the strategy.
      4. Assert: zero NEW fires landed in the log; the old DOWN fire
         is the only one present."""
    # Seed the prior fire.
    _seed_prior_fire_in_log(tmp_path, decision_id="prior-down", side="DOWN")
    # Sanity: the seeded file has exactly one fired line.
    pre_records = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    assert sum(1 for r in pre_records if r.get("kind") == "fired") == 1

    # Sequence of events DURING the active window: spot, book, second spot
    # at T+150s → strategy fires.
    feed = _FakeFeed(
        [
            _spot(5, 80_000.0),
            _book(10, ASSET_UP, best_ask=0.43),
            _book(10, ASSET_DOWN, best_ask=0.59),
            _spot(150, 80_080.0),  # would trigger another fire
        ]
    )
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=_AlwaysFireStrategy(),
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=_now_ns_inside_active_window,
    )
    await runner.run()

    # Assert: no NEW fired record was written. The seeded DOWN fire is
    # the only fire on disk for this window.
    post_records = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fires = [r for r in post_records if r.get("kind") == "fired"]
    assert len(fires) == 1, (
        f"runner wrote {len(fires)} fires; expected exactly 1 (the seeded prior). "
        "Double-fire guard didn't trip — the new runner instance fired despite "
        "an existing fire for the active window."
    )
    assert fires[0]["decision_id"] == "prior-down"
    assert fires[0]["side"] == "DOWN"


@pytest.mark.asyncio
async def test_runner_allows_fire_when_active_window_has_no_prior(tmp_path: Path) -> None:
    """Sanity: with no prior fire for the active window, the runner
    accepts a new fire as normal. Confirms the prime-state logic
    doesn't over-block."""
    feed = _FakeFeed(
        [
            _spot(5, 80_000.0),
            _book(10, ASSET_UP, best_ask=0.43),
            _book(10, ASSET_DOWN, best_ask=0.59),
            _spot(150, 80_080.0),
        ]
    )
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=_AlwaysFireStrategy(),
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=_now_ns_inside_active_window,
    )
    await runner.run()
    files = _list_jsonl(tmp_path)
    if not files:
        # No file written — that means strategy didn't fire (insufficient
        # context or runner gated). Fail loudly so we know.
        pytest.fail("runner wrote no decision log at all; strategy should have fired")
    fires = [r for r in read_jsonl(files[0]) if r.get("kind") == "fired"]
    assert len(fires) == 1, f"expected 1 fire, got {len(fires)}"
    assert fires[0]["side"] == "UP"


@pytest.mark.asyncio
async def test_runner_ignores_settled_prior_fire_when_priming(tmp_path: Path) -> None:
    """A prior fire that's already SETTLED (instant-settle resolved
    while still in same window — rare but possible) should not block
    a new fire. The prime logic only cares about UNSETTLED fires."""
    _seed_prior_fire_in_log(tmp_path, decision_id="prior-settled-aaa", side="DOWN")
    # Append a settled record for the same decision_id.
    settled = {
        "kind": "settled",
        "decision_id": "prior-settled-aaa",
        "window_ts": ACTIVE_WINDOW_TS,
        "settled_ts_ns": ACTIVE_WINDOW_OPEN_NS + 60 * 10**9,
        "open_oracle": None,
        "close_oracle": None,
        "resolution": "DOWN",
        "fill_at_settle": None,
        "pnl_usd": 5.0,
    }
    path = _list_jsonl(tmp_path)[0]
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(settled, separators=(",", ":")) + "\n")

    # NOTE: in practice the runner would refuse to fire twice in the
    # same window via _state.settled_fill being set after the first
    # fire's natural settlement. But after a restart, _state is fresh.
    # The prime should NOT pre-populate from a settled fire (it's done).
    feed = _FakeFeed(
        [
            _spot(5, 80_000.0),
            _book(10, ASSET_UP, best_ask=0.43),
            _book(10, ASSET_DOWN, best_ask=0.59),
            _spot(150, 80_080.0),
        ]
    )
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=_AlwaysFireStrategy(),
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=_now_ns_inside_active_window,
    )
    await runner.run()
    fires = [r for r in read_jsonl(_list_jsonl(tmp_path)[0]) if r.get("kind") == "fired"]
    # The prior fire + the new fire = 2 entries (because the prior was
    # settled; primed state doesn't block).
    assert len(fires) == 2

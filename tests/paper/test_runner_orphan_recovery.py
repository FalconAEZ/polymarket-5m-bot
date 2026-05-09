"""Tests for PaperRunner startup-time orphan-fire recovery.

Per Phase 11.A.2 hand-off Item 2.2 — when bot is restarted between a
fire and the closing window's settle (e.g., during a deploy), the new
runner has fresh `_state` so the close-side boundary returns early
(decision_id is None) and never writes a settled record. The orphan
sits unresolved forever; the dashboard's resolver_loop only corrects
EXISTING settled records, it doesn't synthesize them.

Concrete example: 2026-05-09 21:10 fire → bot restarted 21:13:50 →
window closed 21:15:00 with no settle. After this test's fix, the
runner's startup pass scans for orphans and post-hoc resolves them
via Polymarket Gamma, writing a settled record marked
resolution_source="polymarket-recovery".

Tests verify:
  1. Pre-existing orphan gets a synthesized settle on startup.
  2. The recovery is idempotent — a second startup does not double-write.
  3. With orphan_recovery_enabled=False the kill-switch suppresses recovery.
  4. Recovery skips orphans whose closing window is still in the future.
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
from polymarket_bot.feeds.protocols import Feed, Health, Record


def _list_jsonl(root: Path) -> list[Path]:
    return sorted(root.glob("*.jsonl"))


ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32

# Pick a fixed window in the past so active_window_ts(now_s) > orphan
# window_ts at test-time. WINDOW_TS is 2025-11-07 17:55 UTC; "now" in
# the test is set well after that via clock_ns.
WINDOW_TS = 1_762_540_500
WINDOW_TS_NEXT = WINDOW_TS + 300


class _StubFeed:
    """Feed that yields nothing. Used when we just want startup to run
    and exit; orphan recovery is a startup-time pass and doesn't need
    live records."""

    name: str = "stub"

    def __init__(self) -> None:
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
        # Yield zero records — feed completes immediately, queue gets a
        # sentinel None, runner finishes startup and exits cleanly.
        if False:
            yield  # type: ignore[unreachable]


_: type[Feed] = _StubFeed


def _resolver() -> StaticTokenSideResolver:
    return StaticTokenSideResolver(
        {
            ASSET_UP: ("UP", WINDOW_TS, 1),
            ASSET_DOWN: ("DOWN", WINDOW_TS, 1),
        }
    )


class _NoFireStrategy:
    name: str = "no-fire"

    async def on_event(self, event: Any) -> Any:
        return None


def _seed_orphan_fire(
    log_root: Path,
    *,
    decision_id: str = "orphan-1",
    window_ts: int = WINDOW_TS,
    side: str = "UP",
) -> None:
    """Write a `fired` record to log_root/<date>.jsonl with no matching
    settled. Mirrors the on-disk schema produced by record_fired."""
    decision_ts_ns = window_ts * 1_000_000_000 + 5_000_000_000
    fired = {
        "kind": "fired",
        "decision_id": decision_id,
        "window_ts": window_ts,
        "decision_ts_ns": decision_ts_ns,
        "asset_id": ASSET_UP,
        "side": side,
        "size_usd": 5.0,
        "price_limit": 0.55,
        "ttl_s": 60,
        "rationale": "composite=+0.612pct ttl=60s side=UP",
        "snapshot": {"spot_now": 67400.0},
        "composite_pct": 0.612,
        "fill": {
            "ts_utc_ns": decision_ts_ns,
            "asset_id": ASSET_UP,
            "size_filled": 9.98,
            "price_filled": 0.50,
            "fee_usd": 0.001,
        },
    }
    # Date the file by the decision's UTC date so the runner's lookback
    # finds it. Using the ts_utc_ns of the fire keeps the file path
    # consistent with what record_fired would have produced.
    from datetime import UTC, datetime

    date_str = datetime.fromtimestamp(decision_ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")
    path = log_root / f"{date_str}.jsonl"
    log_root.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fired, separators=(",", ":")) + "\n")


def _gamma_resolves(resolution: str) -> httpx.MockTransport:
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
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _now_ns_well_past_orphan() -> int:
    """A clock_ns that returns a timestamp comfortably after the orphan
    window's close, so active_window_ts(now_s) > orphan.window_ts."""
    return (WINDOW_TS + 3600) * 1_000_000_000  # 1 hour after orphan window


def _build_runner(
    *,
    log_root: Path,
    transport: httpx.MockTransport | None,
    orphan_recovery_enabled: bool = True,
    lookback_days: int = 1,
) -> PaperRunner:
    log = DecisionLog(root=log_root)
    return PaperRunner(
        feeds=[_StubFeed()],
        strategy=_NoFireStrategy(),
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=_now_ns_well_past_orphan,
        instant_settle_enabled=False,  # not exercised here
        gamma_client=httpx.Client(transport=transport) if transport is not None else None,
        orphan_recovery_enabled=orphan_recovery_enabled,
        orphan_recovery_lookback_days=lookback_days,
    )


# ----------------------------------------------------------------------
# Test 1 — pre-existing orphan gets a synthesized settle on startup.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_writes_synthesized_settle_for_orphan(tmp_path: Path) -> None:
    _seed_orphan_fire(tmp_path, decision_id="orphan-aaa", window_ts=WINDOW_TS, side="UP")
    runner = _build_runner(log_root=tmp_path, transport=_gamma_resolves("UP"))
    await runner.run()

    files = _list_jsonl(tmp_path)
    assert len(files) == 1
    events = list(read_jsonl(files[0]))
    fired = [e for e in events if e["kind"] == "fired"]
    settled = [e for e in events if e["kind"] == "settled"]

    assert len(fired) == 1
    assert len(settled) == 1
    assert settled[0]["decision_id"] == "orphan-aaa"
    assert settled[0]["window_ts"] == WINDOW_TS
    assert settled[0]["resolution"] == "UP"
    assert settled[0]["resolution_source"] == "polymarket-recovery"
    # Side UP, resolution UP, fill price 0.50, size 9.98 → won → pnl > 0
    assert settled[0]["pnl_usd"] > 0


# ----------------------------------------------------------------------
# Test 2 — idempotent: a second startup does not double-write.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_is_idempotent(tmp_path: Path) -> None:
    _seed_orphan_fire(tmp_path, decision_id="orphan-bbb", side="UP")

    # First startup recovers.
    runner1 = _build_runner(log_root=tmp_path, transport=_gamma_resolves("UP"))
    await runner1.run()

    # Second startup should NOT add another settled record.
    runner2 = _build_runner(log_root=tmp_path, transport=_gamma_resolves("UP"))
    await runner2.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    settled = [e for e in events if e["kind"] == "settled"]
    assert len(settled) == 1, (
        f"orphan recovery wrote {len(settled)} settled records; "
        "expected exactly one (idempotency violated)"
    )


# ----------------------------------------------------------------------
# Test 3 — kill-switch: orphan_recovery_enabled=False prevents recovery.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_disabled_writes_nothing(tmp_path: Path) -> None:
    _seed_orphan_fire(tmp_path, decision_id="orphan-ccc", side="DOWN")
    runner = _build_runner(
        log_root=tmp_path,
        transport=_gamma_resolves("DOWN"),
        orphan_recovery_enabled=False,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    fired = [e for e in events if e["kind"] == "fired"]
    settled = [e for e in events if e["kind"] == "settled"]
    assert len(fired) == 1
    # With recovery disabled, the orphan stays orphan.
    assert len(settled) == 0


# ----------------------------------------------------------------------
# Test 4 — recovery skips orphans whose closing window is still in the
# future (the bot legitimately hasn't gotten to settle yet).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_skips_future_window_orphans(tmp_path: Path) -> None:
    # Seed an orphan whose window_ts > current_window. Use clock_ns that
    # places "now" BEFORE the orphan's window, so the window is future.
    future_window = WINDOW_TS_NEXT  # 5 min after WINDOW_TS

    def early_clock() -> int:
        # "now" is 3 minutes after WINDOW_TS — i.e., MID-future_window's
        # opening period. active_window_ts(now_s) == WINDOW_TS, future
        # window hasn't opened yet.
        return (WINDOW_TS + 180) * 1_000_000_000

    _seed_orphan_fire(tmp_path, decision_id="orphan-future", window_ts=future_window, side="UP")
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[_StubFeed()],
        strategy=_NoFireStrategy(),
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=early_clock,
        gamma_client=httpx.Client(transport=_gamma_resolves("UP")),
        orphan_recovery_enabled=True,
    )
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    settled = [e for e in events if e["kind"] == "settled"]
    # Future-window orphan must NOT be recovered — it's still legitimately
    # pending (the bot would settle it on the natural close boundary).
    assert len(settled) == 0


# ----------------------------------------------------------------------
# Test 5 — when gamma client is None, recovery skips entirely without
# raising, even with the flag enabled. Defensive: an operator could
# enable orphan_recovery in env but forget to wire gamma_client; we
# should fail gracefully.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_no_gamma_client_skips_safely(tmp_path: Path) -> None:
    _seed_orphan_fire(tmp_path, decision_id="orphan-no-client", side="UP")
    runner = _build_runner(
        log_root=tmp_path,
        transport=None,  # gamma_client = None
        orphan_recovery_enabled=True,
    )
    # Must complete without raising.
    await runner.run()

    events = list(read_jsonl(_list_jsonl(tmp_path)[0]))
    settled = [e for e in events if e["kind"] == "settled"]
    assert len(settled) == 0  # nothing recovered, nothing crashed


# Use time only to suppress flake; real test logic doesn't depend on it.
_ = time

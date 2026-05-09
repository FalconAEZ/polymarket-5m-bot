"""Tests for PaperRunner instant-settle path (Polymarket Gamma poll).

Per design/instant_settlement.md. Drives the same FakeFeed pattern as
test_runner.py, but injects a gamma httpx.Client (MockTransport) to
control the Polymarket-side resolution. Asserts:
  * When gamma returns UP/DOWN, settled record uses it +
    resolution_source="polymarket"; oracle path is bypassed
  * When gamma times out, falls back to actual_resolution() +
    resolution_source="chainlink-local-fallback"
  * When instant_settle_enabled=False, gamma is never called
"""

from __future__ import annotations

import asyncio
import json
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


def _spot(ts_s: int, price: float) -> Record:
    return _record(
        ts_utc_ns=ts_s * 1_000_000_000,
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
    """Returns one Decision when fed a matching book event."""

    name: str = "fake"

    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self._fired = False

    def reset(self) -> None:
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


def _decision_in_window(*, decision_ts_s: int) -> Decision:
    return Decision(
        ts_utc_ns=decision_ts_s * 1_000_000_000,
        asset_id=ASSET_UP,
        side="BUY",
        size_usd=5.0,
        price_limit=0.55,
        ttl_s=60,
        rationale="composite=+0.612pct ttl=60s side=UP",
    )


def _records_with_window_rollover() -> list[Record]:
    """Standard record sequence: spot+oracle (open), book (decision fires),
    oracle update (close), spot at next window (settles current)."""
    return [
        _spot(WINDOW_TS + 5, 67400.00),
        _oracle(WINDOW_TS + 6, 67400.00),
        _book(WINDOW_TS + 8, ASSET_UP, best_ask=0.50),
        _book(WINDOW_TS + 12, ASSET_UP, best_ask=0.50),  # FakeStrategy fires here
        _oracle(WINDOW_TS + 250, 67500.00),  # Chainlink says UP wins
        _spot(WINDOW_TS_NEXT + 1, 67510.00),  # rolls window over -> settles
    ]


def _gamma_transport_returns(resolution: str) -> httpx.MockTransport:
    """Gamma always returns the given UP/DOWN resolution on the first call."""
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


def _gamma_transport_never_resolves() -> httpx.MockTransport:
    """Gamma always returns empty payload (never resolved)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_instant_settle_uses_polymarket_when_gamma_resolves(
    tmp_path: Path,
) -> None:
    """Gamma says DOWN even though Chainlink would have said UP -> Gamma wins."""
    feed = _FakeFeed(_records_with_window_rollover())
    strategy = _FakeStrategy(_decision_in_window(decision_ts_s=WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    transport = _gamma_transport_returns("DOWN")
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
        instant_settle_interval_s=0.1,
    )
    await runner.run()

    settled = next(e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled")
    assert settled["resolution"] == "DOWN"  # Gamma's truth, NOT Chainlink's UP
    assert settled["resolution_source"] == "polymarket"
    # Side was UP, resolution DOWN -> we lost
    assert settled["pnl_usd"] < 0


@pytest.mark.asyncio
async def test_instant_settle_falls_back_to_chainlink_on_timeout(
    tmp_path: Path,
) -> None:
    """Gamma never resolves -> falls back to actual_resolution() + marks source."""
    feed = _FakeFeed(_records_with_window_rollover())
    strategy = _FakeStrategy(_decision_in_window(decision_ts_s=WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    transport = _gamma_transport_never_resolves()
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=True,
        gamma_client=httpx.Client(transport=transport),
        instant_settle_timeout_s=0.3,  # short timeout for test speed
        instant_settle_interval_s=0.05,
    )
    await runner.run()

    settled = next(e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled")
    # Chainlink path: open=67400, close=67500 -> UP
    assert settled["resolution"] == "UP"
    assert settled["resolution_source"] == "chainlink-local-fallback"
    # Side was UP, resolution UP -> we won
    assert settled["pnl_usd"] > 0


@pytest.mark.asyncio
async def test_instant_settle_disabled_skips_gamma_entirely(tmp_path: Path) -> None:
    """instant_settle_enabled=False -> gamma client never used; legacy
    behavior preserved (no resolution_source field even if Chainlink fires)."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=_gamma_transport_returns("DOWN"))

    transport = httpx.MockTransport(handler)
    feed = _FakeFeed(_records_with_window_rollover())
    strategy = _FakeStrategy(_decision_in_window(decision_ts_s=WINDOW_TS + 12))
    log = DecisionLog(root=tmp_path)
    runner = PaperRunner(
        feeds=[feed],
        strategy=strategy,
        side_resolver=_resolver(),
        shadow_book=ShadowBook(),
        decision_log=log,
        clock_ns=lambda: WINDOW_TS_NEXT * 1_000_000_000 + 5_000_000_000,
        instant_settle_enabled=False,  # OFF
        gamma_client=httpx.Client(transport=transport),
    )
    await runner.run()

    settled = next(e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled")
    # Chainlink path was used; gamma never called.
    assert settled["resolution"] == "UP"
    assert "resolution_source" not in settled  # legacy behavior, no field
    assert call_count == 0  # never hit gamma


@pytest.mark.asyncio
async def test_instant_settle_default_off_when_no_kwargs(tmp_path: Path) -> None:
    """Default constructor (no instant-settle kwargs) -> legacy behavior."""
    feed = _FakeFeed(_records_with_window_rollover())
    strategy = _FakeStrategy(_decision_in_window(decision_ts_s=WINDOW_TS + 12))
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

    settled = next(e for e in read_jsonl(_list_jsonl(tmp_path)[0]) if e["kind"] == "settled")
    assert settled["resolution"] == "UP"
    assert "resolution_source" not in settled

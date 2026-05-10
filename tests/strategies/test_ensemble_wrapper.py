"""Tests for polymarket_bot.strategies.ensemble_wrapper.EnsembleWrapper.

Per design/phase-5-llm-ensemble.md (Phase 5.0). EnsembleWrapper is the
operator-approved bridge between an arbitrary base Strategy (typically
SpotAwareStrategyV2 in either tight or wide-fire mode) and the existing
3-specialist + Sonnet meta agents. It supports three modes:

  off    — bypasses the ensemble; returns the base strategy's verdict
  shadow — runs the ensemble for logging only; base verdict still drives
  gate   — only fires when both base AND meta agree on the same side

Tests cover the gating logic + mode behavior + cold-start + log writing.
No real Anthropic calls — FakeAdapter pattern reused from
tests/agents/conftest.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from polymarket_bot.agents.protocol import (
    AgentContext,
    AgentVote,
    MetaDecision,
)
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    MarketEvent,
    OracleUpdate,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.ensemble_wrapper import EnsembleWrapper

WINDOW_TS = 1_715_000_100
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "0x" + "11" * 32
TOKEN_DOWN = "0x" + "22" * 32


# ----------------------------------------------------------------------
# Stubs — base strategy + agents (no real Anthropic)
# ----------------------------------------------------------------------


class _StubBaseStrategy:
    """Always emits a Decision when fed the right SpotTick (one-shot)."""

    name = "stub-base"

    def __init__(self, side: str = "UP") -> None:
        self._fired = False
        self._side = side

    def reset(self) -> None:
        self._fired = False

    async def on_event(self, event: MarketEvent) -> Decision | None:
        if self._fired:
            return None
        if isinstance(event, SpotTick) and event.ts_utc_ns >= WINDOW_OPEN_NS + 30 * 10**9:
            self._fired = True
            return Decision(
                ts_utc_ns=event.ts_utc_ns,
                asset_id=TOKEN_UP if self._side == "UP" else TOKEN_DOWN,
                side="BUY",
                size_usd=5.0,
                price_limit=0.55,
                ttl_s=60,
                rationale=f"strategy=stub side={self._side} delta_bps=+10.0",
            )
        return None


class _StubAgent:
    """Returns canned AgentVote (or None) on each .vote() call."""

    def __init__(self, name: str, vote: AgentVote | None) -> None:
        self.name = name
        self.model = "stub"
        self._vote = vote

    async def vote(self, ctx: AgentContext) -> AgentVote | None:
        return self._vote


class _StubMeta:
    """Returns canned MetaDecision (or None) on each .decide() call."""

    def __init__(self, decision: MetaDecision | None) -> None:
        self.name = "meta-stub"
        self.model = "sonnet-stub"
        self._decision = decision

    async def decide(self, ctx: AgentContext, votes: dict[str, AgentVote]) -> MetaDecision | None:
        return self._decision


def _spot(price: float, ts_offset_s: int) -> SpotTick:
    return SpotTick(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 10**9,
        source="binance",
        price=price,
    )


def _oracle(price: float, ts_offset_s: int) -> OracleUpdate:
    return OracleUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 10**9,
        price=price,
        round_id=ts_offset_s,
        updated_at_s=WINDOW_TS + ts_offset_s,
    )


def _book(asset_id: str, side: str, ask: float, ts_offset_s: int) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 10**9,
        asset_id=asset_id,
        side=side,  # type: ignore[arg-type]
        best_bid=max(0.01, ask - 0.02),
        best_ask=ask,
        bid_size_top=100.0,
        ask_size_top=100.0,
    )


def _open() -> WindowBoundary:
    return WindowBoundary(ts_utc_ns=WINDOW_OPEN_NS, window_ts=WINDOW_TS, kind="open")


def _list_jsonl(root: Path) -> list[Path]:
    """Sync helper so async tests don't trip ASYNC240 (pathlib in async)."""
    return sorted(root.glob("*.jsonl"))


def _read_jsonl_lines(path: Path) -> list[dict[str, Any]]:
    """Sync helper for reading the ensemble log in tests."""
    return [json.loads(line) for line in path.read_text().strip().splitlines()]


async def _drive(wrapper: EnsembleWrapper) -> Decision | None:
    """Feed the wrapper a complete window's worth of events. Returns the
    Decision (if any) emitted at the firing SpotTick at T+30s."""
    await wrapper.on_event(_open())
    await wrapper.on_event(_spot(80_000.0, 1))
    await wrapper.on_event(_oracle(79_990.0, 2))
    await wrapper.on_event(_book(TOKEN_UP, "UP", 0.55, 3))
    await wrapper.on_event(_book(TOKEN_DOWN, "DOWN", 0.47, 3))
    return await wrapper.on_event(_spot(80_080.0, 30))


# ----------------------------------------------------------------------
# Mode tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_mode_passes_base_verdict_through(tmp_path: Path) -> None:
    """mode=off: ensemble is never invoked; base's verdict is the result."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(),
        specialists=[_StubAgent("orderbook", None)],  # would return None if called
        meta=_StubMeta(None),
        mode="off",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is not None
    assert "side=UP" in decision.rationale
    # No log file should be written (ensemble never invoked).
    assert _list_jsonl(tmp_path) == []


@pytest.mark.asyncio
async def test_shadow_mode_logs_but_does_not_gate(tmp_path: Path) -> None:
    """mode=shadow: ensemble votes are logged; base verdict still drives."""
    # Meta says ABSTAIN — but in shadow mode the base fire still happens.
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", AgentVote(side="UP", confidence=0.8, rationale="o-up")),
            _StubAgent("oracle_gap", AgentVote(side="UP", confidence=0.7, rationale="og-up")),
            _StubAgent("momentum", AgentVote(side="UP", confidence=0.6, rationale="m-up")),
        ],
        meta=_StubMeta(
            MetaDecision(action="ABSTAIN", side=None, confidence=0.5, rationale="meta-no")
        ),
        mode="shadow",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is not None, "shadow mode must NOT block base's fire"
    log_files = _list_jsonl(tmp_path)
    assert len(log_files) == 1
    payloads = _read_jsonl_lines(log_files[0])
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["kind"] == "ensemble_vote"
    assert payload["mode"] == "shadow"
    assert payload["meta"]["action"] == "ABSTAIN"
    assert payload["votes"]["orderbook"]["side"] == "UP"


@pytest.mark.asyncio
async def test_gate_mode_blocks_when_meta_abstains(tmp_path: Path) -> None:
    """mode=gate: meta=ABSTAIN drops the base's fire."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", AgentVote(side="UP", confidence=0.8, rationale="o")),
            _StubAgent("oracle_gap", AgentVote(side="UP", confidence=0.7, rationale="og")),
        ],
        meta=_StubMeta(
            MetaDecision(action="ABSTAIN", side=None, confidence=0.5, rationale="meta-abstain")
        ),
        mode="gate",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is None
    # Log still records the abstain.
    payload = _read_jsonl_lines(_list_jsonl(tmp_path)[0])[0]
    assert payload["meta"]["action"] == "ABSTAIN"


@pytest.mark.asyncio
async def test_gate_mode_passes_when_meta_fires_same_side(tmp_path: Path) -> None:
    """mode=gate: meta=FIRE on same side as base passes through."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", AgentVote(side="UP", confidence=0.8, rationale="o")),
            _StubAgent("oracle_gap", AgentVote(side="UP", confidence=0.7, rationale="og")),
        ],
        meta=_StubMeta(
            MetaDecision(action="FIRE", side="UP", confidence=0.85, rationale="meta-up")
        ),
        mode="gate",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is not None
    assert "side=UP" in decision.rationale


@pytest.mark.asyncio
async def test_gate_mode_blocks_when_meta_disagrees_on_side(tmp_path: Path) -> None:
    """mode=gate: base wants UP but meta=FIRE on DOWN → abstain. We never
    flip the base's chosen side; a side-mismatch is grounds to skip the
    fire entirely."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", AgentVote(side="DOWN", confidence=0.8, rationale="o")),
            _StubAgent("oracle_gap", AgentVote(side="DOWN", confidence=0.7, rationale="og")),
        ],
        meta=_StubMeta(
            MetaDecision(action="FIRE", side="DOWN", confidence=0.9, rationale="meta-down")
        ),
        mode="gate",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is None


@pytest.mark.asyncio
async def test_gate_falls_through_when_too_few_specialist_votes(tmp_path: Path) -> None:
    """When fewer than MIN_VOTES_FOR_META specialists return valid votes,
    meta is not invoked. In shadow mode log + pass; in gate mode the
    safe behavior is to abstain (we can't validate the base's verdict)."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", None),  # refusal
            _StubAgent("oracle_gap", None),  # refusal
            _StubAgent("momentum", None),  # refusal
        ],
        meta=_StubMeta(MetaDecision(action="FIRE", side="UP", confidence=0.9, rationale="m")),
        mode="gate",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    # gate mode + meta never invoked = abstain. The log records meta=null.
    assert decision is None


@pytest.mark.asyncio
async def test_shadow_mode_passes_through_when_too_few_votes(tmp_path: Path) -> None:
    """Same setup but shadow mode: base verdict still wins."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[_StubAgent("orderbook", None)],
        meta=_StubMeta(MetaDecision(action="FIRE", side="UP", confidence=0.9, rationale="m")),
        mode="shadow",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    assert decision is not None  # shadow never blocks


@pytest.mark.asyncio
async def test_cold_start_logs_event_and_falls_through(tmp_path: Path) -> None:
    """When context is incomplete (no oracle / no spot history yet) the
    wrapper logs a cold-start event and lets the base verdict stand —
    even in gate mode. Don't punish ensemble for not having data."""
    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _StubAgent("orderbook", AgentVote(side="UP", confidence=0.8, rationale="o")),
            _StubAgent("oracle_gap", AgentVote(side="UP", confidence=0.7, rationale="og")),
        ],
        meta=_StubMeta(MetaDecision(action="FIRE", side="UP", confidence=0.9, rationale="m")),
        mode="gate",
        log_root=tmp_path,
    )
    # Drive WITHOUT an oracle — context can't be built.
    await wrapper.on_event(_open())
    await wrapper.on_event(_spot(80_000.0, 1))
    await wrapper.on_event(_book(TOKEN_UP, "UP", 0.55, 2))
    await wrapper.on_event(_book(TOKEN_DOWN, "DOWN", 0.47, 2))
    decision = await wrapper.on_event(_spot(80_080.0, 30))
    assert decision is not None  # cold-start does not gate
    payloads = _read_jsonl_lines(_list_jsonl(tmp_path)[0])
    assert any(p["kind"] == "ensemble_cold_start" for p in payloads)


@pytest.mark.asyncio
async def test_specialist_raise_does_not_kill_ensemble(tmp_path: Path) -> None:
    """If a specialist's .vote() raises, the wrapper logs + treats it as
    a None vote. The other specialists' votes still feed meta."""

    class _RaisingAgent:
        name = "broken"
        model = "stub"

        async def vote(self, ctx: AgentContext) -> AgentVote | None:
            raise RuntimeError("simulated specialist crash")

    wrapper = EnsembleWrapper(
        base=_StubBaseStrategy(side="UP"),
        specialists=[
            _RaisingAgent(),
            _StubAgent("oracle_gap", AgentVote(side="UP", confidence=0.7, rationale="og")),
            _StubAgent("momentum", AgentVote(side="UP", confidence=0.6, rationale="m")),
        ],
        meta=_StubMeta(MetaDecision(action="FIRE", side="UP", confidence=0.9, rationale="meta")),
        mode="gate",
        log_root=tmp_path,
    )
    decision = await _drive(wrapper)
    # 2 of 3 specialists voted → meta invoked → FIRE.
    assert decision is not None


@pytest.mark.asyncio
async def test_constructor_rejects_empty_specialists() -> None:
    with pytest.raises(ValueError, match="at least one specialist"):
        EnsembleWrapper(
            base=_StubBaseStrategy(),
            specialists=[],
            meta=_StubMeta(None),
        )


# Suppress "unused import" — these are referenced via the helper signatures
# above and the conftest pattern. Keeping them imported preserves the type
# completeness for downstream readers.
_: type = AsyncIterator
__: type = Any  # type: ignore[assignment]

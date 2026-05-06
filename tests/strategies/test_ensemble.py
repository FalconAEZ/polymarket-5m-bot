"""Tests for polymarket_bot.strategies.ensemble.EnsembleStrategy.

Drives the ensemble through synthetic MarketEvents (no Parquet, no
network, no real Anthropic). Each test wires a tiny set of fake agents
plus a fake meta-decider, then walks a window worth of events through
on_event() and asserts on the resulting Decision (or None).

Coverage:
  - threshold + TTL gate (same as DeterministicStrategy)
  - Tier-3 fallback when fewer than 2 specialists return votes
  - Meta FIRE wins when composite is below threshold
  - Composite >= threshold fires even when ensemble abstains
  - Meta side overrides composite sign when both fire
  - Fire-once-per-window
  - reset() clears state
"""

from __future__ import annotations

from typing import Literal

import pytest

from polymarket_bot.agents.protocol import (
    AgentContext,
    AgentVote,
    MetaDecision,
)
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    OracleUpdate,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.strategies.ensemble import EnsembleStrategy

WINDOW_TS = 1_715_000_100
WINDOW_OPEN_NS = WINDOW_TS * 1_000_000_000
TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


# --- fake agents --------------------------------------------------------


class _FakeSpecialist:
    """Returns a pre-canned AgentVote (or None) regardless of input."""

    def __init__(
        self,
        name: str,
        model: str = "claude-haiku-4-5",
        vote: AgentVote | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._vote = vote
        self.calls: list[AgentContext] = []

    async def vote(self, ctx: AgentContext) -> AgentVote | None:
        self.calls.append(ctx)
        return self._vote


class _FakeMeta:
    name = "meta"
    model = "claude-sonnet-4-6"

    def __init__(self, decision: MetaDecision | None) -> None:
        self._decision = decision
        self.calls: list[tuple[AgentContext, dict[str, AgentVote]]] = []

    async def decide(self, ctx: AgentContext, votes: dict[str, AgentVote]) -> MetaDecision | None:
        self.calls.append((ctx, dict(votes)))
        return self._decision


# --- fixture builders ---------------------------------------------------


def _open() -> WindowBoundary:
    return WindowBoundary(ts_utc_ns=WINDOW_OPEN_NS, window_ts=WINDOW_TS, kind="open")


def _spot(price: float, ts_offset_s: int) -> SpotTick:
    return SpotTick(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        source="binance",
        price=price,
    )


def _oracle(price: float, ts_offset_s: int) -> OracleUpdate:
    return OracleUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        price=price,
        round_id=1,
        updated_at_s=WINDOW_TS + ts_offset_s,
    )


def _book(
    side: Literal["UP", "DOWN"], asset_id: str, ask: float, ts_offset_s: int = 0
) -> BookUpdate:
    return BookUpdate(
        ts_utc_ns=WINDOW_OPEN_NS + ts_offset_s * 1_000_000_000,
        asset_id=asset_id,
        side=side,
        best_bid=ask - 0.02,
        best_ask=ask,
        bid_size_top=100.0,
        ask_size_top=100.0,
    )


def _vote(side: str, conf: float = 0.7) -> AgentVote:
    return AgentVote(side=side, confidence=conf, rationale="test")  # type: ignore[arg-type]


def _meta_fire(side: Literal["UP", "DOWN"], conf: float = 0.75) -> MetaDecision:
    return MetaDecision(action="FIRE", side=side, confidence=conf, rationale="test")


def _meta_abstain() -> MetaDecision:
    return MetaDecision(action="ABSTAIN", side=None, confidence=0.4, rationale="test")


async def _drive_window(strategy: EnsembleStrategy, *, spot_late: float) -> Decision | None:
    """Walk a typical window: open → setup ticks → fire-window event."""
    last: Decision | None = None
    for event in [
        _open(),
        _book("UP", TOKEN_UP, ask=0.55),
        _book("DOWN", TOKEN_DOWN, ask=0.46),
        _spot(60_000.0, 0),
        _oracle(60_000.0, 270),
        _spot(spot_late, 275),  # at TTL=25s
    ]:
        last = await strategy.on_event(event) or last
    return last


# --- tests --------------------------------------------------------------


async def test_meta_fire_wins_below_composite_threshold() -> None:
    """Even with composite below threshold, meta=FIRE causes the ensemble to fire."""
    specs = [
        _FakeSpecialist("orderbook", vote=_vote("UP", 0.7)),
        _FakeSpecialist("oracle_gap", vote=_vote("UP", 0.8)),
        _FakeSpecialist("momentum", vote=_vote("UP", 0.7)),
    ]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(
        specialists=specs,
        meta=meta,
        threshold_pct=10.0,  # impossibly high → composite never fires
    )
    decision = await _drive_window(strategy, spot_late=60_060.0)  # +0.1% (small composite)
    assert isinstance(decision, Decision)
    assert decision.asset_id == TOKEN_UP
    assert decision.price_limit == 0.55
    assert "meta=FIRE" in decision.rationale


async def test_composite_fires_when_ensemble_abstains() -> None:
    """High composite fires the deterministic side even if meta abstains."""
    specs = [
        _FakeSpecialist("orderbook", vote=_vote("ABSTAIN", 0.4)),
        _FakeSpecialist("oracle_gap", vote=_vote("ABSTAIN", 0.3)),
        _FakeSpecialist("momentum", vote=_vote("ABSTAIN", 0.4)),
    ]
    meta = _FakeMeta(_meta_abstain())
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=0.5)
    decision = await _drive_window(strategy, spot_late=60_600.0)  # +1% → composite ~1.0pp > 0.5
    assert isinstance(decision, Decision)
    assert decision.asset_id == TOKEN_UP
    assert "Tier-3" in decision.rationale


async def test_meta_side_overrides_composite_sign() -> None:
    """When meta fires DOWN but composite leans UP slightly, meta wins."""
    specs = [
        _FakeSpecialist("orderbook", vote=_vote("DOWN", 0.7)),
        _FakeSpecialist("oracle_gap", vote=_vote("DOWN", 0.7)),
        _FakeSpecialist("momentum", vote=_vote("DOWN", 0.7)),
    ]
    meta = _FakeMeta(_meta_fire("DOWN"))
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=10.0)
    decision = await _drive_window(strategy, spot_late=60_060.0)
    assert isinstance(decision, Decision)
    assert decision.asset_id == TOKEN_DOWN


async def test_under_two_votes_skips_meta_and_falls_back() -> None:
    """If <2 specialists vote, ensemble doesn't call meta; only composite can fire."""
    specs = [
        _FakeSpecialist("orderbook", vote=None),
        _FakeSpecialist("oracle_gap", vote=None),
        _FakeSpecialist("momentum", vote=_vote("UP", 0.7)),
    ]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=10.0)
    decision = await _drive_window(strategy, spot_late=60_060.0)
    # composite ~0.1, threshold 10 → no fire; meta wasn't called
    assert decision is None
    assert meta.calls == []


async def test_tier_three_fires_even_with_zero_votes() -> None:
    """Composite-only path fires when no specialist votes succeed."""
    specs = [
        _FakeSpecialist("orderbook", vote=None),
        _FakeSpecialist("oracle_gap", vote=None),
        _FakeSpecialist("momentum", vote=None),
    ]
    meta = _FakeMeta(_meta_abstain())
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=0.5)
    decision = await _drive_window(strategy, spot_late=60_600.0)
    assert isinstance(decision, Decision)
    assert "Tier-3" in decision.rationale
    assert meta.calls == []  # never called with <2 votes


async def test_no_fire_outside_ttl_window() -> None:
    """Composite over threshold but TTL not yet in [10, 30]."""
    specs = [_FakeSpecialist("orderbook", vote=_vote("UP")) for _ in range(3)]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(
        specialists=specs, meta=meta, threshold_pct=0.1, ttl_low_s=10, ttl_high_s=30
    )
    # Drive to ts_offset_s=100 (ttl=200, outside [10,30])
    last: Decision | None = None
    for event in [
        _open(),
        _book("UP", TOKEN_UP, ask=0.55),
        _book("DOWN", TOKEN_DOWN, ask=0.46),
        _spot(60_000.0, 0),
        _oracle(60_000.0, 50),
        _spot(60_600.0, 100),  # TTL=200s, outside [10,30]
    ]:
        last = await strategy.on_event(event) or last
    assert last is None


async def test_fires_at_most_once_per_window() -> None:
    specs = [_FakeSpecialist(n, vote=_vote("UP")) for n in ("orderbook", "oracle_gap", "momentum")]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=10.0)
    # Drive a fire then continue with more events within the same window
    last: Decision | None = None
    events = [
        _open(),
        _book("UP", TOKEN_UP, ask=0.55),
        _book("DOWN", TOKEN_DOWN, ask=0.46),
        _spot(60_000.0, 0),
        _oracle(60_000.0, 270),
        _spot(60_600.0, 275),  # → fires
        _spot(60_800.0, 278),  # additional event after fire
        _spot(60_900.0, 280),
    ]
    fires: list[Decision] = []
    for event in events:
        result = await strategy.on_event(event)
        if result is not None:
            fires.append(result)
            last = result
    assert len(fires) == 1
    assert isinstance(last, Decision)


def test_constructor_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold_pct"):
        EnsembleStrategy(
            specialists=[_FakeSpecialist("o")],
            meta=_FakeMeta(None),
            threshold_pct=0.0,
        )


def test_constructor_requires_specialists() -> None:
    with pytest.raises(ValueError, match="at least one specialist"):
        EnsembleStrategy(
            specialists=[],
            meta=_FakeMeta(None),
        )


async def test_reset_clears_state() -> None:
    specs = [_FakeSpecialist(n, vote=_vote("UP")) for n in ("orderbook", "oracle_gap", "momentum")]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=10.0)
    await strategy.on_event(_open())
    await strategy.on_event(_spot(60_000.0, 0))
    strategy.reset()
    # After reset, even a normal-firing sequence doesn't fire because window state is gone
    decision = await strategy.on_event(_spot(60_600.0, 275))
    assert decision is None


async def test_ensemble_passes_full_context_to_meta() -> None:
    """When meta is called, it must receive a populated AgentContext with
    every specialist's vote keyed by its agent name."""
    specs = [_FakeSpecialist(n, vote=_vote("UP")) for n in ("orderbook", "oracle_gap", "momentum")]
    meta = _FakeMeta(_meta_fire("UP"))
    strategy = EnsembleStrategy(specialists=specs, meta=meta, threshold_pct=10.0)
    await _drive_window(strategy, spot_late=60_060.0)
    assert len(meta.calls) == 1
    ctx, votes = meta.calls[0]
    assert set(votes.keys()) == {"orderbook", "oracle_gap", "momentum"}
    # AgentContext fields must be populated (not None / not stub defaults)
    assert ctx.window_ts == WINDOW_TS
    assert ctx.spot_at_window_open == 60_000.0
    assert ctx.oracle_last == 60_000.0
    assert ctx.best_ask_up == 0.55
    assert ctx.best_ask_down == 0.46

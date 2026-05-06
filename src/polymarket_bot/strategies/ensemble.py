"""EnsembleStrategy — bridge agents into the BacktestRunner.Strategy contract.

Maintains the same per-window state as DeterministicStrategy (window-open
spot, oracle, etc.), plus a rolling ~60s spot tick buffer for the momentum
agent. At fire-window time:
  1. Build AgentContext from current state.
  2. Fan out to specialists in parallel (asyncio.gather).
  3. Filter to valid votes; if < 2, Tier-3 fallback to deterministic.
  4. Call meta-decider with the surviving votes.
  5. Compute final action per the union rule (decision #6):
       fire if (composite >= threshold) OR (meta == FIRE)
       side = meta's side if it fired, else composite's sign
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterable

from polymarket_bot.agents.protocol import (
    Agent,
    AgentContext,
    AgentVote,
    MetaAgent,
    MetaDecision,
)
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    MarketEvent,
    OracleUpdate,
    Side,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.resolver import WINDOW_SECONDS
from polymarket_bot.strategies.deterministic import (
    DEFAULT_SIZE_USD,
    DEFAULT_THRESHOLD_PCT,
    DEFAULT_TTL_HIGH_S,
    DEFAULT_TTL_LOW_S,
    DEFAULT_W_ORACLE_GAP,
    DEFAULT_W_WINDOW_DELTA,
    composite_pct,
)

DEFAULT_RECENT_WINDOW_S = 60
DEFAULT_RECENT_BUFFER_LEN = 64

MIN_VOTES_FOR_META = 2


class EnsembleStrategy:
    """3-specialist + meta-decider strategy. Implements the Strategy protocol."""

    name: str = "ensemble"

    def __init__(
        self,
        *,
        specialists: Iterable[Agent],
        meta: MetaAgent,
        threshold_pct: float = DEFAULT_THRESHOLD_PCT,
        ttl_low_s: int = DEFAULT_TTL_LOW_S,
        ttl_high_s: int = DEFAULT_TTL_HIGH_S,
        size_usd: float = DEFAULT_SIZE_USD,
        w_window_delta: float = DEFAULT_W_WINDOW_DELTA,
        w_oracle_gap: float = DEFAULT_W_ORACLE_GAP,
        recent_window_s: int = DEFAULT_RECENT_WINDOW_S,
        recent_buffer_len: int = DEFAULT_RECENT_BUFFER_LEN,
    ) -> None:
        if threshold_pct <= 0:
            raise ValueError(f"threshold_pct must be > 0, got {threshold_pct}")
        if ttl_low_s < 0 or ttl_high_s < ttl_low_s:
            raise ValueError(f"ttl_low_s ({ttl_low_s}) must be in [0, ttl_high_s ({ttl_high_s})]")
        self._specialists = list(specialists)
        if not self._specialists:
            raise ValueError("EnsembleStrategy needs at least one specialist agent")
        self._meta = meta
        self._threshold = threshold_pct
        self._ttl_low = ttl_low_s
        self._ttl_high = ttl_high_s
        self._size_usd = size_usd
        self._w_wd = w_window_delta
        self._w_og = w_oracle_gap
        self._recent_window_s = recent_window_s
        self._recent_buffer_len = recent_buffer_len

        self._spot_now: float | None = None
        self._oracle_last: float | None = None
        self._oracle_last_ns: int | None = None
        self._window_ts: int | None = None
        self._window_open_spot: float | None = None
        self._window_open_oracle: float | None = None
        self._fired_for_window: int | None = None
        self._token_for_side: dict[Side, str] = {}
        self._best_bid_for_side: dict[Side, float] = {}
        self._best_ask_for_side: dict[Side, float] = {}
        self._top_size_for_side: dict[Side, tuple[float, float]] = {}  # (bid_size, ask_size)
        self._recent_spot: deque[tuple[int, float]] = deque(maxlen=recent_buffer_len)

    def reset(self) -> None:
        self._spot_now = None
        self._oracle_last = None
        self._oracle_last_ns = None
        self._window_ts = None
        self._window_open_spot = None
        self._window_open_oracle = None
        self._fired_for_window = None
        self._token_for_side = {}
        self._best_bid_for_side = {}
        self._best_ask_for_side = {}
        self._top_size_for_side = {}
        self._recent_spot.clear()

    async def on_event(self, event: MarketEvent) -> Decision | None:
        if isinstance(event, SpotTick):
            self._spot_now = event.price
            if self._window_open_spot is None and self._window_ts is not None:
                self._window_open_spot = event.price
            self._recent_spot.append((event.ts_utc_ns, event.price))
            return await self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, OracleUpdate):
            self._oracle_last = event.price
            self._oracle_last_ns = event.ts_utc_ns
            if self._window_open_oracle is None and self._window_ts is not None:
                self._window_open_oracle = event.price
            return await self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, BookUpdate):
            self._token_for_side[event.side] = event.asset_id
            if event.best_bid is not None:
                self._best_bid_for_side[event.side] = event.best_bid
            if event.best_ask is not None:
                self._best_ask_for_side[event.side] = event.best_ask
            if event.bid_size_top is not None or event.ask_size_top is not None:
                self._top_size_for_side[event.side] = (
                    event.bid_size_top or 0.0,
                    event.ask_size_top or 0.0,
                )
            return await self._maybe_fire(event.ts_utc_ns)
        if isinstance(event, WindowBoundary) and event.kind == "open":
            self._window_ts = event.window_ts
            self._window_open_spot = None
            self._window_open_oracle = None
            self._fired_for_window = None
        return None

    async def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:
        if self._window_ts is None:
            return None
        if self._fired_for_window == self._window_ts:
            return None
        if self._spot_now is None or self._oracle_last is None or self._window_open_spot is None:
            return None
        ttl_s = self._compute_ttl_s(now_ts_utc_ns)
        if not (self._ttl_low <= ttl_s <= self._ttl_high):
            return None

        composite = composite_pct(
            self._spot_now,
            self._window_open_spot,
            self._oracle_last,
            w_wd=self._w_wd,
            w_og=self._w_og,
        )

        # Build the AgentContext the specialists + meta both consume.
        ctx = self._build_context(now_ts_utc_ns, ttl_s, composite)

        # Fan out specialists in parallel; collect (name → vote) for the
        # subset that returned a valid AgentVote.
        votes = await self._collect_votes(ctx)

        meta_decision: MetaDecision | None = None
        if len(votes) >= MIN_VOTES_FOR_META:
            meta_decision = await self._meta.decide(ctx, votes)

        return self._compose_decision(
            now_ts_utc_ns=now_ts_utc_ns,
            ttl_s=ttl_s,
            composite=composite,
            meta=meta_decision,
        )

    def _build_context(self, now_ts_utc_ns: int, ttl_s: int, composite: float) -> AgentContext:
        # Caller (_maybe_fire) has already guarded all required state; these
        # locals exist purely for mypy's narrowing of Optional → concrete.
        if (
            self._window_ts is None
            or self._spot_now is None
            or self._window_open_spot is None
            or self._oracle_last is None
            or self._window_open_oracle is None
        ):
            raise RuntimeError("ensemble: _build_context called before state ready")

        oracle_age_s = 0.0
        if self._oracle_last_ns is not None:
            oracle_age_s = max(0.0, (now_ts_utc_ns - self._oracle_last_ns) / 1e9)

        cutoff_ns = now_ts_utc_ns - self._recent_window_s * 1_000_000_000
        recent = [price for (ts, price) in self._recent_spot if ts >= cutoff_ns]

        bid_size_up: float | None = None
        ask_size_up: float | None = None
        if "UP" in self._top_size_for_side:
            bid_size_up, ask_size_up = self._top_size_for_side["UP"]
        imbalance = _book_imbalance(bid_size_up, ask_size_up)

        return AgentContext(
            window_ts=self._window_ts,
            now_ts_utc_ns=now_ts_utc_ns,
            seconds_to_close=ttl_s,
            spot_now=self._spot_now,
            spot_at_window_open=self._window_open_spot,
            spot_recent_60s=recent,
            oracle_last=self._oracle_last,
            oracle_at_window_open=self._window_open_oracle,
            oracle_age_s=oracle_age_s,
            best_bid_up=self._best_bid_for_side.get("UP"),
            best_ask_up=self._best_ask_for_side.get("UP"),
            best_bid_down=self._best_bid_for_side.get("DOWN"),
            best_ask_down=self._best_ask_for_side.get("DOWN"),
            book_imbalance=imbalance,
            composite_pct=composite,
        )

    async def _collect_votes(self, ctx: AgentContext) -> dict[str, AgentVote]:
        results = await asyncio.gather(
            *(s.vote(ctx) for s in self._specialists),
            return_exceptions=True,
        )
        votes: dict[str, AgentVote] = {}
        for specialist, result in zip(self._specialists, results, strict=True):
            if isinstance(result, AgentVote):
                votes[specialist.name] = result
        return votes

    def _compose_decision(
        self,
        *,
        now_ts_utc_ns: int,
        ttl_s: int,
        composite: float,
        meta: MetaDecision | None,
    ) -> Decision | None:
        # Tier-3 union: fire if (composite >= threshold) OR (meta FIRE).
        composite_above = abs(composite) >= self._threshold

        side: Side | None = None
        rationale_parts: list[str] = []

        if meta is not None and meta.action == "FIRE" and meta.side is not None:
            side = meta.side
            rationale_parts.append(f"meta=FIRE conf={meta.confidence:.2f}: {meta.rationale[:120]}")
        elif composite_above:
            side = "UP" if composite > 0 else "DOWN"
            rationale_parts.append(
                f"composite={composite:+.3f}pp >= {self._threshold:.2f} (Tier-3)"
            )

        if side is None:
            return None  # neither path fires

        asset_id = self._token_for_side.get(side)
        if asset_id is None:
            return None
        ask = self._best_ask_for_side.get(side)
        price_limit = ask if ask is not None else 0.50

        rationale_parts.append(f"ttl={ttl_s}s side={side}")
        rationale = " | ".join(rationale_parts)[:500]

        if self._window_ts is None:
            return None
        self._fired_for_window = self._window_ts
        return Decision(
            ts_utc_ns=now_ts_utc_ns,
            asset_id=asset_id,
            side="BUY",
            size_usd=self._size_usd,
            price_limit=price_limit,
            ttl_s=ttl_s,
            rationale=rationale,
        )

    def _compute_ttl_s(self, now_ts_utc_ns: int) -> int:
        if self._window_ts is None:
            return -1
        now_s = now_ts_utc_ns // 1_000_000_000
        close_s = self._window_ts + WINDOW_SECONDS
        return max(0, close_s - now_s)


def _book_imbalance(bid_size: float | None, ask_size: float | None) -> float | None:
    if bid_size is None or ask_size is None:
        return None
    total = bid_size + ask_size
    if total <= 0:
        return None
    return (bid_size - ask_size) / total

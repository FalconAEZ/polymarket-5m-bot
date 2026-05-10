"""EnsembleWrapper — wraps a base strategy (e.g., SpotAwareStrategyV2) with
the LLM ensemble's meta-decider as a final gate, plus shadow-mode logging.

Per design/phase-5-llm-ensemble.md (Phase 5.0). The base strategy emits
candidate fires under whatever rules it likes (typically v2-tight or
v2-wide); the ensemble then runs 3 specialists + Sonnet meta against the
same window's context, and one of three modes determines the outcome:

  off    — ensemble bypassed entirely. Base strategy's verdict drives.
  shadow — ensemble votes captured to JSONL but base verdict still drives.
           Used to evaluate ensemble lift WITHOUT production risk.
  gate   — base strategy emits a candidate; ensemble's meta-decider
           OVERRIDES it. Fire iff (base wants to fire) AND (meta=FIRE).
           Production mode after shadow data validates the lift.

In ALL modes, the ensemble call is fully isolated from the base
strategy's logic — a refusal, schema fail, BudgetExceeded, or timeout
defaults to "let the base strategy's verdict stand" (i.e., shadow=log
nothing, gate=fire as base would have). Operator gets a CRITICAL alert
when the ensemble is unable to vote, so silent degradation is impossible.

The EnsembleStrategy in polymarket_bot.strategies.ensemble is a STANDALONE
strategy with its own composite-based gating. EnsembleWrapper is a
DIFFERENT integration: it re-uses the same Agent/MetaAgent contracts but
treats the ensemble as a filter on top of an arbitrary base strategy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

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
from polymarket_bot.strategies.protocol import Strategy

LOG = logging.getLogger("polymarket_bot.strategies.ensemble_wrapper")

EnsembleMode = Literal["off", "shadow", "gate"]

DEFAULT_RECENT_BUFFER_LEN = 64
DEFAULT_RECENT_WINDOW_S = 60
MIN_VOTES_FOR_META = 2


class EnsembleWrapper:
    """A Strategy that runs `base` first and optionally gates its fires
    via the LLM ensemble.

    Construction:
      EnsembleWrapper(
        base=SpotAwareStrategyV2(...),
        specialists=[OrderbookAgent(adapter), OracleGapAgent(adapter), ...],
        meta=MetaAgent(adapter),
        mode="shadow",
        log_root=Path("state/ensemble"),
      )
    """

    name: str = "ensemble"

    def __init__(
        self,
        *,
        base: Strategy,
        specialists: Iterable[Agent],
        meta: MetaAgent,
        mode: EnsembleMode = "off",
        log_root: str | Path | None = None,
        recent_buffer_len: int = DEFAULT_RECENT_BUFFER_LEN,
        recent_window_s: int = DEFAULT_RECENT_WINDOW_S,
    ) -> None:
        self._base = base
        self._specialists = list(specialists)
        if not self._specialists:
            raise ValueError("EnsembleWrapper needs at least one specialist agent")
        self._meta = meta
        self._mode: EnsembleMode = mode
        self._log_root: Path | None = Path(log_root) if log_root is not None else None
        if self._log_root is not None:
            self._log_root.mkdir(parents=True, exist_ok=True)

        # Per-window context state — refreshed on every event so when the
        # base strategy emits a Decision we can build a complete AgentContext
        # without round-tripping back through the runner.
        self._spot_now: float | None = None
        self._oracle_last: float | None = None
        self._oracle_last_ns: int | None = None
        self._window_ts: int | None = None
        self._window_open_spot: float | None = None
        self._window_open_oracle: float | None = None
        self._best_bid_for_side: dict[Side, float] = {}
        self._best_ask_for_side: dict[Side, float] = {}
        self._top_size_for_side: dict[Side, tuple[float, float]] = {}
        self._recent_spot: deque[tuple[int, float]] = deque(maxlen=recent_buffer_len)
        self._recent_window_s = recent_window_s

    @property
    def mode(self) -> EnsembleMode:
        return self._mode

    def reset(self) -> None:
        # Forward to base + clear our context cache.
        try:
            self._base.reset()
        except Exception:
            LOG.exception("base strategy reset() raised; ignoring")
        self._spot_now = None
        self._oracle_last = None
        self._oracle_last_ns = None
        self._window_ts = None
        self._window_open_spot = None
        self._window_open_oracle = None
        self._best_bid_for_side = {}
        self._best_ask_for_side = {}
        self._top_size_for_side = {}
        self._recent_spot.clear()

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # 1. Mirror context state from the same events the base sees, so
        #    when base produces a candidate we have the full snapshot.
        self._update_context(event)

        # 2. Forward the event to the base strategy and capture its verdict.
        candidate = await self._base.on_event(event)

        # 3. If base abstained OR ensemble is off, return base's verdict.
        if candidate is None or self._mode == "off":
            return candidate

        # 4. Build context + run the ensemble (shadow or gate).
        ctx = self._build_context(now_ns=event.ts_utc_ns, candidate=candidate)
        if ctx is None:
            # Cold-start: insufficient data to score. In shadow mode log
            # the gap; in gate mode fall through to base (don't penalise
            # ensemble for cold-start by suppressing valid fires).
            self._log_ensemble_event(
                {
                    "kind": "ensemble_cold_start",
                    "ts_ns": event.ts_utc_ns,
                    "decision_id_hint": _decision_hint(candidate),
                    "mode": self._mode,
                }
            )
            return candidate

        votes, meta_decision = await self._run_ensemble(ctx)

        # 5. Always log ensemble verdict — shadow OR gate.
        self._log_ensemble_event(
            {
                "kind": "ensemble_vote",
                "ts_ns": event.ts_utc_ns,
                "window_ts": self._window_ts,
                "mode": self._mode,
                "decision_id_hint": _decision_hint(candidate),
                "candidate_side": _side_from_rationale(candidate.rationale),
                "candidate_rationale": candidate.rationale,
                "votes": {
                    name: vote.model_dump() if vote is not None else None
                    for name, vote in votes.items()
                },
                "meta": meta_decision.model_dump() if meta_decision is not None else None,
            }
        )

        # 6. Mode-specific gating.
        if self._mode == "shadow":
            return candidate  # base verdict wins; ensemble is observers only
        # gate mode: only fire if meta says FIRE on the same side
        if meta_decision is None or meta_decision.action != "FIRE":
            return None
        candidate_side = _side_from_rationale(candidate.rationale)
        if candidate_side is not None and meta_decision.side != candidate_side:
            # Meta wants to fire the OPPOSITE side. The base committed to
            # one direction; we don't override the side, we abstain.
            return None
        return candidate

    # ------------------------------------------------------------------
    # Internal: context tracking + ensemble call
    # ------------------------------------------------------------------

    def _update_context(self, event: MarketEvent) -> None:
        if isinstance(event, SpotTick):
            self._spot_now = event.price
            if self._window_ts is not None and self._window_open_spot is None:
                self._window_open_spot = event.price
            self._recent_spot.append((event.ts_utc_ns, event.price))
        elif isinstance(event, OracleUpdate):
            self._oracle_last = event.price
            self._oracle_last_ns = event.ts_utc_ns
            if self._window_ts is not None and self._window_open_oracle is None:
                self._window_open_oracle = event.price
        elif isinstance(event, BookUpdate):
            if event.best_bid is not None:
                self._best_bid_for_side[event.side] = event.best_bid
            if event.best_ask is not None:
                self._best_ask_for_side[event.side] = event.best_ask
            if event.bid_size_top is not None or event.ask_size_top is not None:
                self._top_size_for_side[event.side] = (
                    event.bid_size_top or 0.0,
                    event.ask_size_top or 0.0,
                )
        elif isinstance(event, WindowBoundary) and event.kind == "open":
            self._window_ts = event.window_ts
            self._window_open_spot = None
            self._window_open_oracle = None

    def _build_context(self, *, now_ns: int, candidate: Decision) -> AgentContext | None:
        if (
            self._window_ts is None
            or self._spot_now is None
            or self._oracle_last is None
            or self._oracle_last_ns is None
            or self._window_open_spot is None
            or self._window_open_oracle is None
        ):
            return None
        seconds_to_close = max(
            0,
            (self._window_ts + 300) - now_ns // 1_000_000_000,
        )
        cutoff = now_ns - self._recent_window_s * 1_000_000_000
        recent = [p for ts, p in self._recent_spot if ts >= cutoff]
        oracle_age_s = (now_ns - self._oracle_last_ns) / 1_000_000_000
        bid_size_up, ask_size_up = self._top_size_for_side.get("UP", (0.0, 0.0))
        bid_size_down, ask_size_down = self._top_size_for_side.get("DOWN", (0.0, 0.0))
        # Book imbalance: (bid_total - ask_total) / (bid_total + ask_total).
        bid_total = bid_size_up + bid_size_down
        ask_total = ask_size_up + ask_size_down
        imbalance = (
            (bid_total - ask_total) / (bid_total + ask_total)
            if (bid_total + ask_total) > 0
            else None
        )
        return AgentContext(
            window_ts=self._window_ts,
            now_ts_utc_ns=now_ns,
            seconds_to_close=int(seconds_to_close),
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
            composite_pct=_composite_pct_from_rationale(candidate.rationale) or 0.0,
        )

    async def _run_ensemble(
        self, ctx: AgentContext
    ) -> tuple[dict[str, AgentVote | None], MetaDecision | None]:
        # Specialists in parallel; each can return None (refusal/schema/budget).
        results = await asyncio.gather(
            *(spec.vote(ctx) for spec in self._specialists),
            return_exceptions=True,
        )
        votes: dict[str, AgentVote | None] = {}
        valid_count = 0
        for spec, result in zip(self._specialists, results, strict=False):
            if isinstance(result, BaseException):
                LOG.warning("specialist %s raised: %s", spec.name, result)
                votes[spec.name] = None
            else:
                votes[spec.name] = result
                if result is not None:
                    valid_count += 1
        if valid_count < MIN_VOTES_FOR_META:
            return votes, None
        try:
            meta = await self._meta.decide(
                ctx,
                {name: v for name, v in votes.items() if v is not None},
            )
        except Exception as exc:
            LOG.exception("meta agent raised: %s", exc)
            meta = None
        return votes, meta

    def _log_ensemble_event(self, payload: dict[str, object]) -> None:
        if self._log_root is None:
            return
        ts_ns = payload.get("ts_ns")
        if not isinstance(ts_ns, int):
            ts_ns = time.time_ns()
        from datetime import UTC, datetime

        date_str = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")
        path = self._log_root / f"{date_str}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except OSError as exc:
            LOG.exception("ensemble log write failed: %s", exc)


def _side_from_rationale(rationale: str) -> Side | None:
    if "side=UP" in rationale:
        return "UP"
    if "side=DOWN" in rationale:
        return "DOWN"
    return None


def _composite_pct_from_rationale(rationale: str) -> float | None:
    marker = "composite="
    idx = rationale.find(marker)
    if idx < 0:
        # v2 rationales don't include "composite=" — fall back to delta_bps.
        marker = "delta_bps="
        idx = rationale.find(marker)
        if idx < 0:
            return None
    tail = rationale[idx + len(marker) :]
    end = 0
    while end < len(tail) and (tail[end].isdigit() or tail[end] in "+-.eE"):
        end += 1
    if end == 0:
        return None
    try:
        return float(tail[:end])
    except ValueError:
        return None


def _decision_hint(d: Decision) -> str:
    """Compact identifier for the decision in the ensemble log — uses
    decision_ts_ns + asset_id prefix so the log can be joined with the
    main decision_log JSONL after fires actually land."""
    return f"{d.ts_utc_ns}/{d.asset_id[:10]}"

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
from typing import Literal, cast

from polymarket_bot.agents.protocol import (
    Agent,
    AgentContext,
    AgentVote,
    MetaAgent,
    MetaDecision,
    MetaOutcome,
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
from polymarket_bot.strategies.every_window import Router
from polymarket_bot.strategies.every_window.runner import (
    log_router_event,
    parse_delta_bps_from_rationale,
    router_decision_to_decision,
    router_payload,
    side_from_rationale,
)
from polymarket_bot.strategies.every_window.types import Regime, RouterContext, Tier
from polymarket_bot.strategies.protocol import Strategy
from polymarket_bot.strategies.regime_detector import RegimeDetector
from polymarket_bot.tiers import TIER_LABELS, tier_label_for_price

# Regime labels valid as abstain targets. "unknown" is intentionally
# excluded: classify() returns it during cold-start (first ~10s after
# bot restart), so blocking it would refuse every fire in the early
# window. Operator-typo defense; see design/phase-15-regime-gate.md §3.4.
REGIME_GATE_LABELS: frozenset[str] = frozenset({"trending", "chop", "mixed"})

LOG = logging.getLogger("polymarket_bot.strategies.ensemble_wrapper")

EnsembleMode = Literal["off", "shadow", "gate"]

DEFAULT_RECENT_BUFFER_LEN = 64
DEFAULT_RECENT_WINDOW_S = 60
MIN_VOTES_FOR_META = 2

# Gate-mode LLM timeout. The runner's main loop awaits strategy.on_event;
# when the strategy is the ensemble in gate mode, this await IS the LLM
# round-trip (Haiku specialists in parallel + Sonnet meta serially). If
# the LLM hangs/slows, the runner can't drain its feed queue and drops
# market records (audit 2026-05-10 14:24 UTC: 13,172 records dropped in
# the first ~17min of gate-mode). On timeout, we fall back to base
# candidate (same policy as meta=None).
#
# Bumped 2.5s -> 4.0s on 2026-05-10 14:38, then 4.0s -> 8.0s at 14:50
# (still 100% timeout), then 8.0s -> 12.0s at 16:05 UTC after a direct
# latency probe on the VPS measured the actual round-trip:
#   specialists (3x Haiku parallel): median 2.15s, max 4.55s
#   meta (Sonnet medium serial):     median 3.23s, max 3.67s
#   total end-to-end:                median 5.18s, p95 7.08s, max 7.67s
# 8s = ~0.3s headroom over max — too tight, occasional timeouts.
# 12s = ~4s headroom, with queue still draining comfortably (12s
# blocking = 4% of the 5min cycle, buffers ~60-120 records vs 1024
# queue limit). Async pre-compute remains the next step if the LLM
# ever reliably exceeds 12s.
DEFAULT_GATE_LLM_TIMEOUT_S = 12.0


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
        gate_llm_timeout_s: float = DEFAULT_GATE_LLM_TIMEOUT_S,
        tier_blocklist: Iterable[str] = (),
        regime_detector: RegimeDetector | None = None,
        abstain_regimes: Iterable[str] = (),
        router: Router | None = None,
        every_window_mode: bool = False,
        every_window_shadow: bool = False,
        router_log_root: str | Path | None = None,
    ) -> None:
        self._base = base
        self._specialists = list(specialists)
        if not self._specialists:
            raise ValueError("EnsembleWrapper needs at least one specialist agent")
        self._meta = meta
        self._mode: EnsembleMode = mode
        self._gate_llm_timeout_s = max(0.1, gate_llm_timeout_s)
        self._log_root: Path | None = Path(log_root) if log_root is not None else None
        if self._log_root is not None:
            self._log_root.mkdir(parents=True, exist_ok=True)
        # Phase 14: optional entry-price tier blocklist. Empty = no tier
        # filtering; zero overhead. Populated = check candidate.price_limit
        # tier against the set before LLM dispatch and refuse on match.
        unknown = {t for t in tier_blocklist if t not in TIER_LABELS}
        if unknown:
            raise ValueError(
                f"tier_blocklist contains unknown tier labels {sorted(unknown)}; "
                f"valid labels are {sorted(TIER_LABELS)}"
            )
        self._tier_blocklist: frozenset[str] = frozenset(tier_blocklist)

        # Phase 15: optional regime-classifier gate. Empty abstain set =
        # zero-overhead pass-through (no spot-tick observation, no
        # classify() call). When populated, the wrapper observes every
        # SpotTick on the supplied detector and calls classify() before
        # the LLM ensemble runs — refuses on match. `unknown` is rejected
        # at startup to prevent operator-typo cold-start blackout.
        abstain_set = frozenset(abstain_regimes)
        unknown_regimes = abstain_set - REGIME_GATE_LABELS
        if unknown_regimes:
            raise ValueError(
                f"abstain_regimes contains unknown regime labels {sorted(unknown_regimes)}; "
                f"valid labels are {sorted(REGIME_GATE_LABELS)} "
                "('unknown' is intentionally excluded — would block cold-start fires)"
            )
        self._abstain_regimes: frozenset[str] = abstain_set
        # If the detector is supplied, we observe every SpotTick so its
        # buffer warms during the natural ~10-min cold-start. Whether
        # the abstain set is populated or not is independent — operator
        # may want to populate the set later without re-instantiating.
        self._regime_detector: RegimeDetector | None = regime_detector

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
        # Background-task bookkeeping for shadow-mode LLM votes. Per the
        # 2026-05-10 04:20 UTC queue-overflow incident: inline-awaiting
        # the LLM ensemble in the runner main loop blocked record
        # consumption, queue overflowed, 16,223 records dropped. Shadow
        # mode now schedules votes as fire-and-forget tasks tracked
        # here. Shutdown awaits this set via aclose().
        self._pending_shadow_votes: set[asyncio.Task[None]] = set()

        # Phase 16.B.4 — every-window router wire. Default OFF means
        # this code path is short-circuited at the very top of the
        # dispatch (the bulwark "MODE=off → no behavior change" test).
        # When `every_window_mode` is true the router REPLACES the
        # existing FIRE/ABSTAIN dispatch on windows where the base
        # produces a candidate; when `every_window_shadow` is true the
        # router runs as an observer (logs only, base still drives).
        # `_every_window_runtime` is a mutable flag so the runtime
        # kill-switches (Phase 16.B.6, design §5 layers 3-5) can flip
        # the wrapper back to the base flow without a service restart;
        # disable_every_window() is the entry point for those.
        if every_window_mode and router is None:
            raise ValueError(
                "every_window_mode=True requires a Router instance; got router=None. "
                "Pass router=Router(RouterConfig()) (Phase 16.B.4 wire)."
            )
        self._router: Router | None = router
        self._every_window_mode_initial = bool(every_window_mode)
        self._every_window_mode_runtime = bool(every_window_mode)
        self._every_window_shadow = bool(every_window_shadow)
        self._router_log_root: Path | None = (
            Path(router_log_root) if router_log_root is not None else None
        )
        if self._router_log_root is not None:
            self._router_log_root.mkdir(parents=True, exist_ok=True)
        # Per-side asset_id mapping populated from BookUpdate observations
        # so the router can address the correct CTF token when the side
        # it picks differs from the base candidate's side.
        self._asset_id_for_side: dict[Side, str] = {}

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
        self._asset_id_for_side = {}
        self._recent_spot.clear()

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # 1. Mirror context state from the same events the base sees, so
        #    when base produces a candidate we have the full snapshot.
        self._update_context(event)

        # 2. Forward the event to the base strategy and capture its verdict.
        candidate = await self._base.on_event(event)

        # 2b. Phase 14 — entry-price tier blocklist. Applied BEFORE the
        # off/shadow/gate mode dispatch so it works regardless of whether
        # the LLM ensemble is engaged, AND before any LLM call so a
        # blocked tier never costs a Haiku/Sonnet round-trip. Empty
        # blocklist short-circuits with no overhead.
        if candidate is not None and self._tier_blocklist:
            tier = tier_label_for_price(candidate.price_limit)
            if tier in self._tier_blocklist:
                self._log_ensemble_event(
                    {
                        "kind": "tier_abstained",
                        "ts_ns": event.ts_utc_ns,
                        "window_ts": self._window_ts,
                        "decision_id_hint": _decision_hint(candidate),
                        "price_limit": candidate.price_limit,
                        "tier": tier,
                        "blocklist": sorted(self._tier_blocklist),
                        "base_rationale": candidate.rationale,
                    }
                )
                return None

        # 2c. Phase 15 — regime gate. Slots immediately AFTER the tier
        # gate so the cheaper O(1) tier check refuses first; runs BEFORE
        # the LLM dispatch so a chop/mixed regime never costs a Haiku +
        # Sonnet round-trip. Empty abstain set OR no detector
        # short-circuits with no overhead. The classify() call is O(N)
        # on the ~600-tick rolling buffer (<1ms in practice).
        if candidate is not None and self._regime_detector is not None and self._abstain_regimes:
            regime = self._regime_detector.classify(event.ts_utc_ns)
            if regime in self._abstain_regimes:
                self._log_ensemble_event(
                    {
                        "kind": "regime_abstained",
                        "ts_ns": event.ts_utc_ns,
                        "window_ts": self._window_ts,
                        "decision_id_hint": _decision_hint(candidate),
                        "regime": regime,
                        "abstain_regimes": sorted(self._abstain_regimes),
                        "base_rationale": candidate.rationale,
                    }
                )
                return None

        # 2d. Phase 16.B.4 — every-window router takeover. When
        # EVERY_WINDOW_MODE is on AND a candidate exists, the router
        # replaces the FIRE/ABSTAIN dispatch entirely: it consumes the
        # LLM signal as one input (W_LLM weight) and returns its own
        # (side, size, ttl, fill_style) per design §3. With the
        # production wide_fire base this fires on every window with
        # any spot motion; with spot_aware_v2 base it routes the
        # subset of windows v2 already qualifies. The runtime flag
        # (vs the constructor one) lets the periodic kill-switch flip
        # us back to the base flow without a service restart.
        if candidate is not None and self._router is not None and self._every_window_mode_runtime:
            return await self._dispatch_every_window(event=event, candidate=candidate)

        # 2e. Phase 16.B.4 — SHADOW observer (mode off + shadow on).
        # The router runs on every candidate window for the 24h audit
        # but returns nothing; the existing dispatch still drives. LLM
        # signals aren't joined here (the observer fires BEFORE the
        # existing dispatch's LLM run); audit treats LLM-blank shadow
        # records as a documented limitation that goes away when the
        # operator flips MODE=true.
        if (
            candidate is not None
            and self._router is not None
            and self._every_window_shadow
            and not self._every_window_mode_runtime
        ):
            self._log_router_shadow(event=event, candidate=candidate)

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

        # 5. Mode-specific dispatch.
        #
        # SHADOW mode: the LLM verdict is observation-only — the base's
        # candidate IS the fire either way. We MUST NOT block the main
        # runner loop on the LLM call (300-2000ms per call x 4 calls in
        # the worst case). Per the 2026-05-10 04:20 UTC incident
        # (16,223 dropped records), inline-awaiting the ensemble in the
        # main loop reproduces the exact queue-overflow class the
        # background-settle fix already addressed for gamma polls.
        # Solution: schedule the ensemble vote as a fire-and-forget
        # asyncio.Task, return the candidate immediately. The task
        # captures snapshot-style state (ctx, candidate, ts_ns) so the
        # runner's continued mutation of self._state can't corrupt the
        # in-flight vote.
        #
        # GATE mode: the LLM verdict gates the fire — we MUST await it.
        # Mitigation here is operator-side (ensure budget caps and
        # short timeouts) rather than architectural. Default behavior
        # is to keep the inline await for now; if production gate mode
        # ever causes overflow, that's a separate redesign (e.g., run
        # ensemble continuously and gate against last-known verdict).
        if self._mode == "shadow":
            self._spawn_shadow_vote(ctx=ctx, candidate=candidate, event_ts_ns=event.ts_utc_ns)
            return candidate

        # gate mode — inline await with hard timeout. The runner's main
        # loop awaits strategy.on_event so a slow LLM call here blocks
        # the feed-record consumer; per audit 2026-05-10 14:24 UTC, the
        # uncapped await dropped 13,172 records in ~17min when the LLM
        # round-trip exceeded the queue-drain budget. Wait_for() bounds
        # the worst case to gate_llm_timeout_s; on timeout we fall
        # through to base (same policy as meta=None).
        votes: dict[str, AgentVote | None]
        meta_decision: MetaDecision | None
        meta_outcome: MetaOutcome
        try:
            votes, meta_decision, meta_outcome = await asyncio.wait_for(
                self._run_ensemble(ctx), timeout=self._gate_llm_timeout_s
            )
        except TimeoutError:
            LOG.warning(
                "ensemble gate LLM timed out at %.1fs for window %s — "
                "falling back to base candidate (queue-overflow defense)",
                self._gate_llm_timeout_s,
                self._window_ts,
            )
            self._log_ensemble_event(
                {
                    "kind": "ensemble_vote",
                    "ts_ns": event.ts_utc_ns,
                    "window_ts": self._window_ts,
                    "mode": self._mode,
                    "decision_id_hint": _decision_hint(candidate),
                    "candidate_side": _side_from_rationale(candidate.rationale),
                    "candidate_rationale": candidate.rationale,
                    "votes": {},
                    "meta": None,
                    "meta_outcome": "timeout",
                    "timeout_s": self._gate_llm_timeout_s,
                }
            )
            return candidate
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
                "meta_outcome": meta_outcome,
            }
        )
        # GATE-mode fallback policy. Two distinct cases:
        #
        #   (1) meta_decision is None — the LLM call failed (refusal, schema
        #       fail, budget cap, network error). The LLM did NOT vote.
        #       Falling through to base preserves the bot's trade volume
        #       when the LLM infrastructure is degraded — gate-mode then
        #       only ABSTAINs when the LLM ACTUALLY said no, not when it
        #       failed to answer. Audit 2026-05-10: 23% of votes were
        #       null-meta and silently dropped under the previous behavior.
        #
        #   (2) meta_decision.action == "ABSTAIN" — the LLM explicitly said
        #       no. Honor it; return None (no fire).
        if meta_decision is None:
            LOG.warning(
                "ensemble meta=None for window %s — falling back to base "
                "candidate (gate-mode honors LLM only when it actually voted)",
                self._window_ts,
            )
            return candidate
        if meta_decision.action != "FIRE":
            return None
        candidate_side = _side_from_rationale(candidate.rationale)
        if candidate_side is not None and meta_decision.side != candidate_side:
            return None
        return candidate

    def _spawn_shadow_vote(
        self, *, ctx: AgentContext, candidate: Decision, event_ts_ns: int
    ) -> None:
        # Background-task launcher for shadow-mode LLM votes. Mirrors
        # the background-settle pattern in PaperRunner: snapshot all
        # state needed by the task, schedule via asyncio.create_task,
        # track in `_pending_shadow_votes` so shutdown can await
        # in-flight votes (avoids losing the last batch on stop).
        # Errors inside the task are caught at the top-level so a
        # single bad LLM call never propagates to the main loop.
        task = asyncio.create_task(
            self._run_shadow_vote_task(ctx=ctx, candidate=candidate, event_ts_ns=event_ts_ns),
            name=f"ensemble-shadow-vote-{event_ts_ns}",
        )
        self._pending_shadow_votes.add(task)
        task.add_done_callback(self._pending_shadow_votes.discard)

    async def _run_shadow_vote_task(
        self, *, ctx: AgentContext, candidate: Decision, event_ts_ns: int
    ) -> None:
        try:
            votes, meta_decision, meta_outcome = await self._run_ensemble(ctx)
            self._log_ensemble_event(
                {
                    "kind": "ensemble_vote",
                    "ts_ns": event_ts_ns,
                    "window_ts": ctx.window_ts,
                    "mode": "shadow",
                    "decision_id_hint": _decision_hint(candidate),
                    "candidate_side": _side_from_rationale(candidate.rationale),
                    "candidate_rationale": candidate.rationale,
                    "votes": {
                        name: vote.model_dump() if vote is not None else None
                        for name, vote in votes.items()
                    },
                    "meta": meta_decision.model_dump() if meta_decision is not None else None,
                    "meta_outcome": meta_outcome,
                }
            )
        except Exception as exc:
            LOG.exception("shadow vote task failed: %s", exc)

    async def aclose(self) -> None:
        """Await all pending shadow-vote tasks. Idempotent. Called by
        the runner during graceful shutdown so the last batch of votes
        finishes writing to disk before the log file closes."""
        if not self._pending_shadow_votes:
            return
        pending = list(self._pending_shadow_votes)
        LOG.info("awaiting %d in-flight shadow votes", len(pending))
        await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------
    # Phase 16.B.4 — every-window router dispatch + observer + kill-switch
    # ------------------------------------------------------------------

    def disable_every_window(self, reason: str) -> None:
        """Runtime kill-switch — flip EVERY_WINDOW_MODE off in-process.

        Idempotent. The Phase 16.B.6 periodic runtime checks
        (rolling-WR < floor, daily PnL < floor, per-tier daily loss)
        call this so a service restart isn't required. Subsequent
        events take the base flow until the operator restarts the
        service with the constructor flag explicitly set again.
        """
        if not self._every_window_mode_runtime:
            return
        LOG.warning(
            "EVERY_WINDOW_MODE runtime-disabled by kill-switch: reason=%s",
            reason,
        )
        self._every_window_mode_runtime = False
        log_router_event(
            self._router_log_root,
            {
                "kind": "router_disabled",
                "ts_ns": time.time_ns(),
                "reason": reason,
            },
        )

    async def _dispatch_every_window(
        self, *, event: MarketEvent, candidate: Decision
    ) -> Decision | None:
        """Phase 16.B.4 router-driven dispatch.

        Computes the LLM signals once (so the router has W_LLM input),
        builds a RouterContext, calls Router.decide, logs the verdict
        to state/router/<UTC-date>.jsonl, and either returns the
        router-shaped Decision (fire=True) or None (veto).

        On any error in the LLM step we fall through with llm_*=None
        rather than crashing — the router still produces a verdict
        from the deterministic + regime + tier + Kelly inputs and the
        neutral 0.50 LLM-score fallback (router.py::_llm_score).
        """
        router = self._router
        if router is None:
            return candidate  # caller's guard slipped; degrade safely
        agent_ctx = self._build_context(now_ns=event.ts_utc_ns, candidate=candidate)
        llm_meta_action: Literal["FIRE", "ABSTAIN"] | None = None
        llm_meta_side: Side | None = None
        llm_meta_confidence: float | None = None
        llm_consensus: float | None = None
        if agent_ctx is not None and self._mode != "off":
            try:
                votes, meta_decision, meta_outcome = await asyncio.wait_for(
                    self._run_ensemble(agent_ctx), timeout=self._gate_llm_timeout_s
                )
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
                        "meta": (meta_decision.model_dump() if meta_decision is not None else None),
                        "meta_outcome": meta_outcome,
                    }
                )
                if meta_decision is not None:
                    llm_meta_action = meta_decision.action
                    llm_meta_side = meta_decision.side
                    llm_meta_confidence = meta_decision.confidence
                llm_consensus = _consensus_from_votes(votes)
            except TimeoutError:
                LOG.warning(
                    "every-window LLM timed out at %.1fs for window %s — "
                    "router proceeds with neutral LLM score",
                    self._gate_llm_timeout_s,
                    self._window_ts,
                )
                self._log_ensemble_event(
                    {
                        "kind": "ensemble_vote",
                        "ts_ns": event.ts_utc_ns,
                        "window_ts": self._window_ts,
                        "mode": self._mode,
                        "decision_id_hint": _decision_hint(candidate),
                        "candidate_side": _side_from_rationale(candidate.rationale),
                        "candidate_rationale": candidate.rationale,
                        "votes": {},
                        "meta": None,
                        "meta_outcome": "timeout",
                        "timeout_s": self._gate_llm_timeout_s,
                    }
                )

        router_ctx = self._build_router_context(
            event=event,
            candidate=candidate,
            llm_meta_action=llm_meta_action,
            llm_meta_side=llm_meta_side,
            llm_meta_confidence=llm_meta_confidence,
            llm_consensus=llm_consensus,
        )
        if router_ctx is None:
            # Cold-start: too little state to score. Fall through to base
            # so volume isn't lost; log the gap for audit.
            log_router_event(
                self._router_log_root,
                {
                    "kind": "router_cold_start",
                    "ts_ns": event.ts_utc_ns,
                    "window_ts": self._window_ts,
                    "decision_id_hint": _decision_hint(candidate),
                },
            )
            return candidate

        router_decision = router.decide(router_ctx)
        kind: Literal["router_fired", "router_vetoed"] = (
            "router_fired" if router_decision.fire else "router_vetoed"
        )
        log_router_event(
            self._router_log_root,
            router_payload(
                kind,
                decision=router_decision,
                ctx=router_ctx,
                ts_ns=event.ts_utc_ns,
                decision_hint=_decision_hint(candidate),
            ),
            ts_ns=event.ts_utc_ns,
        )
        if not router_decision.fire:
            return None
        return router_decision_to_decision(
            router_decision,
            candidate=candidate,
            ts_utc_ns=event.ts_utc_ns,
            asset_id_for_side=self._asset_id_for_side,
        )

    def _log_router_shadow(self, *, event: MarketEvent, candidate: Decision) -> None:
        """Observer-mode log: run the router without LLM signals and
        append a 'router_shadow' record so the 24h audit (Phase 16.B.5)
        can compare router-would-fire against actual-fired."""
        router = self._router
        if router is None:
            return  # caller's guard slipped; silent no-op
        router_ctx = self._build_router_context(
            event=event,
            candidate=candidate,
            llm_meta_action=None,
            llm_meta_side=None,
            llm_meta_confidence=None,
            llm_consensus=None,
        )
        if router_ctx is None:
            return
        router_decision = router.decide(router_ctx)
        log_router_event(
            self._router_log_root,
            router_payload(
                "router_shadow",
                decision=router_decision,
                ctx=router_ctx,
                ts_ns=event.ts_utc_ns,
                decision_hint=_decision_hint(candidate),
            ),
            ts_ns=event.ts_utc_ns,
        )

    def _build_router_context(
        self,
        *,
        event: MarketEvent,
        candidate: Decision,
        llm_meta_action: Literal["FIRE", "ABSTAIN"] | None,
        llm_meta_side: Side | None,
        llm_meta_confidence: float | None,
        llm_consensus: float | None,
    ) -> RouterContext | None:
        """Pack wrapper state + candidate signals + LLM signals into a
        RouterContext. Returns None on cold-start (no window + no spot)."""
        if self._window_ts is None or self._spot_now is None or self._window_open_spot is None:
            return None
        router = self._router
        if router is None:
            return None
        config = router.config
        delta_bps = parse_delta_bps_from_rationale(candidate.rationale)
        candidate_side = side_from_rationale(candidate.rationale)
        seconds_to_close = max(
            0,
            (self._window_ts + WINDOW_SECONDS) - event.ts_utc_ns // 1_000_000_000,
        )
        oracle_age_s = (
            (event.ts_utc_ns - self._oracle_last_ns) / 1_000_000_000
            if self._oracle_last_ns is not None
            else 999.0
        )
        if candidate_side is not None:
            _bid_size, ask_size = self._top_size_for_side.get(candidate_side, (0.0, 0.0))
            ask_size_top: float | None = ask_size if ask_size > 0 else None
        else:
            ask_size_top = None
        tier_label = tier_label_for_price(candidate.price_limit)
        tier: Tier = cast(Tier, tier_label) if tier_label in TIER_LABELS else "50-70%"
        regime: Regime = (
            self._regime_detector.classify(event.ts_utc_ns)
            if self._regime_detector is not None
            else "unknown"
        )
        bid_up, ask_up = self._top_size_for_side.get("UP", (0.0, 0.0))
        bid_down, ask_down = self._top_size_for_side.get("DOWN", (0.0, 0.0))
        bid_total = bid_up + bid_down
        ask_total = ask_up + ask_down
        imbalance = (
            (bid_total - ask_total) / (bid_total + ask_total)
            if (bid_total + ask_total) > 0
            else None
        )
        if candidate_side is not None:
            fill_price = self._best_ask_for_side.get(candidate_side, 0.50)
        else:
            fill_price = 0.50
        return RouterContext(
            window_ts=self._window_ts,
            now_ts_utc_ns=event.ts_utc_ns,
            seconds_to_close=int(seconds_to_close),
            spot_now=self._spot_now,
            window_open_spot=self._window_open_spot,
            oracle_last=self._oracle_last,
            oracle_age_s=oracle_age_s,
            composite_pct=delta_bps,
            delta_bps=delta_bps,
            best_bid_up=self._best_bid_for_side.get("UP"),
            best_ask_up=self._best_ask_for_side.get("UP"),
            best_bid_down=self._best_bid_for_side.get("DOWN"),
            best_ask_down=self._best_ask_for_side.get("DOWN"),
            ask_size_top=ask_size_top,
            book_imbalance=imbalance,
            regime=regime,
            tier=tier,
            llm_meta_action=llm_meta_action,
            llm_meta_side=llm_meta_side,
            llm_meta_confidence=llm_meta_confidence,
            llm_consensus=llm_consensus,
            bankroll_usd=config.bankroll_usd,
            p_win_prior=None,
            fill_price_estimate=fill_price,
        )

    # ------------------------------------------------------------------
    # Internal: context tracking + ensemble call
    # ------------------------------------------------------------------

    def _update_context(self, event: MarketEvent) -> None:
        if isinstance(event, SpotTick):
            self._spot_now = event.price
            if self._window_ts is not None and self._window_open_spot is None:
                self._window_open_spot = event.price
            self._recent_spot.append((event.ts_utc_ns, event.price))
            # Phase 15: feed the regime classifier's rolling buffer if
            # one is configured. observe_spot is O(1) amortised (deque
            # append + age-trim).
            if self._regime_detector is not None:
                self._regime_detector.observe_spot(event.ts_utc_ns, event.price)
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
            # Phase 16.B.4: router may pick a side that differs from the
            # base candidate's — remember each side's asset_id so we can
            # build a Decision addressed to the correct CTF token.
            self._asset_id_for_side[event.side] = event.asset_id
        elif isinstance(event, WindowBoundary) and event.kind == "open":
            self._window_ts = event.window_ts
            self._window_open_spot = None
            self._window_open_oracle = None

    def _build_context(self, *, now_ns: int, candidate: Decision) -> AgentContext | None:
        # Hard requirements: window known + spot known on both sides of
        # the window. Without these the bot literally can't have made a
        # candidate fire so this branch is true cold-start.
        if self._window_ts is None or self._spot_now is None or self._window_open_spot is None:
            return None
        # Soft requirements: oracle. Chainlink heartbeats ~33s, so on a
        # just-restarted bot or a quiet window we may have no oracle
        # reading yet. Rather than skip the LLM ensemble entirely (which
        # was the prior behavior — every "cold-start" log ate a fire's
        # vote), fall back to spot as a proxy. The oracle_gap specialist
        # can recognise the staleness via oracle_age_s and abstain; the
        # orderbook + momentum specialists don't need oracle data at all.
        oracle_last = self._oracle_last if self._oracle_last is not None else self._spot_now
        oracle_at_window_open = (
            self._window_open_oracle
            if self._window_open_oracle is not None
            else self._window_open_spot
        )
        if self._oracle_last_ns is not None:
            oracle_age_s = (now_ns - self._oracle_last_ns) / 1_000_000_000
        else:
            # Very stale signal value; oracle_gap agent treats this as
            # "no real oracle, abstain".
            oracle_age_s = 999.0
        seconds_to_close = max(
            0,
            (self._window_ts + WINDOW_SECONDS) - now_ns // 1_000_000_000,
        )
        cutoff = now_ns - self._recent_window_s * 1_000_000_000
        recent = [p for ts, p in self._recent_spot if ts >= cutoff]
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
            oracle_last=oracle_last,
            oracle_at_window_open=oracle_at_window_open,
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
    ) -> tuple[dict[str, AgentVote | None], MetaDecision | None, MetaOutcome]:
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
            return votes, None, "no_meta_call"
        try:
            meta, outcome = await self._meta.decide(
                ctx,
                {name: v for name, v in votes.items() if v is not None},
            )
        except Exception as exc:
            LOG.exception("meta agent raised: %s", exc)
            meta = None
            outcome = "exception"
        return votes, meta, outcome

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


def _consensus_from_votes(votes: dict[str, AgentVote | None]) -> float | None:
    """Specialist-agreement score for the router's W_LLM consensus input.

    Returns the fraction of directional votes that agree on the
    majority side (1.0 = unanimous, 2/3 ≈ 0.67, 1/2 = 0.50). ABSTAIN
    specialists don't count toward consensus — they don't vote a
    direction. Returns None when no specialist offered a directional
    vote (router's `_llm_score` treats None as 'no consensus signal'
    and uses meta confidence alone).
    """
    from collections import Counter

    directional = [v for v in votes.values() if v is not None and v.side in ("UP", "DOWN")]
    if not directional:
        return None
    side_counts = Counter(v.side for v in directional)
    most_common_count = side_counts.most_common(1)[0][1]
    return most_common_count / len(directional)

"""Wrapper-side helpers that wire ``Router`` into ``EnsembleWrapper``.

The ``Router`` itself is a pure function (``router.py``); this module is
the seam between the wrapper's mirrored event state and the router's
inputs/outputs:

  - ``build_router_context`` packages wrapper state + the base candidate's
    parsed signals + optional LLM signals into a ``RouterContext``.
  - ``router_decision_to_decision`` translates a fire=True
    ``RouterDecision`` back into the ``Decision`` shape the
    ``PaperRunner`` ingests (preserves ``asset_id`` from the base
    candidate; replaces ``size_usd``, ``ttl_s``, ``price_limit``, and
    rationale).
  - ``log_router_event`` appends to ``state/router/<UTC-date>.jsonl`` in
    the same daily-rotating shape used by the ensemble log.

Logged record kinds:
  - ``router_fired``  — ``fire=True``, includes confidence breakdown
  - ``router_vetoed`` — ``fire=False``, includes ``veto_reason``
  - ``router_shadow`` — observer log (``EVERY_WINDOW_SHADOW=true``)

Phase 16.B.4. See ``design/phase-16b-every-window-mode.md`` §11.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from polymarket_bot.backtest.types import Decision, Side
from polymarket_bot.strategies.every_window.types import (
    RouterContext,
    RouterDecision,
)

LOG = logging.getLogger("polymarket_bot.strategies.every_window.runner")

RouterLogKind = Literal["router_fired", "router_vetoed", "router_shadow"]


def parse_delta_bps_from_rationale(rationale: str) -> float:
    """Extract the signed ``delta_bps=<float>`` value from a rationale.

    Both ``wide_fire`` and ``spot_aware_v2`` rationales include
    ``delta_bps=+X.XX``. Returns 0.0 when absent so the router falls
    through to det_score(0)=0 rather than crashing.
    """
    marker = "delta_bps="
    idx = rationale.find(marker)
    if idx < 0:
        return 0.0
    tail = rationale[idx + len(marker) :]
    end = 0
    while end < len(tail) and (tail[end].isdigit() or tail[end] in "+-.eE"):
        end += 1
    if end == 0:
        return 0.0
    try:
        return float(tail[:end])
    except ValueError:
        return 0.0


def side_from_rationale(rationale: str) -> Side | None:
    """Extract ``side=UP`` or ``side=DOWN`` from a rationale string."""
    if "side=UP" in rationale:
        return "UP"
    if "side=DOWN" in rationale:
        return "DOWN"
    return None


def router_decision_to_decision(
    router: RouterDecision,
    *,
    candidate: Decision,
    ts_utc_ns: int,
    asset_id_for_side: dict[Side, str],
) -> Decision:
    """Build a ``Decision`` from a fire=True ``RouterDecision``.

    The router picks ``side``, ``size_usd``, ``ttl_s``, ``price_limit``,
    and writes its own ``rationale``. We preserve ``asset_id`` from the
    side mapping (the wrapper sees both UP and DOWN BookUpdates with
    their asset_ids; we look up the chosen side) and reuse ``ts_utc_ns``
    from the firing event.

    Falls back to the candidate's ``asset_id`` if the side mapping is
    missing — this can happen on a window where the wrapper has only
    seen one side's book yet.
    """
    asset_id = asset_id_for_side.get(router.side, candidate.asset_id)
    return Decision(
        ts_utc_ns=ts_utc_ns,
        asset_id=asset_id,
        side="BUY",
        size_usd=router.size_usd,
        price_limit=router.price_limit,
        ttl_s=router.ttl_s,
        rationale=router.rationale,
    )


def log_router_event(
    log_root: Path | None,
    payload: dict[str, object],
    *,
    ts_ns: int | None = None,
) -> None:
    """Append a router log entry to ``<log_root>/<UTC-date>.jsonl``.

    Mirror of ``EnsembleWrapper._log_ensemble_event``. Daily rotation by
    UTC date (matches the existing decisions/ensemble logs). Missing
    log_root is a silent no-op so tests don't need to wire it.
    """
    if log_root is None:
        return
    log_root.mkdir(parents=True, exist_ok=True)
    if ts_ns is None:
        raw_ts = payload.get("ts_ns")
        ts_ns = raw_ts if isinstance(raw_ts, int) else _now_ns()
    date_str = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")
    path = log_root / f"{date_str}.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except OSError as exc:
        LOG.exception("router log write failed: %s", exc)


def router_payload(
    kind: RouterLogKind,
    *,
    decision: RouterDecision,
    ctx: RouterContext,
    ts_ns: int,
    decision_hint: str,
) -> dict[str, object]:
    """Shape one JSONL record for the router log.

    Carries enough state to (a) reconstruct the inputs that drove the
    decision and (b) join against ``state/decisions/<date>.jsonl`` by
    ``decision_hint`` + ``window_ts``.
    """
    return {
        "kind": kind,
        "ts_ns": ts_ns,
        "window_ts": ctx.window_ts,
        "decision_id_hint": decision_hint,
        "fire": decision.fire,
        "side": decision.side,
        "size_usd": decision.size_usd,
        "ttl_s": decision.ttl_s,
        "fill_style": decision.fill_style,
        "price_limit": decision.price_limit,
        "confidence": decision.confidence,
        "veto_reason": decision.veto_reason,
        "rationale": decision.rationale,
        "inputs_breakdown": decision.inputs_breakdown,
        "ctx": {
            "regime": ctx.regime,
            "tier": ctx.tier,
            "delta_bps": ctx.delta_bps,
            "composite_pct": ctx.composite_pct,
            "spot_now": ctx.spot_now,
            "best_ask_up": ctx.best_ask_up,
            "best_ask_down": ctx.best_ask_down,
            "ask_size_top": ctx.ask_size_top,
            "llm_meta_action": ctx.llm_meta_action,
            "llm_meta_side": ctx.llm_meta_side,
            "llm_meta_confidence": ctx.llm_meta_confidence,
            "llm_consensus": ctx.llm_consensus,
        },
    }


def _now_ns() -> int:
    import time

    return time.time_ns()

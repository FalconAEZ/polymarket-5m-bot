"""Router dataclasses — RouterContext + RouterDecision.

Phase 16.B.3. Read-only snapshots; the router is a pure function from
``RouterContext`` -> ``RouterDecision``. No IO, no mutation. See
``design/phase-16b-every-window-mode.md`` §3.1 and §3.2 for the locked
contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["UP", "DOWN"]
Regime = Literal["trending", "mixed", "chop", "unknown"]
Tier = Literal["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]
FillStyle = Literal["maker", "taker_fallback"]
MetaAction = Literal["FIRE", "ABSTAIN"]


@dataclass(frozen=True, slots=True)
class RouterContext:
    """Read-only snapshot of everything the router needs to decide one window."""

    # Deterministic state
    window_ts: int
    now_ts_utc_ns: int
    seconds_to_close: int
    spot_now: float | None
    window_open_spot: float | None
    oracle_last: float | None
    oracle_age_s: float
    composite_pct: float | None
    delta_bps: float

    # Market state
    best_bid_up: float | None
    best_ask_up: float | None
    best_bid_down: float | None
    best_ask_down: float | None
    ask_size_top: float | None
    book_imbalance: float | None

    # Pre-classified
    regime: Regime
    tier: Tier

    # LLM signals (optional)
    llm_meta_action: MetaAction | None = None
    llm_meta_side: Side | None = None
    llm_meta_confidence: float | None = None
    llm_consensus: float | None = None

    # Bankroll + priors
    bankroll_usd: float = 1000.0
    p_win_prior: float | None = None
    fill_price_estimate: float | None = None


@dataclass(frozen=True, slots=True)
class RouterDecision:
    """The router's verdict for one window."""

    fire: bool
    side: Side
    size_usd: float
    ttl_s: int
    fill_style: FillStyle
    price_limit: float
    confidence: float
    veto_reason: str | None
    rationale: str
    inputs_breakdown: dict[str, float] = field(default_factory=dict)

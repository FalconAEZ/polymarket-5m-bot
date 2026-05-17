"""Phase 16.B.1 — counterfactual audit of the every-window router.

For each historical fired record in ``state/decisions/*.jsonl``,
recompute what the v2 router (confidence-weighted $5-$30 sizing,
hybrid-Kelly) would have done and project the PnL delta vs the actual
outcome.

This is a SYNTHETIC backtest. It cannot replay tick-by-tick — it
uses the same fired-side as today (since the deterministic composite-
sign rule is unchanged) and only adjusts the SIZE. For fills, it
assumes:

  - Filled trades stay filled at the same price (size doesn't affect
    fill mechanics in shadow_book — bot fires $5 maker-post-only;
    bigger size means a bigger order at the same price, same fill
    decision).
  - Unfilled trades that fall in a TAKER_FALLBACK_TIER (<15%, 85-100%)
    become filled at best_ask (paying the spread).

Output: a markdown report at
``state/research/2026-05-11-router-counterfactual.md``.

Run with:
    uv run python scripts/audit_router_counterfactual.py
"""

from __future__ import annotations

import json
import pathlib
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

DECISIONS_DIR = pathlib.Path("state/decisions")
OUTPUT_PATH = pathlib.Path("state/research/2026-05-11-router-counterfactual.md")

# Tier definitions (mirrors src/polymarket_bot/tiers.py)
TIER_BOUNDS = [
    (0.0, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
]

# v2 confidence weights (from study §12.2)
W_DET = 0.25
W_REG = 0.20
W_TIER = 0.15
W_LLM = 0.25
W_KELLY = 0.15

# Tier-historical scores (calibrated from study §3.2 on 513 fires)
TIER_SCORE = {
    "<15%": 0.50,
    "15-30%": 1.00,
    "30-50%": 0.85,
    "50-70%": 0.40,
    "70-85%": 0.75,
    "85-100%": 0.50,
}

# Regime scores (calibrated from study §3.5 + 2026-05-09 case study)
REGIME_SCORE = {
    "trending": 1.00,
    "mixed": 0.70,
    "chop": 0.40,
    "unknown": 0.50,
}

TAKER_FALLBACK_TIERS = ("<15%", "85-100%")
SIZE_FLOOR = 5.0
SIZE_CAP = 30.0
BANKROLL = 1000.0
KELLY_FRACTION = 0.5
KELLY_MAX_PCT = 0.03


def tier_of(price: float) -> str:
    for lo, hi, lbl in TIER_BOUNDS:
        if lo <= price < hi:
            return lbl
    return "?"


def normalize_delta(abs_db: float) -> float:
    """Map |delta_bps| → [0,1] using observed predictive ranges (study §3.3).

    0-1bps: 0.0 (coinflip noise)
    1-2bps: 0.25 (small edge)
    2-5bps: 0.50 (real edge)
    5-10bps: 0.85 (high edge)
    >10bps: 1.00 (max signal)
    """
    if abs_db < 1.0:
        return 0.0
    if abs_db < 2.0:
        return 0.25
    if abs_db < 5.0:
        return 0.50
    if abs_db < 10.0:
        return 0.85
    return 1.00


def kelly_suggested_size_usd(p_win: float, fill_price: float) -> float:
    """Half-Kelly with 3% bankroll cap. Returns SUGGESTED size in $."""
    if p_win <= fill_price or p_win >= 1.0 or fill_price <= 0:
        return 0.0
    b = (1.0 - fill_price) / fill_price
    f = (p_win * b - (1.0 - p_win)) / b
    f = max(0.0, min(KELLY_MAX_PCT, f * KELLY_FRACTION))
    return round(f * BANKROLL, 2)


@dataclass
class Fire:
    decision_id: str
    fired: dict[str, Any]
    settled: dict[str, Any] | None = None
    corrections: list[dict[str, Any]] | None = None


def load_fires() -> list[Fire]:
    by_id: dict[str, Fire] = {}
    for fp in sorted(DECISIONS_DIR.glob("2026-05-*.jsonl")):
        for ln in fp.open():
            r = json.loads(ln.strip())
            did = r["decision_id"]
            kind = r.get("kind")
            if kind == "fired":
                by_id.setdefault(did, Fire(decision_id=did, fired=r, corrections=[]))
            elif kind == "settled":
                if did in by_id:
                    by_id[did].settled = r
            elif kind == "settled_correction":
                if did in by_id:
                    cor = by_id[did].corrections or []
                    cor.append(r)
                    by_id[did].corrections = cor
    return list(by_id.values())


def composite_from_rationale(rationale: str | None) -> float | None:
    if not rationale:
        return None
    m = re.search(r"delta_bps=([+-]?\d+\.?\d*)", rationale)
    return float(m.group(1)) if m else None


def effective_pnl(f: Fire) -> float:
    """Corrected PnL: settled_correction overrides settled."""
    if f.corrections:
        # last-write-wins
        f.corrections.sort(key=lambda r: r["corrected_ts_ns"])
        return float(f.corrections[-1].get("corrected_pnl_usd") or 0.0)
    if f.settled is None:
        return 0.0
    return float(f.settled.get("pnl_usd") or 0.0)


def effective_resolution(f: Fire) -> str | None:
    if f.corrections:
        f.corrections.sort(key=lambda r: r["corrected_ts_ns"])
        return f.corrections[-1].get("corrected_resolution")
    if f.settled is None:
        return None
    return f.settled.get("resolution")


def is_filled(f: Fire) -> bool:
    if f.fired.get("fill"):
        return True
    if f.settled and f.settled.get("fill_at_settle"):
        return True
    return False


def fill_price(f: Fire) -> float | None:
    if f.fired.get("fill"):
        return float(f.fired["fill"]["price_filled"])
    if f.settled and f.settled.get("fill_at_settle"):
        return float(f.settled["fill_at_settle"]["price_filled"])
    return None


# --- Router computation -------------------------------------------------------


def router_confidence(
    abs_delta_bps: float,
    tier_label: str,
    regime: str = "unknown",
    llm_meta_action: str | None = None,
    llm_meta_confidence: float | None = None,
    p_win_est: float = 0.52,
    fill_price_est: float = 0.50,
) -> tuple[float, dict[str, float]]:
    """Compute confidence score + per-input breakdown."""
    det = normalize_delta(abs_delta_bps)
    reg = REGIME_SCORE.get(regime, 0.50)
    tier = TIER_SCORE.get(tier_label, 0.50)
    if llm_meta_action == "FIRE" and llm_meta_confidence is not None:
        llm = max(0.30, min(1.00, llm_meta_confidence))
    elif llm_meta_action == "ABSTAIN":
        llm = 0.30
    else:
        llm = 0.50  # meta=None or no LLM signal
    kelly_s = kelly_suggested_size_usd(p_win_est, fill_price_est)
    kelly = min(1.0, kelly_s / 22.0) if kelly_s > 0 else 0.0
    confidence = W_DET * det + W_REG * reg + W_TIER * tier + W_LLM * llm + W_KELLY * kelly
    return confidence, {"det": det, "reg": reg, "tier": tier, "llm": llm, "kelly": kelly}


def router_size(confidence: float) -> float:
    return max(SIZE_FLOOR, min(SIZE_CAP, SIZE_FLOOR + (SIZE_CAP - SIZE_FLOOR) * confidence))


# --- Projection ---------------------------------------------------------------


@dataclass
class CounterfactualRow:
    fire: Fire
    tier_label: str
    abs_delta_bps: float
    actual_size: float
    actual_filled: bool
    actual_pnl: float
    actual_won: bool | None
    actual_resolution: str | None
    router_confidence: float
    router_size: float
    router_filled: bool
    router_taker_fallback: bool
    router_projected_pnl: float


def project_router_pnl(f: Fire) -> CounterfactualRow | None:
    fired = f.fired
    db = composite_from_rationale(fired.get("rationale"))
    if db is None:
        return None
    abs_db = abs(db)
    tier_label = tier_of(fired.get("price_limit") or 0.0)
    actual_size = float(fired.get("size_usd") or 5.0)
    actual_filled = is_filled(f)
    actual_pnl = effective_pnl(f)
    resolution = effective_resolution(f)
    side = fired.get("side")
    actual_won = None if resolution is None else (side == resolution)
    fp = fill_price(f) or float(fired.get("price_limit") or 0.50)

    # PHANTOM-FILL VETO (mirrors v2 router's safety check).
    # Phase 11.A finding: fills at price < $0.06 with ask_size_top=None at
    # fire time are phantom. settled_correction may have zeroed the PnL
    # but resolution stays "UP" — naive projection would size UP and
    # produce absurd projected PnL ($30k+ on n=21 phantoms). Router
    # would VETO these windows. Reflect that here.
    snap = fired.get("snapshot") or {}
    ask_size_top = snap.get("ask_size_top")
    if actual_filled and fp < 0.06 and ask_size_top is None:
        # Router would veto → project 0 PnL, 0 size
        return CounterfactualRow(
            fire=f,
            tier_label=tier_label,
            abs_delta_bps=abs_db,
            actual_size=actual_size,
            actual_filled=actual_filled,
            actual_pnl=actual_pnl,
            actual_won=actual_won,
            actual_resolution=resolution,
            router_confidence=0.0,
            router_size=0.0,
            router_filled=False,
            router_taker_fallback=False,
            router_projected_pnl=0.0,
        )

    # p_win estimate: use empirical per-tier WR if we have enough history.
    # For counterfactual, just use tier_score adjusted to a probability.
    p_win_est = 0.50 + 0.10 * (TIER_SCORE.get(tier_label, 0.5) - 0.5)

    # Router decides on this window
    confidence, _ = router_confidence(
        abs_delta_bps=abs_db,
        tier_label=tier_label,
        regime="unknown",  # no per-window regime info in fired records
        llm_meta_action=None,
        llm_meta_confidence=None,
        p_win_est=p_win_est,
        fill_price_est=fp,
    )
    rsize = router_size(confidence)

    # Fill projection
    router_filled = actual_filled
    router_taker = False
    if not actual_filled and tier_label in TAKER_FALLBACK_TIERS:
        # Project taker fallback: fills at best_ask + 1¢ slippage.
        # PHANTOM-FILL DEFENSE: refuse to fire if best_ask < $0.05 (the
        # phantom-fill class lives below this). NOTE: historical snapshots
        # often have ask_size_top=None due to a snapshotter gap — in
        # production the WS feed has size attestation. So we relax the
        # ask_size requirement here for the counterfactual, just keeping
        # the price floor.
        ask = snap.get("best_ask")
        if ask is not None and 0.05 <= float(ask) <= 0.95:
            router_filled = True
            router_taker = True
            fp = float(ask) + 0.01  # 1¢ slippage
            # Safety cap: at tier extremes, taker stake capped at $10
            # (half the router's max). Limits blast radius if the projection
            # assumption about fill price is optimistic.
            rsize = min(rsize, 10.0)

    # PnL projection — HONEST PROPORTIONAL SCALE.
    #
    # The router places a larger order than the actual $5 fire, but
    # we CANNOT assume the same fill price holds. Two safe modes:
    #
    #   1. If actual_filled: scale actual PnL by size ratio.
    #      This is conservative: it assumes the bigger order produces
    #      the same RATE of return as the actual one — no compounding,
    #      no magic alpha from sizing.
    #
    #   2. If NOT actual_filled but taker fallback eligible: project
    #      a small synthetic outcome based on tier WR + the actual
    #      resolution we know (since size 0 → some-size doesn't change
    #      the resolution, only the win/loss dollar amount).
    if not router_filled:
        proj_pnl = 0.0
    elif actual_filled:
        # Proportional scale: same trade, bigger size, same RATE.
        size_ratio = rsize / actual_size if actual_size > 0 else 1.0
        proj_pnl = actual_pnl * size_ratio
        if router_taker:
            # Taker fallback wasn't used (already filled as maker) — no extra cost.
            pass
    else:
        # Taker fallback fill: project using actual resolution.
        # WIN: (1 - fp) x shares - fee, LOSS: -fp x shares - fee
        # Cap at 2x the equivalent $5 trade so we stay conservative.
        if resolution is None or actual_won is None:
            proj_pnl = 0.0
        elif actual_won:
            # Conservative: assume same payoff ratio as a $5 fire would have got
            equivalent_5_payoff = 5.0 * (1.0 - fp) / fp if fp > 0 else 0.0
            proj_pnl = min(equivalent_5_payoff * (rsize / 5.0), equivalent_5_payoff * 4.0)
            proj_pnl -= 0.02 * rsize  # 2¢ taker spread per dollar of stake
        else:
            proj_pnl = -rsize - 0.02 * rsize  # full size loss + spread
    return CounterfactualRow(
        fire=f,
        tier_label=tier_label,
        abs_delta_bps=abs_db,
        actual_size=actual_size,
        actual_filled=actual_filled,
        actual_pnl=actual_pnl,
        actual_won=actual_won,
        actual_resolution=resolution,
        router_confidence=confidence,
        router_size=rsize,
        router_filled=router_filled,
        router_taker_fallback=router_taker,
        router_projected_pnl=proj_pnl,
    )


# --- Report -------------------------------------------------------------------


def fmt_delta(d: float) -> str:
    sign = "+" if d >= 0 else ""
    return f"{sign}${d:.2f}"


def main() -> int:
    fires = load_fires()
    rows: list[CounterfactualRow] = []
    for f in fires:
        if f.settled is None:
            continue
        r = project_router_pnl(f)
        if r is not None:
            rows.append(r)
    n = len(rows)
    if n == 0:
        print("no rows")
        return 1

    # Per-tier rollup
    by_tier: dict[str, list[CounterfactualRow]] = defaultdict(list)
    for r in rows:
        by_tier[r.tier_label].append(r)

    # Per-|delta| bucket
    BUCKETS = [(0, 1), (1, 2), (2, 5), (5, 10), (10, 100)]
    by_db: dict[str, list[CounterfactualRow]] = defaultdict(list)
    for r in rows:
        for lo, hi in BUCKETS:
            if lo <= r.abs_delta_bps < hi:
                by_db[f"{lo}-{hi}bps"].append(r)
                break

    # Per-confidence-bucket
    CONF_BUCKETS = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    by_conf: dict[str, list[CounterfactualRow]] = defaultdict(list)
    for r in rows:
        for lo, hi in CONF_BUCKETS:
            if lo <= r.router_confidence < hi:
                by_conf[f"{lo:.1f}-{hi:.1f}"].append(r)
                break

    total_actual = sum(r.actual_pnl for r in rows)
    total_proj = sum(r.router_projected_pnl for r in rows)
    delta = total_proj - total_actual

    fills_new = sum(1 for r in rows if r.router_filled and not r.actual_filled)
    avg_router_size = statistics.mean(r.router_size for r in rows)
    confidence_distribution = Counter()
    for r in rows:
        confidence_distribution[round(r.router_confidence, 1)] += 1

    # Render report
    lines: list[str] = []
    lines.append("---")
    lines.append("title: Phase 16.B.1 — router counterfactual audit")
    lines.append("date: 2026-05-11")
    lines.append("tags: [audit, phase-16b, counterfactual]")
    lines.append("---")
    lines.append("")
    lines.append("# Phase 16.B.1 — router counterfactual audit")
    lines.append("")
    lines.append("> Synthetic backtest: for each historical fired record, recompute what the")
    lines.append("> v2 router (confidence-weighted $5-$30 sizing, hybrid-Kelly) WOULD HAVE")
    lines.append("> done and project the PnL delta. **No replay of orderbook depth, no**")
    lines.append("> **regime-by-window lookup, no LLM re-run.** This is a first-cut")
    lines.append("> projection from the existing fired+settled+correction data.")
    lines.append("")
    lines.append("## Top-line numbers")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Settled rows audited | **{n}** |")
    lines.append(f"| Today's actual PnL (corrected) | **{fmt_delta(total_actual)}** |")
    lines.append(
        f"| Router's projected PnL (same fires + size shaping) | **{fmt_delta(total_proj)}** |"
    )
    lines.append(f"| **Net delta from router** | **{fmt_delta(delta)}** |")
    lines.append(f"| Avg router size (vs $5 today) | **${avg_router_size:.2f}** |")
    lines.append(f"| New fills via taker fallback | **{fills_new}** |")
    lines.append("")
    lines.append("## Per-tier breakdown")
    lines.append("")
    lines.append("| Tier | n | Actual PnL | Router PnL | Δ | Avg router size |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for _, _, lbl in TIER_BOUNDS:
        if lbl not in by_tier:
            continue
        rs = by_tier[lbl]
        a = sum(r.actual_pnl for r in rs)
        p = sum(r.router_projected_pnl for r in rs)
        sz = statistics.mean(r.router_size for r in rs)
        lines.append(
            f"| `{lbl}` | {len(rs)} | {fmt_delta(a)} | {fmt_delta(p)} | {fmt_delta(p - a)} | ${sz:.2f} |"
        )
    lines.append("")
    lines.append("## Per-`|delta_bps|` breakdown")
    lines.append("")
    lines.append("| Bucket | n | Actual PnL | Router PnL | Δ | Avg router size |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for lo, hi in BUCKETS:
        k = f"{lo}-{hi}bps"
        if k not in by_db:
            continue
        rs = by_db[k]
        a = sum(r.actual_pnl for r in rs)
        p = sum(r.router_projected_pnl for r in rs)
        sz = statistics.mean(r.router_size for r in rs)
        lines.append(
            f"| `{k}` | {len(rs)} | {fmt_delta(a)} | {fmt_delta(p)} | {fmt_delta(p - a)} | ${sz:.2f} |"
        )
    lines.append("")
    lines.append("## Confidence-bucket breakdown")
    lines.append("")
    lines.append("| Confidence | n | Avg size | Actual PnL | Router PnL | Δ |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for lo, hi in CONF_BUCKETS:
        k = f"{lo:.1f}-{hi:.1f}"
        if k not in by_conf:
            continue
        rs = by_conf[k]
        a = sum(r.actual_pnl for r in rs)
        p = sum(r.router_projected_pnl for r in rs)
        sz = statistics.mean(r.router_size for r in rs)
        lines.append(
            f"| `{k}` | {len(rs)} | ${sz:.2f} | {fmt_delta(a)} | {fmt_delta(p)} | {fmt_delta(p - a)} |"
        )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- **Regime not per-window:** projection uses `regime=unknown` for all rows. Real router would weight trending stronger and chop weaker. **Expected effect:** router projection is CONSERVATIVE for the trending subset (would have been larger sizes); LIBERAL for the chop subset (smaller)."
    )
    lines.append(
        "- **LLM not re-run:** projection uses `llm=0.50` (neutral) for all rows. Real router would size up on high-confidence LLM agreement."
    )
    lines.append(
        "- **p_win not learned:** projection uses tier-derived prior. Real router will use `spot_aware_priors.SpotAwarePriors.lookup`."
    )
    lines.append("- **Taker slippage assumed 1¢ flat.** Real cost is 1-2¢ depending on book depth.")
    lines.append(
        "- **Win/loss outcomes are HISTORICAL** (frozen). Size shaping doesn't change whether a window resolved UP or DOWN; it only scales the dollar PnL."
    )
    lines.append("")
    lines.append("## How to interpret")
    lines.append("")
    lines.append(
        "- **If net delta is POSITIVE** → the size shaping captures more on winners than it loses on losers, even before LLM and regime sharpening. The 7-day soak should improve this."
    )
    lines.append(
        "- **If net delta is NEGATIVE** → first-cut confidence weights are mis-calibrated. Tune `W_DET / W_TIER / W_REG / W_LLM / W_KELLY` and re-run the audit before any code ships."
    )
    lines.append(
        "- **The avg router size** tells us if the confidence math is doing anything: $5 means everything got the floor; $30 means everything got the cap; healthy is ~$12-$18."
    )
    lines.append("")
    lines.append("## Sub-phase status")
    lines.append("")
    lines.append("- ✅ 16.B.1 — counterfactual audit (this doc)")
    lines.append("- ⏳ 16.B.2 — design doc lock at `design/phase-16b-every-window-mode.md`")
    lines.append("- ⏳ 16.B.3 — router primitives + `sizing.py` + tests")
    lines.append("- ⏳ 16.B.4 — wire into EnsembleWrapper behind `EVERY_WINDOW_MODE=false`")
    lines.append("- ⏳ 16.B.5 — dark deploy + 24h shadow mode")
    lines.append("- ⏳ 16.B.6 — 7-day soak gate → PROMOTE or ROLLBACK")
    lines.append("")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines))
    print(f"wrote {OUTPUT_PATH}")
    print(f"  n_settled = {n}")
    print(f"  actual PnL = ${total_actual:+.2f}")
    print(f"  router projected PnL = ${total_proj:+.2f}")
    print(f"  net Δ = ${delta:+.2f}")
    print(f"  avg router size = ${avg_router_size:.2f}")
    print(f"  new fills (taker fallback) = {fills_new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

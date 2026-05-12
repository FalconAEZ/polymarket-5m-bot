"""One-shot study: where is v2's edge inside the May 8-12 production data.

Reads state/decisions/*.jsonl, applies truth-correction overlay
(settled_correction overrides settled.pnl_usd by decision_id), then
stratifies v2 fires by:

    1. tier (the price-tier of the entry — same buckets as
       PRICE_TIER_BUCKETS in dashboard/loaders.py)
    2. delta_bps bucket (|Δ| = |spot - oracle| in basis points)
    3. p_win prior bucket (from the priors table)
    4. side (UP / DOWN)
    5. hour-of-day (UTC)
    6. fill class (taker_at_fire / maker_at_settle / no_fill)
    7. spot direction (BTC moving UP or DOWN during the fire window)

Includes simple Wilson-CI floor on WR for stat-significance flag.

v2 here means: rationale matches `strategy=spot_aware_v2` (which also
captures the inheritance-bug v3 fires from before commit 74f7541 — only
one such fire in the dataset at 13:35:16 UTC 2026-05-12; not material to
the conclusion).

Goal: find subgroups within v2 where WR is materially below 50% so we
can propose tighter filters (a "v2.1" iteration).

Usage:
    uv run python -u scripts/study_v2_edge.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS_DIR = ROOT / "state" / "decisions"

# Same buckets as dashboard/loaders.PRICE_TIER_BUCKETS, derived from price_limit
TIER_BUCKETS: list[tuple[float, float, str]] = [
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
]

DELTA_BUCKETS_BPS: list[tuple[float, float, str]] = [
    (-1000, -20, "≤-20"),
    (-20, -10, "[-20,-10)"),
    (-10, -5, "[-10,-5)"),
    (-5, -2, "[-5,-2)"),
    (-2, 0, "[-2,0)"),
    (0, 2, "[0,2)"),
    (2, 5, "[2,5)"),
    (5, 10, "[5,10)"),
    (10, 20, "[10,20)"),
    (20, 1000, "≥20"),
]

P_WIN_BUCKETS: list[tuple[float, float, str]] = [
    (0.00, 0.40, "<0.40"),
    (0.40, 0.50, "[0.40,0.50)"),
    (0.50, 0.55, "[0.50,0.55)"),
    (0.55, 0.60, "[0.55,0.60)"),
    (0.60, 0.70, "[0.60,0.70)"),
    (0.70, 1.01, "≥0.70"),
]

EV_BUCKETS: list[tuple[float, float, str]] = [
    (-1.0, 0.01, "<0.01"),
    (0.01, 0.03, "[0.01,0.03)"),
    (0.03, 0.05, "[0.03,0.05)"),
    (0.05, 0.10, "[0.05,0.10)"),
    (0.10, 0.20, "[0.10,0.20)"),
    (0.20, 1.0, "≥0.20"),
]

# Parse the rationale string for delta_bps / p_win / ev tokens.
RE_DELTA = re.compile(r"delta_bps=([+-]?\d+\.?\d*)")
RE_PWIN = re.compile(r"p_win=([+-]?\d+\.?\d*)")
RE_EV = re.compile(r"ev=([+-]?\d+\.?\d*)")


def bucket_of(buckets, value):
    for lo, hi, label in buckets:
        if lo <= value < hi:
            return label
    return "?"


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    """95% Wilson lower bound on WR (proportion)."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return max(0.0, (center - margin) / denom)


def load_records() -> tuple[list[dict], list[dict], dict[str, float]]:
    fired = []
    settled = []
    correction = {}
    for path in sorted(DECISIONS_DIR.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = r.get("kind")
                if kind == "fired":
                    fired.append(r)
                elif kind == "settled":
                    settled.append(r)
                elif kind == "settled_correction":
                    did = r.get("decision_id")
                    pnl = r.get("corrected_pnl_usd")
                    if isinstance(did, str) and isinstance(pnl, int | float):
                        correction[did] = float(pnl)
    return fired, settled, correction


def main() -> int:
    fired, settled, correction = load_records()

    # Join: build settled-by-id map with truth-corrected pnl
    settled_by_id = {}
    for s in settled:
        did = s.get("decision_id")
        if not isinstance(did, str):
            continue
        naive = s.get("pnl_usd", 0.0)
        truth = correction.get(did, naive) if isinstance(naive, int | float) else 0.0
        settled_by_id[did] = {**s, "truth_pnl": float(truth)}

    # Filter to v2 fires (rationale contains "strategy=spot_aware_v2")
    v2_fires = [
        f
        for f in fired
        if isinstance(f.get("rationale"), str) and "strategy=spot_aware_v2" in f["rationale"]
    ]

    # Join with settled, dropping fires that haven't settled
    v2_joined = []
    for f in v2_fires:
        did = f.get("decision_id")
        s = settled_by_id.get(did)
        if s is None:
            continue
        rat = f["rationale"]
        d_m = RE_DELTA.search(rat)
        p_m = RE_PWIN.search(rat)
        e_m = RE_EV.search(rat)
        delta = float(d_m.group(1)) if d_m else 0.0
        p_win = float(p_m.group(1)) if p_m else 0.0
        ev = float(e_m.group(1)) if e_m else 0.0
        side = f.get("side")
        f.get("size_usd", 5.0)
        snap = f.get("snapshot") or {}
        spot_now = snap.get("spot_now")
        win_open = snap.get("window_open_spot")
        truth_pnl = s["truth_pnl"]
        # bucket for spot direction during fire (price moving UP or DOWN within window)
        spot_dir = "?"
        if isinstance(spot_now, int | float) and isinstance(win_open, int | float) and win_open > 0:
            ret_bps = (spot_now - win_open) / win_open * 10000
            if ret_bps > 5:
                spot_dir = "UP_strong"
            elif ret_bps > 0:
                spot_dir = "UP_weak"
            elif ret_bps > -5:
                spot_dir = "DOWN_weak"
            else:
                spot_dir = "DOWN_strong"
        # tier from price_limit
        plim = f.get("price_limit")
        if isinstance(plim, int | float):
            tier = bucket_of(TIER_BUCKETS, plim)
        else:
            tier = "?"
        # fill class
        fired_fill = f.get("fill")
        settle_fill = s.get("fill_at_settle")
        if fired_fill is not None:
            fill_class = "taker_at_fire"
        elif settle_fill is not None:
            fill_class = "maker_at_settle"
        else:
            fill_class = "no_fill"
        # hour of day from fire ts
        ts_ns = f.get("decision_ts_ns") or 0
        hour = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC).hour if ts_ns else -1
        v2_joined.append(
            {
                "tier": tier,
                "delta_bucket": bucket_of(DELTA_BUCKETS_BPS, delta),
                "p_win_bucket": bucket_of(P_WIN_BUCKETS, p_win),
                "ev_bucket": bucket_of(EV_BUCKETS, ev),
                "side": side,
                "hour": hour,
                "fill_class": fill_class,
                "spot_dir": spot_dir,
                "delta_bps": delta,
                "p_win": p_win,
                "ev": ev,
                "truth_pnl": truth_pnl,
            }
        )

    n = len(v2_joined)
    if n == 0:
        print("NO v2 fires found in data")
        return 1

    total_pnl = sum(r["truth_pnl"] for r in v2_joined)
    wins = sum(1 for r in v2_joined if r["truth_pnl"] > 0)
    losses = sum(1 for r in v2_joined if r["truth_pnl"] < 0)
    zeros = sum(1 for r in v2_joined if r["truth_pnl"] == 0)
    settled_n = wins + losses
    wr = (wins / settled_n) if settled_n else 0.0

    print(f"=== v2 universe: {n} joined fires (May 8-12 truth-corrected) ===")
    print(f"  W/L/Z = {wins}/{losses}/{zeros}")
    print(f"  WR (W/(W+L)) = {wr*100:.1f}%")
    print(f"  total truth PnL = ${total_pnl:+.2f}")
    print(f"  per-trade avg = ${total_pnl/n:+.4f}")
    print()

    def summarize(label: str, dimension_key: str, sort_key=None):
        buckets = defaultdict(list)
        for r in v2_joined:
            buckets[r[dimension_key]].append(r["truth_pnl"])
        rows = []
        for k, pnls in buckets.items():
            n_total = len(pnls)
            n_w = sum(1 for p in pnls if p > 0)
            n_l = sum(1 for p in pnls if p < 0)
            n_z = sum(1 for p in pnls if p == 0)
            wr_b = (n_w / (n_w + n_l)) if (n_w + n_l) else 0
            wl = wilson_lower(n_w, n_w + n_l) if (n_w + n_l) else 0
            pnl_sum = sum(pnls)
            per_trade = pnl_sum / n_total
            rows.append((k, n_total, n_w, n_l, n_z, wr_b, wl, pnl_sum, per_trade))
        if sort_key:
            rows.sort(key=sort_key)
        print(f"=== {label} ===")
        print(
            f"  {'bucket':<14} {'n':>4} {'W':>3} {'L':>3} {'Z':>3}   WR    WR-lo95   total$    /trade"
        )
        print(f"  {'-'*14} {'-'*4} {'-'*3} {'-'*3} {'-'*3} {'-'*5} {'-'*8} {'-'*9} {'-'*8}")
        for k, n_t, n_w, n_l, n_z, wr_b, wl, pnl_sum, per_trade in rows:
            flag = ""
            if (n_w + n_l) >= 30 and wr_b < 0.50:
                flag = " *LOSER*"
            elif (n_w + n_l) >= 30 and wr_b >= 0.55:
                flag = " *winner*"
            print(
                f"  {k!s:<14} {n_t:>4} {n_w:>3} {n_l:>3} {n_z:>3} {wr_b*100:>4.1f}% {wl*100:>6.1f}% {pnl_sum:>+9.2f} {per_trade:>+8.3f}{flag}"
            )
        print()

    summarize("v2 by TIER", "tier")
    summarize("v2 by DELTA_BPS bucket", "delta_bucket")
    summarize("v2 by P_WIN prior", "p_win_bucket")
    summarize("v2 by EV bucket", "ev_bucket")
    summarize("v2 by SIDE", "side")
    summarize("v2 by FILL class", "fill_class")
    summarize("v2 by SPOT direction in window", "spot_dir")
    summarize("v2 by HOUR-of-day (UTC)", "hour", sort_key=lambda r: r[0])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

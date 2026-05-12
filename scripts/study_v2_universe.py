"""Study: edge analysis on the v2-eligible universe across May 8-12.

The 17-fire v2-tagged subset is too small for sub-group inference. To get
a bigger meaningful sample, this script applies v2's gate criteria to
EVERY fire in the dataset and analyzes the qualifying subset:

  - delta_bps in [5, 50] (v2's defaults)
  - ev >= 0.005 ($0.005 per share)
  - tier in {15-30%, 30-50%, 70-85%} (v2's allowed tiers; 50-70% +
    85-100% explicitly rejected; <15% has small sample but allowed
    structurally)
  - p_win parseable (not the v1 aggressive p_win=0.54 fallback)

This simulates "what if v2 had been running the whole time on these
fires" and lets us find sub-group winners/losers with n large enough
to mean something.

Truth-corrected PnL throughout (settled_correction overrides naive).

Usage:
    uv run python -u scripts/study_v2_universe.py
"""

# ruff: noqa: E741

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS_DIR = ROOT / "state" / "decisions"

TIER_BUCKETS = [
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),  # v2 rejects
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),  # v2 rejects
]

DELTA_BUCKETS = [
    (5, 7, "[5,7)"),
    (7, 10, "[7,10)"),
    (10, 15, "[10,15)"),
    (15, 25, "[15,25)"),
    (25, 1000, "≥25"),
    (-7, -5, "[-7,-5)"),
    (-10, -7, "[-10,-7)"),
    (-15, -10, "[-15,-10)"),
    (-25, -15, "[-25,-15)"),
    (-1000, -25, "≤-25"),
]

P_WIN_BUCKETS = [
    (0.00, 0.40, "<0.40"),
    (0.40, 0.50, "[0.40,0.50)"),
    (0.50, 0.60, "[0.50,0.60)"),
    (0.60, 0.70, "[0.60,0.70)"),
    (0.70, 0.85, "[0.70,0.85)"),
    (0.85, 1.01, "≥0.85"),
]

EV_BUCKETS = [
    (0.005, 0.02, "[0.005,0.02)"),
    (0.02, 0.05, "[0.02,0.05)"),
    (0.05, 0.10, "[0.05,0.10)"),
    (0.10, 0.20, "[0.10,0.20)"),
    (0.20, 1.0, "≥0.20"),
]

V2_REJECTED_TIERS = {"50-70%", "85-100%"}

RE_DELTA = re.compile(r"delta_bps=([+-]?\d+\.?\d*)")
RE_PWIN = re.compile(r"p_win=([+-]?\d+\.?\d*)")
RE_EV = re.compile(r"ev=([+-]?\d+\.?\d*)")
RE_STRAT = re.compile(r"strategy=(\w+)(?:\s+mode=(\w+))?")


def bucket(buckets, v):
    for lo, hi, label in buckets:
        if lo <= v < hi:
            return label
    return "?"


def wilson_lo(w, n, z=1.96):
    if n == 0:
        return 0.0
    p = w / n
    denom = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return max(0.0, (center - margin) / denom)


def load():
    fires, settled, correction = [], [], {}
    for p in sorted(DECISIONS_DIR.glob("*.jsonl")):
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = r.get("kind")
                if k == "fired":
                    fires.append(r)
                elif k == "settled":
                    settled.append(r)
                elif k == "settled_correction":
                    did = r.get("decision_id")
                    pnl = r.get("corrected_pnl_usd")
                    if isinstance(did, str) and isinstance(pnl, int | float):
                        correction[did] = float(pnl)
    return fires, settled, correction


def summarize(label, rows_by_bucket):
    """rows_by_bucket: dict[label] = list of truth_pnl floats"""
    print(f"=== {label} ===")
    print(
        f"  {'bucket':<14} {'n':>4} {'W':>3} {'L':>3} {'Z':>3}   WR    WR-lo95   total$    /trade   flag"
    )
    print("  " + "-" * 86)
    rows = []
    for k, pnls in rows_by_bucket.items():
        n = len(pnls)
        w = sum(1 for p in pnls if p > 0)
        l = sum(1 for p in pnls if p < 0)
        z = sum(1 for p in pnls if p == 0)
        wr = w / (w + l) if (w + l) else 0
        wl = wilson_lo(w, w + l) if (w + l) else 0
        tot = sum(pnls)
        pt = tot / n if n else 0
        rows.append((k, n, w, l, z, wr, wl, tot, pt))
    rows.sort(key=lambda r: (-r[1],))  # sort by n desc
    for k, n, w, l, z, wr, wl, tot, pt in rows:
        flag = ""
        if (w + l) >= 30:
            if wr < 0.45:
                flag = "*LOSER*"
            elif wl > 0.52:
                flag = "*WINNER*"
            elif wr < 0.50:
                flag = "marginal-loser"
        print(
            f"  {k!s:<14} {n:>4} {w:>3} {l:>3} {z:>3} {wr*100:>4.1f}% {wl*100:>6.1f}% {tot:>+9.2f} {pt:>+8.3f}   {flag}"
        )
    print()


def main():
    fires, settled, correction = load()

    settled_by_id = {}
    for s in settled:
        did = s.get("decision_id")
        if not did:
            continue
        naive = s.get("pnl_usd", 0.0) or 0.0
        truth = correction.get(did, naive)
        settled_by_id[did] = float(truth)

    # v2-eligible filter
    eligible = []
    for f in fires:
        rat = f.get("rationale") or ""
        d_m = RE_DELTA.search(rat)
        p_m = RE_PWIN.search(rat)
        e_m = RE_EV.search(rat)
        s_m = RE_STRAT.search(rat)
        # Need delta + p_win + ev parseable
        if not (d_m and p_m and e_m):
            continue
        delta = float(d_m.group(1))
        p_win = float(p_m.group(1))
        ev = float(e_m.group(1))
        strat = s_m.group(1) if s_m else "?"
        # v2 gates:
        if abs(delta) < 5 or abs(delta) > 50:
            continue
        if ev < 0.005:
            continue
        # v1 aggressive's fallback p_win=0.54 is NOT a real priors hit
        if abs(p_win - 0.54) < 1e-6:
            continue  # synthetic fallback, v2 rejects these
        plim = f.get("price_limit")
        if not isinstance(plim, int | float):
            continue
        tier = bucket(TIER_BUCKETS, plim)
        if tier in V2_REJECTED_TIERS:
            continue
        pnl = settled_by_id.get(f.get("decision_id"))
        if pnl is None:
            continue
        side = f.get("side")
        snap = f.get("snapshot") or {}
        spot_now = snap.get("spot_now")
        win_open = snap.get("window_open_spot")
        spot_dir = "?"
        if isinstance(spot_now, int | float) and isinstance(win_open, int | float) and win_open > 0:
            r_bps = (spot_now - win_open) / win_open * 10000
            if r_bps > 5:
                spot_dir = "UP_strong"
            elif r_bps > 0:
                spot_dir = "UP_weak"
            elif r_bps > -5:
                spot_dir = "DOWN_weak"
            else:
                spot_dir = "DOWN_strong"
        ts_ns = f.get("decision_ts_ns", 0)
        hour = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC).hour if ts_ns else -1
        eligible.append(
            {
                "tier": tier,
                "delta_bucket": bucket(DELTA_BUCKETS, delta),
                "delta_signed": "Δ>0" if delta > 0 else "Δ<0",
                "p_win_bucket": bucket(P_WIN_BUCKETS, p_win),
                "ev_bucket": bucket(EV_BUCKETS, ev),
                "side": side,
                "hour": hour,
                "spot_dir": spot_dir,
                "strat": strat,
                "pnl": pnl,
            }
        )

    n = len(eligible)
    w = sum(1 for r in eligible if r["pnl"] > 0)
    l = sum(1 for r in eligible if r["pnl"] < 0)
    tot = sum(r["pnl"] for r in eligible)
    print("=== v2-ELIGIBLE UNIVERSE (truth-corrected, May 8-12) ===")
    print(f"  n = {n}, W={w}, L={l}, WR = {(w/(w+l))*100:.1f}%")
    print(f"  total PnL = ${tot:+.2f}, per-trade = ${tot/n:+.4f}")
    print()
    print("  Strategy provenance:")
    from collections import Counter

    sc = Counter(r["strat"] for r in eligible)
    for k, c in sc.most_common():
        print(f"    {c:>4}  {k}")
    print()
    print("  (These are fires that would have passed v2's gates regardless")
    print("  of which strategy actually ran them. wide_fire fires that")
    print("  happened to have delta_bps>=5 + ev>=0.005 + good tier are INCLUDED")
    print("  because they're informationally equivalent to v2 fires.)")
    print()

    for dim in [
        ("tier", "TIER"),
        ("delta_bucket", "DELTA_BPS bucket"),
        ("delta_signed", "DELTA sign"),
        ("p_win_bucket", "P_WIN bucket"),
        ("ev_bucket", "EV bucket"),
        ("side", "SIDE"),
        ("spot_dir", "SPOT direction in window"),
        ("hour", "HOUR-of-day (UTC)"),
    ]:
        by = defaultdict(list)
        for r in eligible:
            by[r[dim[0]]].append(r["pnl"])
        summarize(f"by {dim[1]}", dict(by))


if __name__ == "__main__":
    raise SystemExit(main())

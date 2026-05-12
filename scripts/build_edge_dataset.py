"""Phase G — build a single-row-per-fire dataset of every fire in
state/decisions/*.jsonl, stratified by 17 dimensions and truth-corrected
via settled_correction overlay.

This is the spine of the Phase G full-edge-discovery study. The output
parquet/csv feeds the analysis script (analyze_edge_full.py) and the
PDF builder (pdfs/build_phase_g_edge_discovery_pdf.py).

Dimensions computed per fire:

    decision_id           — join key
    decision_ts_ns        — fire timestamp
    settled_ts_ns         — settle timestamp (None if pending)
    settle_latency_s      — (settled - decision) / 1e9
    day                   — UTC date string
    hour_utc              — 0-23
    weekday               — 0=Mon … 6=Sun
    strategy              — spot_aware | spot_aware_v2 | spot_aware_v3 |
                            wide_fire | other (from rationale)
    mode                  — aggressive | tier_restricted | ensemble_base | ?
    side                  — UP / DOWN
    price_limit           — Polymarket implied prob at fire
    tier                  — <15% / 15-30% / 30-50% / 50-70% / 70-85% / 85-100%
    delta_bps             — signed Δ from rationale
    delta_sign            — Δ>0 / Δ<0 / Δ=0
    delta_abs_bucket      — [5,7) / [7,10) / [10,15) / [15,25) / ≥25
    p_win                 — from rationale (None for wide_fire)
    p_win_bucket          — bucketed
    ev                    — from rationale (None for wide_fire)
    ev_bucket             — bucketed
    spot_now              — from snapshot
    window_open_spot      — from snapshot
    window_ret_bps        — (spot_now - window_open_spot) / window_open_spot * 1e4
    spot_dir              — UP_strong / UP_weak / DOWN_weak / DOWN_strong
    best_bid              — from snapshot
    best_ask              — from snapshot
    ba_spread             — best_ask - best_bid
    ask_size_top          — from snapshot (None = no depth attested)
    has_depth_attested    — ask_size_top is not None
    oracle_last           — from snapshot
    fired_fill_present    — bool
    settle_fill_present   — bool
    fill_class            — taker_at_fire / maker_at_settle / no_fill /
                            phantom_corrected
    has_correction        — bool
    pnl_naive             — settled.pnl_usd
    pnl_truth             — corrected_pnl_usd if correction else pnl_usd
    win                   — pnl_truth > 0
    loss                  — pnl_truth < 0
    v2_eligible           — would have passed v2's gates (synthetic flag)

Usage:
    uv run python -u scripts/build_edge_dataset.py
    uv run python -u scripts/build_edge_dataset.py --out state/research/phase-G-fires-dataset.csv
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISIONS_DIR = ROOT / "state" / "decisions"

RE_STRAT = re.compile(r"strategy=(\w+)(?:\s+mode=(\w+))?")
RE_DELTA = re.compile(r"delta_bps=([+-]?\d+\.?\d*)")
RE_PWIN = re.compile(r"p_win=([+-]?\d+\.?\d*)")
RE_EV = re.compile(r"ev=([+-]?\d+\.?\d*)")


def tier_of(p: float | None) -> str:
    if p is None:
        return "?"
    if p < 0.15:
        return "<15%"
    if p < 0.30:
        return "15-30%"
    if p < 0.50:
        return "30-50%"
    if p < 0.70:
        return "50-70%"
    if p < 0.85:
        return "70-85%"
    return "85-100%"


def delta_abs_bucket(d: float) -> str:
    a = abs(d)
    if a < 5:
        return "<5"
    if a < 7:
        return "[5,7)"
    if a < 10:
        return "[7,10)"
    if a < 15:
        return "[10,15)"
    if a < 25:
        return "[15,25)"
    return "≥25"


def p_win_bucket(p: float | None) -> str:
    if p is None:
        return "?"
    if p < 0.40:
        return "<0.40"
    if p < 0.50:
        return "[0.40,0.50)"
    if p < 0.55:
        return "[0.50,0.55)"
    if p < 0.60:
        return "[0.55,0.60)"
    if p < 0.70:
        return "[0.60,0.70)"
    return "≥0.70"


def ev_bucket(e: float | None) -> str:
    if e is None:
        return "?"
    if e < 0.005:
        return "<0.005"
    if e < 0.02:
        return "[0.005,0.02)"
    if e < 0.05:
        return "[0.02,0.05)"
    if e < 0.10:
        return "[0.05,0.10)"
    if e < 0.20:
        return "[0.10,0.20)"
    return "≥0.20"


def spot_dir_of(ret_bps: float | None) -> str:
    if ret_bps is None:
        return "?"
    if ret_bps > 10:
        return "UP_strong"
    if ret_bps > 0:
        return "UP_weak"
    if ret_bps > -10:
        return "DOWN_weak"
    return "DOWN_strong"


def parse_rationale(rat: str | None) -> dict[str, object]:
    out = {"strategy": "?", "mode": "?", "delta_bps": None, "p_win": None, "ev": None}
    if not rat:
        return out
    if m := RE_STRAT.search(rat):
        out["strategy"] = m.group(1)
        out["mode"] = m.group(2) or "?"
    if m := RE_DELTA.search(rat):
        out["delta_bps"] = float(m.group(1))
    if m := RE_PWIN.search(rat):
        out["p_win"] = float(m.group(1))
    if m := RE_EV.search(rat):
        out["ev"] = float(m.group(1))
    return out


def is_v2_eligible(
    strategy: str,
    mode: str,
    delta_bps: float | None,
    p_win: float | None,
    ev: float | None,
    tier: str,
) -> bool:
    """Would this fire have passed v2's gate criteria?"""
    if delta_bps is None or ev is None or p_win is None:
        return False
    if abs(delta_bps) < 5 or abs(delta_bps) > 50:
        return False
    if ev < 0.005:
        return False
    if abs(p_win - 0.54) < 1e-6:
        # v1's aggressive fallback p_win — v2 rejects
        return False
    if tier in {"50-70%", "85-100%"}:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions-dir", type=Path, default=DECISIONS_DIR)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "state" / "research" / "phase-G-fires-dataset.csv"
    )
    args = parser.parse_args()

    fires, settled, correction = [], [], {}
    for p in sorted(args.decisions_dir.glob("*.jsonl")):
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

    # settled by id (latest wins if multiple)
    settled_by_id: dict[str, dict] = {}
    for s in settled:
        did = s.get("decision_id")
        if isinstance(did, str):
            settled_by_id[did] = s

    rows: list[dict[str, object]] = []
    for f in fires:
        did = f.get("decision_id")
        if not isinstance(did, str):
            continue
        ts_ns = f.get("decision_ts_ns") or 0
        if not isinstance(ts_ns, int):
            continue
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)
        rat = f.get("rationale")
        parsed = parse_rationale(rat if isinstance(rat, str) else None)
        plim = f.get("price_limit")
        tier = tier_of(plim if isinstance(plim, int | float) else None)
        snap = f.get("snapshot") or {}
        spot_now = snap.get("spot_now")
        win_open = snap.get("window_open_spot")
        ret_bps = None
        if isinstance(spot_now, int | float) and isinstance(win_open, int | float) and win_open > 0:
            ret_bps = (spot_now - win_open) / win_open * 1e4
        best_bid = snap.get("best_bid")
        best_ask = snap.get("best_ask")
        ba_spread = None
        if isinstance(best_bid, int | float) and isinstance(best_ask, int | float):
            ba_spread = best_ask - best_bid
        ask_top = snap.get("ask_size_top")
        # fill class
        fired_fill = f.get("fill")
        s_rec = settled_by_id.get(did)
        settle_fill = (s_rec or {}).get("fill_at_settle")
        if fired_fill is not None:
            fill_class = "taker_at_fire"
        elif settle_fill is not None:
            fill_class = "maker_at_settle"
        else:
            fill_class = "no_fill"
        has_corr = did in correction
        if has_corr:
            fill_class = "phantom_corrected"
        pnl_naive = None
        pnl_truth = None
        settled_ts = None
        settle_latency = None
        if s_rec is not None:
            pn = s_rec.get("pnl_usd", 0.0)
            pnl_naive = float(pn) if isinstance(pn, int | float) else 0.0
            pnl_truth = correction.get(did, pnl_naive)
            sts = s_rec.get("settled_ts_ns")
            if isinstance(sts, int):
                settled_ts = sts
                settle_latency = (sts - ts_ns) / 1e9
        d_b = parsed["delta_bps"]
        v2_elig = is_v2_eligible(
            parsed["strategy"], parsed["mode"], d_b, parsed["p_win"], parsed["ev"], tier
        )
        delta_sign = "?"
        if isinstance(d_b, int | float):
            if d_b > 0:
                delta_sign = "Δ>0"
            elif d_b < 0:
                delta_sign = "Δ<0"
            else:
                delta_sign = "Δ=0"
        rows.append(
            {
                "decision_id": did,
                "decision_ts_ns": ts_ns,
                "settled_ts_ns": settled_ts,
                "settle_latency_s": settle_latency,
                "day": dt.strftime("%Y-%m-%d"),
                "hour_utc": dt.hour,
                "weekday": dt.weekday(),
                "strategy": parsed["strategy"],
                "mode": parsed["mode"],
                "side": f.get("side"),
                "price_limit": plim,
                "tier": tier,
                "delta_bps": d_b,
                "delta_sign": delta_sign,
                "delta_abs_bucket": delta_abs_bucket(d_b) if isinstance(d_b, int | float) else "?",
                "p_win": parsed["p_win"],
                "p_win_bucket": p_win_bucket(parsed["p_win"]),
                "ev": parsed["ev"],
                "ev_bucket": ev_bucket(parsed["ev"]),
                "spot_now": spot_now,
                "window_open_spot": win_open,
                "window_ret_bps": ret_bps,
                "spot_dir": spot_dir_of(ret_bps),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "ba_spread": ba_spread,
                "ask_size_top": ask_top,
                "has_depth_attested": ask_top is not None,
                "oracle_last": snap.get("oracle_last"),
                "fired_fill_present": fired_fill is not None,
                "settle_fill_present": settle_fill is not None,
                "fill_class": fill_class,
                "has_correction": has_corr,
                "pnl_naive": pnl_naive,
                "pnl_truth": pnl_truth,
                "win": pnl_truth is not None and pnl_truth > 0,
                "loss": pnl_truth is not None and pnl_truth < 0,
                "v2_eligible": v2_elig,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fieldnames = list(rows[0].keys())
        with args.out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    print(f"wrote {len(rows)} fires to {args.out}")
    # quick verification
    n_settled = sum(1 for r in rows if r["pnl_truth"] is not None)
    n_w = sum(1 for r in rows if r["win"])
    n_l = sum(1 for r in rows if r["loss"])
    print(
        f"  settled: {n_settled}  W={n_w} L={n_l}  WR={n_w/(n_w+n_l)*100:.1f}%"
        if (n_w + n_l)
        else ""
    )
    print(f"  total truth PnL: ${sum((r['pnl_truth'] or 0) for r in rows):+.2f}")
    # by strategy
    from collections import Counter

    by_strat = Counter()
    for r in rows:
        by_strat[r["strategy"]] += 1
    print("  by strategy:")
    for k, n in by_strat.most_common():
        print(f"    {n:>4}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

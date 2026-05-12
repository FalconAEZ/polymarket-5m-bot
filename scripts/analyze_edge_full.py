"""Phase G — full edge analysis on the Phase-G fires dataset.

Reads state/research/phase-G-fires-dataset.csv (produced by
scripts/build_edge_dataset.py), runs:

  Item 3: time journey (per-day, per-hour cumulative PnL)
  Item 4: 17 single-dimension breakdowns (with Wilson 95% lower-bound flags)
  Item 5: 7 cross-tabs + counterfactual replay
  Item 6: v_next filter spec (computed from Items 4-5)
  Item 7: Monte Carlo 7d/30d/90d bankroll trajectories

Outputs:
  state/research/phase-G-analysis.json — structured findings
  state/research/phase-G-edge-discovery-2026-05-12.md — markdown report
  state/research/phase-G-charts/*.png — matplotlib charts for PDF
  stdout — progress + headlines

Usage:
    uv run --with matplotlib --with numpy python -u scripts/analyze_edge_full.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001

from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "state" / "research" / "phase-G-fires-dataset.csv"
ANALYSIS_DIR = ROOT / "state" / "research"
CHART_DIR = ROOT / "state" / "research" / "phase-G-charts"


def load_rows() -> list[dict]:
    out = []
    with DATA.open() as f:
        for r in csv.DictReader(f):
            # type-coerce
            for k in ("decision_ts_ns", "settled_ts_ns"):
                r[k] = int(r[k]) if r[k] else None
            for k in (
                "settle_latency_s",
                "price_limit",
                "delta_bps",
                "p_win",
                "ev",
                "spot_now",
                "window_open_spot",
                "window_ret_bps",
                "best_bid",
                "best_ask",
                "ba_spread",
                "ask_size_top",
                "oracle_last",
                "pnl_naive",
                "pnl_truth",
            ):
                v = r[k]
                r[k] = float(v) if v not in ("", "None") else None
            for k in ("hour_utc", "weekday"):
                r[k] = int(r[k])
            for k in (
                "has_depth_attested",
                "fired_fill_present",
                "settle_fill_present",
                "has_correction",
                "win",
                "loss",
                "v2_eligible",
            ):
                r[k] = r[k] == "True"
            out.append(r)
    return out


def wilson_lower(w: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = w / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - margin) / denom)


def summarize_dimension(rows: list[dict], key: str) -> list[dict]:
    """Return list of {bucket, n, n_settled, W, L, Z, WR, WR_lo95, total_pnl, per_trade, flag}."""
    by = defaultdict(list)
    for r in rows:
        v = r.get(key)
        by[str(v)].append(r)
    out = []
    for k, sub in by.items():
        n = len(sub)
        w = sum(1 for r in sub if r["win"])
        l = sum(1 for r in sub if r["loss"])
        z = sum(1 for r in sub if r["pnl_truth"] is not None and not r["win"] and not r["loss"])
        wr = w / (w + l) if (w + l) else 0.0
        wl = wilson_lower(w, w + l) if (w + l) else 0.0
        tot = sum((r["pnl_truth"] or 0) for r in sub)
        per_trade = tot / n if n else 0.0
        flag = ""
        if (w + l) >= 30:
            if wr < 0.45:
                flag = "LOSER"
            elif wl > 0.52:
                flag = "WINNER"
            elif wr < 0.50:
                flag = "marginal-loser"
            elif wr > 0.50:
                flag = "marginal-winner"
        elif (w + l) >= 10:
            flag = "small-n"
        else:
            flag = "underpowered"
        out.append(
            {
                "bucket": k,
                "n": n,
                "settled": w + l + z,
                "W": w,
                "L": l,
                "Z": z,
                "WR": round(wr * 100, 1),
                "WR_lo95": round(wl * 100, 1),
                "total_pnl": round(tot, 2),
                "per_trade": round(per_trade, 4),
                "flag": flag,
            }
        )
    out.sort(key=lambda r: -r["n"])
    return out


def crosstab(rows: list[dict], k1: str, k2: str) -> dict[tuple[str, str], dict]:
    cells = defaultdict(list)
    for r in rows:
        cells[(str(r[k1]), str(r[k2]))].append(r)
    out = {}
    for (a, b), sub in cells.items():
        n = len(sub)
        w = sum(1 for r in sub if r["win"])
        l = sum(1 for r in sub if r["loss"])
        wr = w / (w + l) if (w + l) else 0
        tot = sum((r["pnl_truth"] or 0) for r in sub)
        pt = tot / n if n else 0
        out[(a, b)] = {
            "n": n,
            "W": w,
            "L": l,
            "WR": round(wr * 100, 1),
            "pnl": round(tot, 2),
            "per_trade": round(pt, 4),
        }
    return out


def main() -> int:
    rows = load_rows()
    print(f"loaded {len(rows)} fires")
    settled = [r for r in rows if r["pnl_truth"] is not None]
    n_w = sum(1 for r in settled if r["win"])
    n_l = sum(1 for r in settled if r["loss"])
    print(
        f"settled: {len(settled)}  WR={n_w/(n_w+n_l)*100:.1f}%  total=${sum(r['pnl_truth'] for r in settled):+.2f}"
    )

    findings = {
        "metadata": {
            "generated": datetime.now(UTC).isoformat(),
            "n_fires": len(rows),
            "n_settled": len(settled),
            "wr": round(n_w / (n_w + n_l), 4) if (n_w + n_l) else 0,
            "wr_lo95": round(wilson_lower(n_w, n_w + n_l), 4),
            "total_truth_pnl": round(sum(r["pnl_truth"] for r in settled), 2),
            "per_trade": round(sum(r["pnl_truth"] for r in settled) / len(settled), 4)
            if settled
            else 0,
        },
        "dimensions": {},
        "crosstabs": {},
        "time_journey": {},
        "counterfactuals": {},
        "v_next": {},
        "monte_carlo": {},
    }

    # ITEM 4 — single-dim breakdowns
    print("\n=== Item 4: single-dimension breakdowns ===")
    dims = [
        ("strategy", "Strategy"),
        ("mode", "Mode"),
        ("tier", "Tier"),
        ("delta_abs_bucket", "|Δ_bps| bucket"),
        ("delta_sign", "Δ sign"),
        ("p_win_bucket", "p_win prior"),
        ("ev_bucket", "EV bucket"),
        ("side", "Side"),
        ("fill_class", "Fill class"),
        ("spot_dir", "Spot direction during window"),
        ("hour_utc", "Hour of day (UTC)"),
        ("weekday", "Weekday (0=Mon)"),
        ("has_depth_attested", "Depth attested at fire"),
        ("v2_eligible", "v2-eligible"),
        ("day", "Day"),
        ("has_correction", "Has phantom correction"),
    ]
    for key, _name in dims:
        rows_dim = summarize_dimension(rows, key)
        findings["dimensions"][key] = rows_dim
        # quick stdout headline: top winner + worst loser
        winners = [r for r in rows_dim if r["flag"] == "WINNER"]
        losers = [r for r in rows_dim if r["flag"] == "LOSER"]
        print(
            f"  {_name:<32}  buckets={len(rows_dim)}  winners={len(winners)} losers={len(losers)}"
        )
        for r in winners[:2]:
            print(
                f"     WIN:   {r['bucket']:<14} n={r['settled']} WR={r['WR']}% pnl=${r['total_pnl']:+.2f} /trade=${r['per_trade']:+.3f}"
            )
        for r in losers[:2]:
            print(
                f"     LOSE:  {r['bucket']:<14} n={r['settled']} WR={r['WR']}% pnl=${r['total_pnl']:+.2f} /trade=${r['per_trade']:+.3f}"
            )

    # ITEM 5 — cross-tabs
    print("\n=== Item 5: cross-tabs ===")
    ctabs = [
        ("tier", "delta_abs_bucket"),
        ("strategy", "hour_utc"),
        ("strategy", "tier"),
        ("side", "spot_dir"),
        ("fill_class", "tier"),
        ("hour_utc", "delta_sign"),
        ("p_win_bucket", "ev_bucket"),
    ]
    for k1, k2 in ctabs:
        ct = crosstab(rows, k1, k2)
        findings["crosstabs"][f"{k1}_x_{k2}"] = [
            {"a": a, "b": b, **v} for (a, b), v in ct.items() if v["n"] >= 5
        ]
        # find best cell by per_trade with n>=10
        best = sorted(
            [((a, b), v) for (a, b), v in ct.items() if v["n"] >= 10],
            key=lambda x: -x[1]["per_trade"],
        )[:3]
        worst = sorted(
            [((a, b), v) for (a, b), v in ct.items() if v["n"] >= 10],
            key=lambda x: x[1]["per_trade"],
        )[:3]
        print(f"  {k1} × {k2}:")
        for (a, b), v in best:
            print(
                f"     BEST:  {a:<14}/{b:<14}  n={v['n']} WR={v['WR']}% /trade=${v['per_trade']:+.3f}"
            )
        for (a, b), v in worst:
            print(
                f"     WORST: {a:<14}/{b:<14}  n={v['n']} WR={v['WR']}% /trade=${v['per_trade']:+.3f}"
            )

    # ITEM 3 — time journey
    print("\n=== Item 3: per-day journey ===")
    by_day = defaultdict(list)
    for r in settled:
        by_day[r["day"]].append(r)
    day_rows = []
    cum = 0.0
    for day in sorted(by_day):
        sub = by_day[day]
        n = len(sub)
        w = sum(1 for r in sub if r["win"])
        l = sum(1 for r in sub if r["loss"])
        wr = w / (w + l) * 100 if (w + l) else 0
        tot = sum(r["pnl_truth"] for r in sub)
        cum += tot
        strats = Counter(r["strategy"] for r in sub).most_common(1)[0][0]
        modes = Counter(r["mode"] for r in sub).most_common(1)[0][0]
        day_rows.append(
            {
                "day": day,
                "n": n,
                "W": w,
                "L": l,
                "WR": round(wr, 1),
                "day_pnl": round(tot, 2),
                "cum_pnl": round(cum, 2),
                "dominant_strategy": f"{strats}:{modes}",
            }
        )
        print(
            f"  {day}  n={n:>3} WR={wr:>4.1f}%  day=${tot:>+8.2f}  cum=${cum:>+8.2f}  {strats}:{modes}"
        )
    findings["time_journey"]["by_day"] = day_rows

    # ITEM 5 (counterfactuals)
    print("\n=== Item 5: counterfactuals ===")
    counter = {}
    # v2-eligible counterfactual: only count fires that would've passed v2
    v2_settled = [r for r in settled if r["v2_eligible"]]
    counter["v2_only"] = {
        "n": len(v2_settled),
        "W": sum(1 for r in v2_settled if r["win"]),
        "L": sum(1 for r in v2_settled if r["loss"]),
        "pnl": round(sum(r["pnl_truth"] for r in v2_settled), 2),
        "per_trade": round(sum(r["pnl_truth"] for r in v2_settled) / len(v2_settled), 4)
        if v2_settled
        else 0,
    }
    print(
        f"  v2-only universe:  n={counter['v2_only']['n']}  WR={counter['v2_only']['W']/(counter['v2_only']['W']+counter['v2_only']['L'])*100:.1f}%  pnl=${counter['v2_only']['pnl']:+.2f}  /trade=${counter['v2_only']['per_trade']:+.4f}"
    )

    # Cross-tab winners-only: take top quartile cells from tier×delta and replay
    ct_td = crosstab(settled, "tier", "delta_abs_bucket")
    big_cells = [(k, v) for k, v in ct_td.items() if v["n"] >= 10]
    big_cells.sort(key=lambda x: -x[1]["per_trade"])
    top_quartile_count = max(1, len(big_cells) // 4)
    top_keys = set(k for k, v in big_cells[:top_quartile_count])
    top_q_settled = [r for r in settled if (r["tier"], r["delta_abs_bucket"]) in top_keys]
    counter["top_quartile_tier_x_delta"] = {
        "cells_kept": [
            {"tier": k[0], "delta": k[1], **v} for k, v in big_cells[:top_quartile_count]
        ],
        "n": len(top_q_settled),
        "W": sum(1 for r in top_q_settled if r["win"]),
        "L": sum(1 for r in top_q_settled if r["loss"]),
        "pnl": round(sum(r["pnl_truth"] for r in top_q_settled), 2),
        "per_trade": round(sum(r["pnl_truth"] for r in top_q_settled) / len(top_q_settled), 4)
        if top_q_settled
        else 0,
    }
    print(
        f"  top-quartile tier×Δ:  n={counter['top_quartile_tier_x_delta']['n']}  pnl=${counter['top_quartile_tier_x_delta']['pnl']:+.2f}  /trade=${counter['top_quartile_tier_x_delta']['per_trade']:+.4f}"
    )
    print(f"    cells kept: {top_keys}")

    findings["counterfactuals"] = counter

    # ITEM 6 — v_next filter spec heuristic
    # Pick the dimensions whose WINNER buckets we'd ADD as filters,
    # and LOSER buckets we'd EXCLUDE.
    v_next = {"add_gates": [], "drop_gates": [], "keep_gates": [], "notes": []}
    for key, _name in dims:
        d = findings["dimensions"].get(key, [])
        for r in d:
            if r["flag"] == "LOSER":
                v_next["drop_gates"].append(
                    {
                        "dim": key,
                        "bucket": r["bucket"],
                        "n": r["settled"],
                        "WR": r["WR"],
                        "pnl": r["total_pnl"],
                        "rule": f"skip when {key} == {r['bucket']}",
                    }
                )
            elif r["flag"] == "WINNER":
                v_next["add_gates"].append(
                    {
                        "dim": key,
                        "bucket": r["bucket"],
                        "n": r["settled"],
                        "WR": r["WR"],
                        "pnl": r["total_pnl"],
                        "rule": f"prefer/require {key} == {r['bucket']}",
                    }
                )
    findings["v_next"] = v_next

    # ITEM 7 — Monte Carlo
    # If we deploy v_next (top-quartile tier×Δ), use its (μ, σ) for daily PnL
    print("\n=== Item 7: Monte Carlo projection (top-quartile filter) ===")
    cf = counter["top_quartile_tier_x_delta"]
    pt_mu = cf["per_trade"]
    # fires/day estimate from top_q over 5-day span
    n_days = max(1, len(by_day))
    fires_per_day = cf["n"] / n_days
    daily_mu = pt_mu * fires_per_day
    # daily sigma estimate: per-trade std on the top-q subset
    pnls_topq = [r["pnl_truth"] for r in top_q_settled]
    if len(pnls_topq) > 1:
        m = sum(pnls_topq) / len(pnls_topq)
        var = sum((p - m) ** 2 for p in pnls_topq) / (len(pnls_topq) - 1)
        per_trade_sd = math.sqrt(var)
    else:
        per_trade_sd = 5.0
    # daily sd = per_trade_sd * sqrt(fires_per_day)
    daily_sd = per_trade_sd * math.sqrt(max(1, fires_per_day))

    print(f"  per_trade_mu = ${pt_mu:+.4f}")
    print(f"  per_trade_sd = ${per_trade_sd:.4f}")
    print(f"  fires_per_day = {fires_per_day:.2f}")
    print(f"  daily_mu = ${daily_mu:+.4f}")
    print(f"  daily_sd = ${daily_sd:.4f}")

    def mc(horizon_days: int, n_traj: int = 10000, start: float = 1006.01) -> dict:
        random.seed(42)
        finals = []
        hits_2k = 0
        for _ in range(n_traj):
            b = start
            for _d in range(horizon_days):
                b += random.gauss(daily_mu, daily_sd)
            finals.append(b)
            if b >= 2000:
                hits_2k += 1
        finals.sort()

        def pctile(p):
            return finals[int(p * len(finals))]

        return {
            "horizon_days": horizon_days,
            "n_traj": n_traj,
            "median": round(pctile(0.50), 2),
            "p10": round(pctile(0.10), 2),
            "p25": round(pctile(0.25), 2),
            "p75": round(pctile(0.75), 2),
            "p90": round(pctile(0.90), 2),
            "p_2k": round(hits_2k / n_traj, 4),
        }

    mc_results = {h: mc(h) for h in (7, 14, 30, 90)}
    findings["monte_carlo"] = mc_results
    print("\n  Bankroll projections (start $1006.01):")
    for h, m in mc_results.items():
        print(
            f"    +{h:>3}d: median=${m['median']:.0f}  p10/p90=${m['p10']:.0f}/${m['p90']:.0f}  P($2k)={m['p_2k']*100:.1f}%"
        )

    # write findings
    out_json = ANALYSIS_DIR / "phase-G-analysis.json"
    with out_json.open("w") as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"\nwrote {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# ruff: noqa: RUF001 -- output uses unicode (delta, x-times) for readability
"""Edge-discovery audit — multi-dimensional slicing of all paper-trading
data since bot start, plus what-if filtered backtests.

Reads state/staging/decisions/*.jsonl (PM-truth resolved). Output goes to
stdout; the operator captures it for a research write-up.

What this answers:
  1. HIGHS + LOWS since bot start (peak/trough cumulative, best/worst
     hour, day, single trade)
  2. SLICES across |delta_bps| x tier x p_win x hour-of-day x side
  3. WHAT-IF filtered backtests: counterfactual PnL if we'd applied
     various filters retroactively
  4. EDGE THESIS: where the edge actually lives in the data
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_DIR = REPO_ROOT / "state/staging/decisions"


def parse_rationale(rationale: str) -> dict[str, Any]:
    """Extract delta_bps, p_win, ev, mode from the rationale string."""
    out: dict[str, Any] = {"delta_bps": None, "p_win": None, "ev": None, "mode": None}
    if "mode=aggressive" in rationale:
        out["mode"] = "aggressive"
    else:
        out["mode"] = "spot_aware"
    for key, regex in [
        ("delta_bps", r"delta_bps=([-+]?[\d.]+)"),
        ("p_win", r"p_win=([\d.]+)"),
        ("ev", r"ev=([-+]?[\d.]+)"),
    ]:
        m = re.search(regex, rationale)
        if m:
            try:
                out[key] = float(m.group(1))
            except (TypeError, ValueError):
                pass
    return out


def tier_bucket(price_limit: float | None) -> str:
    if price_limit is None:
        return "?"
    if price_limit < 0.15:
        return "<15"
    if price_limit < 0.30:
        return "15-30"
    if price_limit < 0.50:
        return "30-50"
    if price_limit < 0.70:
        return "50-70"
    if price_limit < 0.85:
        return "70-85"
    return "85+"


def delta_bucket(d: float | None) -> str:
    if d is None:
        return "?"
    a = abs(d)
    if a < 2:
        return "0-2"
    if a < 5:
        return "2-5"
    if a < 10:
        return "5-10"
    if a < 20:
        return "10-20"
    return "20+"


def pwin_bucket(p: float | None) -> str:
    if p is None:
        return "?"
    if p < 0.55:
        return "[0.50,0.55)"
    if p < 0.60:
        return "[0.55,0.60)"
    if p < 0.70:
        return "[0.60,0.70)"
    return "[0.70+]"


# ---- load ----
fired: list[dict[str, Any]] = []
settled: dict[str, dict[str, Any]] = {}
for p in sorted(DECISIONS_DIR.glob("*.jsonl")):
    if p.suffix == ".bak":
        continue
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "fired":
            fired.append(r)
        elif r.get("kind") == "settled":
            settled[r["decision_id"]] = r

# ---- enrich ----
trades: list[dict[str, Any]] = []
for f in fired:
    s = settled.get(f["decision_id"]) or {}
    rat = parse_rationale(f.get("rationale", ""))
    pnl = s.get("pnl_usd")
    fill = s.get("fill_at_settle")
    is_filled = bool(fill)
    is_settled = bool(s)
    is_won = pnl is not None and pnl > 0
    is_lost = pnl is not None and pnl < 0
    trades.append(
        {
            "did": f["decision_id"],
            "ts": dt.datetime.fromtimestamp(f["decision_ts_ns"] / 1e9, tz=dt.UTC),
            "window_ts": f["window_ts"],
            "side": f["side"],
            "size_usd": f["size_usd"],
            "price_limit": f["price_limit"],
            "tier": tier_bucket(f["price_limit"]),
            "delta_bps": rat["delta_bps"],
            "delta_abs": abs(rat["delta_bps"]) if rat["delta_bps"] is not None else None,
            "delta_bkt": delta_bucket(rat["delta_bps"]),
            "p_win": rat["p_win"],
            "p_win_bkt": pwin_bucket(rat["p_win"]),
            "ev": rat["ev"],
            "mode": rat["mode"],
            "filled": is_filled,
            "settled": is_settled,
            "pnl": pnl if pnl is not None else 0.0,
            "won": is_won,
            "lost": is_lost,
            "resolution": s.get("resolution"),
            "fill_price": (fill or {}).get("price_filled"),
        }
    )

trades.sort(key=lambda t: t["ts"])

now = dt.datetime.now(tz=dt.UTC)


def fmt_pnl(x: float) -> str:
    return f"${x:+.2f}"


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    n_filled = sum(1 for r in rows if r["filled"])
    n_settled = sum(1 for r in rows if r["settled"])
    n_won = sum(1 for r in rows if r["won"])
    n_lost = sum(1 for r in rows if r["lost"])
    pnl = sum(r["pnl"] for r in rows)
    wr_denom = n_won + n_lost
    wr = (100.0 * n_won / wr_denom) if wr_denom else 0.0
    avg_pnl_per_settled_fill = (pnl / wr_denom) if wr_denom else 0.0
    return {
        "n": n,
        "filled": n_filled,
        "settled": n_settled,
        "won": n_won,
        "lost": n_lost,
        "wr_pct": wr,
        "wr_denom": wr_denom,
        "pnl": pnl,
        "pnl_per_trade": avg_pnl_per_settled_fill,
    }


def print_stats(label: str, rows: list[dict[str, Any]], width: int = 38) -> None:
    s = stats(rows)
    pp = f"{s['pnl_per_trade']:+.3f}"
    print(
        f"  {label:<{width}}  n={s['n']:>3d} filled={s['filled']:>3d}  "
        f"WR={s['wr_pct']:>5.1f}% (n={s['wr_denom']:>3d})  "
        f"pnl={fmt_pnl(s['pnl']):>9s}  per={pp:>7s}"
    )


# ============================================================
print("=" * 80)
print("EDGE-DISCOVERY AUDIT — Phase 11.A.2 mid-soak")
print(f"  generated: {now.isoformat()}")
print(f"  data: {len(fired)} fires / {len(settled)} settled")
print(f"  span: {trades[0]['ts'].isoformat()} -> {trades[-1]['ts'].isoformat()}")
print(f"  elapsed: {(trades[-1]['ts'] - trades[0]['ts']).total_seconds() / 3600:.2f}h")
print("=" * 80)

# ============================================================
print("\n[1] AGGREGATE BASELINE (everything)")
print("-" * 80)
print_stats("ALL TRADES", trades)
print_stats("AGGRESSIVE-MODE ONLY", [t for t in trades if t["mode"] == "aggressive"])
print_stats("PRE-AGGRESSIVE (loose-start)", [t for t in trades if t["mode"] != "aggressive"])

# ============================================================
print("\n[2] HIGHS + LOWS (cumulative PnL trajectory)")
print("-" * 80)
cum = 0.0
peak = (0.0, None)
trough = (0.0, None)
trajectory: list[tuple[dt.datetime, float]] = []
for t in trades:
    cum += t["pnl"]
    trajectory.append((t["ts"], cum))
    if cum > peak[0]:
        peak = (cum, t)
    if cum < trough[0]:
        trough = (cum, t)
print(
    f"  PEAK cumulative PnL:   {fmt_pnl(peak[0])} at {peak[1]['ts'].isoformat() if peak[1] else 'n/a'}"
)
print(
    f"  TROUGH cumulative PnL: {fmt_pnl(trough[0])} at {trough[1]['ts'].isoformat() if trough[1] else 'n/a'}"
)
print(f"  CURRENT cumulative:    {fmt_pnl(cum)}")
print(f"  Drawdown from peak:    {fmt_pnl(cum - peak[0])}")

# Best / worst single trades
trades_with_pnl = [t for t in trades if t["pnl"] != 0]
best = max(trades_with_pnl, key=lambda r: r["pnl"])
worst = min(trades_with_pnl, key=lambda r: r["pnl"])
print(
    f"\n  BEST single trade:  {fmt_pnl(best['pnl'])}  side={best['side']} tier={best['tier']} Δ={best['delta_bps']:+.1f}bps p_win={best['p_win']:.2f}  {best['ts'].isoformat()}"
)
print(
    f"  WORST single trade: {fmt_pnl(worst['pnl'])}  side={worst['side']} tier={worst['tier']} Δ={worst['delta_bps']:+.1f}bps p_win={worst['p_win']:.2f}  {worst['ts'].isoformat()}"
)

# Best / worst hour
by_hour: dict[str, float] = defaultdict(float)
hour_n: dict[str, int] = defaultdict(int)
for t in trades:
    h = t["ts"].strftime("%Y-%m-%d %H")
    by_hour[h] += t["pnl"]
    hour_n[h] += 1
best_h = max(by_hour.items(), key=lambda kv: kv[1])
worst_h = min(by_hour.items(), key=lambda kv: kv[1])
print(f"\n  BEST hour:  {best_h[0]} UTC  pnl={fmt_pnl(best_h[1])} ({hour_n[best_h[0]]} fires)")
print(f"  WORST hour: {worst_h[0]} UTC  pnl={fmt_pnl(worst_h[1])} ({hour_n[worst_h[0]]} fires)")

# Best / worst day
by_day: dict[str, float] = defaultdict(float)
day_n: dict[str, int] = defaultdict(int)
for t in trades:
    d = t["ts"].strftime("%Y-%m-%d")
    by_day[d] += t["pnl"]
    day_n[d] += 1
print("\n  Per-UTC-day PnL:")
for d in sorted(by_day):
    print(f"    {d}  pnl={fmt_pnl(by_day[d]):>9s}  fires={day_n[d]}")

# Streaks
cur_streak = 0
best_win = 0
worst_loss = 0
for t in trades_with_pnl:
    if t["won"]:
        cur_streak = max(1, cur_streak + 1) if cur_streak >= 0 else 1
    elif t["lost"]:
        cur_streak = min(-1, cur_streak - 1) if cur_streak <= 0 else -1
    best_win = max(best_win, cur_streak)
    worst_loss = min(worst_loss, cur_streak)
print(f"\n  Best win streak:  {best_win}")
print(f"  Worst loss streak: {abs(worst_loss)}")

# ============================================================
print("\n[3] PER-TIER (the bedrock slice)")
print("-" * 80)
for tier in ["15-30", "30-50", "50-70", "70-85"]:
    rows = [t for t in trades if t["tier"] == tier]
    if rows:
        print_stats(f"tier {tier}%", rows)

# ============================================================
print("\n[4] PER-|Δ_bps| MAGNITUDE (does delta size predict edge?)")
print("-" * 80)
for bkt in ["0-2", "2-5", "5-10", "10-20", "20+"]:
    rows = [t for t in trades if t["delta_bkt"] == bkt]
    if rows:
        print_stats(f"|Δ| {bkt} bps", rows)

# ============================================================
print("\n[5] |Δ_bps| × tier CROSS-TAB (the headline cross-cut)")
print("-" * 80)
print(
    f"  {'tier↓ Δbkt→':12s}  {'0-2':>16s}  {'2-5':>16s}  {'5-10':>16s}  {'10-20':>16s}  {'20+':>16s}"
)
for tier in ["15-30", "30-50", "50-70", "70-85"]:
    cells = [f"  {'tier ' + tier:12s}"]
    for bkt in ["0-2", "2-5", "5-10", "10-20", "20+"]:
        rows = [t for t in trades if t["tier"] == tier and t["delta_bkt"] == bkt]
        if rows:
            s = stats(rows)
            wr = s["wr_pct"]
            cells.append(f"  n={s['wr_denom']:>2d} WR={wr:>4.0f}%{fmt_pnl(s['pnl']):>5s}")
        else:
            cells.append(f"  {'-':>16s}")
    print("".join(cells))

# ============================================================
print("\n[6] PER-p_win BUCKET (does the priors table actually predict?)")
print("-" * 80)
for bkt in ["[0.50,0.55)", "[0.55,0.60)", "[0.60,0.70)", "[0.70+]"]:
    rows = [t for t in trades if t["p_win_bkt"] == bkt]
    if rows:
        print_stats(f"p_win {bkt}", rows)

# ============================================================
print("\n[7] PER-SIDE (UP vs DOWN imbalance?)")
print("-" * 80)
for side in ["UP", "DOWN"]:
    rows = [t for t in trades if t["side"] == side]
    if rows:
        print_stats(f"side {side}", rows)

# ============================================================
print("\n[8] WHAT-IF FILTERED BACKTESTS (counterfactual PnL)")
print("-" * 80)
filters = [
    ("baseline (no filter)", lambda t: True),
    ("|Δ| ≥ 5  (loose-start floor)", lambda t: (t["delta_abs"] or 0) >= 5),
    ("|Δ| ≥ 8  (design-doc default)", lambda t: (t["delta_abs"] or 0) >= 8),
    ("|Δ| ≥ 10 (tighter floor)", lambda t: (t["delta_abs"] or 0) >= 10),
    ("EV ≥ 0   (positive-EV only)", lambda t: (t["ev"] or 0) > 0),
    ("EV ≥ 0.005 (design-doc EV floor)", lambda t: (t["ev"] or 0) >= 0.005),
    ("tier 30-50 ONLY", lambda t: t["tier"] == "30-50"),
    ("tier 30-50 + 50-70", lambda t: t["tier"] in ("30-50", "50-70")),
    ("tier 30-50 + |Δ| ≥ 5", lambda t: t["tier"] == "30-50" and (t["delta_abs"] or 0) >= 5),
    ("tier 30-50 + |Δ| ≥ 8", lambda t: t["tier"] == "30-50" and (t["delta_abs"] or 0) >= 8),
    ("tier 30-50 + EV ≥ 0", lambda t: t["tier"] == "30-50" and (t["ev"] or 0) > 0),
    ("p_win ≥ 0.55", lambda t: (t["p_win"] or 0) >= 0.55),
    ("p_win ≥ 0.60", lambda t: (t["p_win"] or 0) >= 0.60),
    ("tier 30-50 + p_win ≥ 0.55", lambda t: t["tier"] == "30-50" and (t["p_win"] or 0) >= 0.55),
    ("DROP tier 50-70 (the drag)", lambda t: t["tier"] != "50-70"),
    (
        "KEEP only |Δ|≥5 AND p_win≥0.55 AND EV>0",
        lambda t: (t["delta_abs"] or 0) >= 5 and (t["p_win"] or 0) >= 0.55 and (t["ev"] or 0) > 0,
    ),
]
for label, fn in filters:
    rows = [t for t in trades if fn(t)]
    print_stats(label, rows, width=42)

# ============================================================
print("\n[9] BUCKET BY HOUR-OF-DAY (UTC, any cyclical pattern?)")
print("-" * 80)
hour_pnl: dict[int, float] = defaultdict(float)
hour_n_settled: dict[int, int] = defaultdict(int)
hour_won: dict[int, int] = defaultdict(int)
hour_lost: dict[int, int] = defaultdict(int)
for t in trades:
    h = t["ts"].hour
    hour_pnl[h] += t["pnl"]
    if t["won"]:
        hour_won[h] += 1
    if t["lost"]:
        hour_lost[h] += 1
    hour_n_settled[h] += 1
for h in range(24):
    n_settled = hour_won[h] + hour_lost[h]
    wr = (100.0 * hour_won[h] / n_settled) if n_settled else 0.0
    bar = "+" * max(0, int(hour_pnl[h] * 2)) + "-" * max(0, int(-hour_pnl[h] * 2))
    print(
        f"  hour {h:02d}:00  n={hour_n_settled[h]:>3d} settled-fills={n_settled:>3d} WR={wr:>5.1f}%  pnl={fmt_pnl(hour_pnl[h]):>8s}  {bar[:40]}"
    )

# ============================================================
print("\n[10] EV-IS-A-LIE CHECK (does ev marker correlate with outcome?)")
print("-" * 80)
ev_buckets = [
    ("EV negative", lambda t: t["ev"] is not None and t["ev"] < 0),
    ("EV in [0, 0.02)", lambda t: t["ev"] is not None and 0 <= t["ev"] < 0.02),
    ("EV in [0.02, 0.05)", lambda t: t["ev"] is not None and 0.02 <= t["ev"] < 0.05),
    ("EV in [0.05, 0.10)", lambda t: t["ev"] is not None and 0.05 <= t["ev"] < 0.10),
    ("EV ≥ 0.10", lambda t: t["ev"] is not None and t["ev"] >= 0.10),
]
for label, fn in ev_buckets:
    rows = [t for t in trades if fn(t)]
    if rows:
        print_stats(label, rows, width=22)

# ============================================================
print("\n[11] FILL-QUALITY (entry vs limit slippage)")
print("-" * 80)
filled = [t for t in trades if t["filled"] and t["fill_price"] is not None]
print(f"  filled trades: {len(filled)}")
slips = []
for t in filled:
    slip = t["fill_price"] - t["price_limit"]  # negative = better than limit
    slips.append(slip)
if slips:
    slips_sorted = sorted(slips)
    n = len(slips_sorted)
    print("  fill_price - price_limit (cents):")
    print(f"    p10  {slips_sorted[int(n*0.1)]*100:+.2f}¢")
    print(f"    p50  {slips_sorted[n//2]*100:+.2f}¢")
    print(f"    p90  {slips_sorted[int(n*0.9)]*100:+.2f}¢")
    print(f"    mean {(sum(slips)/n)*100:+.2f}¢")

print("\n" + "=" * 80)
print("END OF EDGE-DISCOVERY AUDIT")
print("=" * 80)

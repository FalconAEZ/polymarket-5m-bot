"""Investigate the +$133.88 -> ~$0 swing on 2026-05-09 starting at 05:30 UTC.

Splits the data at the peak timestamp and compares pre/post by:
  * per-hour PnL (where did the bleed start)
  * per-tier PnL (did tier mix shift)
  * per-side PnL (did UP vs DOWN flip)
  * per-|delta| PnL (did the delta distribution shift)
  * fire rate per side
  * BTC spot trajectory (regime change?)
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
    out: dict[str, Any] = {"delta_bps": None, "p_win": None, "ev": None}
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


def tier_bucket(price: float | None) -> str:
    if price is None:
        return "?"
    if price < 0.30:
        return "15-30"
    if price < 0.50:
        return "30-50"
    if price < 0.70:
        return "50-70"
    return "70-85"


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

trades = []
for f in fired:
    s = settled.get(f["decision_id"]) or {}
    rat = parse_rationale(f.get("rationale", ""))
    pnl = s.get("pnl_usd") or 0.0
    snap = f.get("snapshot") or {}
    trades.append(
        {
            "ts": dt.datetime.fromtimestamp(f["decision_ts_ns"] / 1e9, tz=dt.UTC),
            "side": f["side"],
            "tier": tier_bucket(f.get("price_limit")),
            "price_limit": f.get("price_limit"),
            "delta_bps": rat["delta_bps"] or 0.0,
            "p_win": rat["p_win"] or 0.0,
            "ev": rat["ev"] or 0.0,
            "pnl": pnl,
            "won": pnl > 0,
            "lost": pnl < 0,
            "spot_now": snap.get("spot_now"),
            "window_open_spot": snap.get("window_open_spot"),
        }
    )

trades.sort(key=lambda t: t["ts"])

# ---- find peak ----
cum = 0.0
peak_pnl = 0.0
peak_idx = -1
for i, t in enumerate(trades):
    cum += t["pnl"]
    if cum > peak_pnl:
        peak_pnl = cum
        peak_idx = i

peak_ts = trades[peak_idx]["ts"] if peak_idx >= 0 else None
print(f"PEAK at index {peak_idx}: cumulative=${peak_pnl:+.2f} at {peak_ts}")
print(f"FINAL cumulative: ${cum:+.2f}")
print(f"Drawdown from peak: ${cum - peak_pnl:+.2f}")
print(f"Trades pre-peak: {peak_idx + 1}")
print(f"Trades post-peak: {len(trades) - peak_idx - 1}")
print()

pre = trades[: peak_idx + 1]
post = trades[peak_idx + 1 :]


def stats_block(label: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        print(f"  {label}: (empty)")
        return
    n = len(rows)
    won = sum(1 for r in rows if r["won"])
    lost = sum(1 for r in rows if r["lost"])
    pnl = sum(r["pnl"] for r in rows)
    wr = 100.0 * won / max(won + lost, 1)
    avg_pnl = pnl / max(won + lost, 1)
    print(
        f"  {label:30s} n={n:3d} WR={wr:5.1f}% (n={won + lost:3d}) PnL=${pnl:+8.2f} avg=${avg_pnl:+.3f}"
    )


print("=" * 78)
print("AGGREGATE pre vs post peak")
print("=" * 78)
stats_block("PRE-PEAK (winning period)", pre)
stats_block("POST-PEAK (losing period)", post)
print()

print("=" * 78)
print("PER-TIER: pre vs post peak")
print("=" * 78)
for tier in ["15-30", "30-50", "50-70", "70-85"]:
    pre_t = [r for r in pre if r["tier"] == tier]
    post_t = [r for r in post if r["tier"] == tier]
    if not pre_t and not post_t:
        continue
    print(f"  --- tier {tier}% ---")
    stats_block("    pre", pre_t)
    stats_block("    post", post_t)
print()

print("=" * 78)
print("PER-SIDE: pre vs post peak")
print("=" * 78)
for side in ["UP", "DOWN"]:
    pre_s = [r for r in pre if r["side"] == side]
    post_s = [r for r in post if r["side"] == side]
    print(f"  --- side {side} ---")
    stats_block("    pre", pre_s)
    stats_block("    post", post_s)
print()

print("=" * 78)
print("PER-|DELTA| BUCKET: pre vs post peak")
print("=" * 78)


def dbkt(d: float) -> str:
    a = abs(d)
    if a < 1:
        return "0-1"
    if a < 2:
        return "1-2"
    if a < 5:
        return "2-5"
    if a < 10:
        return "5-10"
    return "10+"


for bkt in ["0-1", "1-2", "2-5", "5-10", "10+"]:
    pre_b = [r for r in pre if dbkt(r["delta_bps"]) == bkt]
    post_b = [r for r in post if dbkt(r["delta_bps"]) == bkt]
    if not pre_b and not post_b:
        continue
    print(f"  --- |Δ| {bkt} bps ---")
    stats_block("    pre", pre_b)
    stats_block("    post", post_b)
print()

print("=" * 78)
print("HOURLY PnL TRAJECTORY around the peak")
print("=" * 78)
by_hour: dict[str, list[dict[str, Any]]] = defaultdict(list)
for t in trades:
    by_hour[t["ts"].strftime("%Y-%m-%d %H:00 UTC")].append(t)

cum = 0.0
print(f"  {'hour':22s} {'fires':>5s} {'WR':>6s} {'hr_pnl':>10s} {'cum_pnl':>10s}  marker")
print(f"  {'-'*22} {'-'*5} {'-'*6} {'-'*10} {'-'*10}  {'-'*8}")
for h in sorted(by_hour):
    rows = by_hour[h]
    n = len(rows)
    won = sum(1 for r in rows if r["won"])
    lost = sum(1 for r in rows if r["lost"])
    wr = 100.0 * won / max(won + lost, 1)
    hr_pnl = sum(r["pnl"] for r in rows)
    cum += hr_pnl
    marker = ""
    if peak_ts and h == peak_ts.strftime("%Y-%m-%d %H:00 UTC"):
        marker = "<-- PEAK HERE"
    bar = ("+" * max(0, int(hr_pnl * 1.5))) if hr_pnl > 0 else ("-" * max(0, int(-hr_pnl * 1.5)))
    print(f"  {h:22s} {n:>5d} {wr:>5.1f}% ${hr_pnl:>+8.2f} ${cum:>+8.2f}  {marker}  {bar[:30]}")
print()

print("=" * 78)
print("BTC SPOT TRAJECTORY (sampled per hour)")
print("=" * 78)
spot_by_hour: dict[str, float] = {}
spot_first_by_hour: dict[str, float] = {}
for t in trades:
    h = t["ts"].strftime("%Y-%m-%d %H:00 UTC")
    if t["spot_now"]:
        spot_by_hour[h] = t["spot_now"]
        if h not in spot_first_by_hour:
            spot_first_by_hour[h] = t["spot_now"]

prev_close = None
for h in sorted(spot_first_by_hour):
    open_p = spot_first_by_hour[h]
    close_p = spot_by_hour[h]
    move_pct = 100.0 * (close_p - open_p) / open_p if open_p else 0
    move_h_pct = 100.0 * (close_p - prev_close) / prev_close if prev_close else 0
    marker = ""
    if peak_ts and h == peak_ts.strftime("%Y-%m-%d %H:00 UTC"):
        marker = "  <-- PEAK"
    print(
        f"  {h:22s} open=${open_p:>9,.0f} close=${close_p:>9,.0f} hr_move={move_h_pct:+6.2f}%{marker}"
    )
    prev_close = close_p
print()

print("=" * 78)
print("TIER MIX SHIFT (pct of fires in each tier, pre vs post)")
print("=" * 78)
for tier in ["15-30", "30-50", "50-70", "70-85"]:
    pre_n = sum(1 for r in pre if r["tier"] == tier)
    post_n = sum(1 for r in post if r["tier"] == tier)
    pre_pct = 100.0 * pre_n / max(len(pre), 1)
    post_pct = 100.0 * post_n / max(len(post), 1)
    delta = post_pct - pre_pct
    arrow = " ↑" if delta > 5 else (" ↓" if delta < -5 else "")
    print(
        f"  tier {tier:8s}  pre {pre_pct:5.1f}% (n={pre_n:3d})  post {post_pct:5.1f}% (n={post_n:3d})  Δ {delta:+5.1f}%{arrow}"
    )

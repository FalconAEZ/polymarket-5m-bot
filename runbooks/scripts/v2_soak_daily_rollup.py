"""Daily roll-up for the v2 7-day soak (Phase 3 of bot_v3_roadmap.md).

Designed to run once per UTC day during the v2 re-soak. Computes:
  * Daily PnL + WR
  * Per-tier PnL split (the test of whether v2's tier-restriction works)
  * Regime split (trending vs chop, using a simple proxy: hour-bucket
    rolling 5-min vol vs 10-min vol — placeholder until the proper
    regime detector lands in Phase 4)
  * Cumulative PnL since v2 deploy
  * Decision-source split (v2 fires vs leftover v1+aggressive fires)

Output goes to runbooks/gate-evidence/v2-soak-day-N.txt for the
operator to review at the end of the 7-day soak.

Usage (from repo root, after sync_staging.sh):
    uv run python runbooks/scripts/v2_soak_daily_rollup.py
    uv run python runbooks/scripts/v2_soak_daily_rollup.py --since 2026-05-09T21:14
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DECISIONS_DIR = REPO_ROOT / "state/staging/decisions"

# Default v2 deploy timestamp — first v2 fire after the gate-day deploy.
# Override via --since CLI arg.
DEFAULT_V2_DEPLOY_UTC = dt.datetime(2026, 5, 9, 21, 13, 50, tzinfo=dt.UTC)


def parse_rationale(rationale: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "delta_bps": None,
        "p_win": None,
        "ev": None,
        "strategy": "spot_aware",
        "mode": None,
    }
    m = re.search(r"strategy=(\w+)", rationale)
    if m:
        out["strategy"] = m.group(1)
    if "mode=aggressive" in rationale:
        out["mode"] = "aggressive"
    elif "mode=tier_restricted" in rationale:
        out["mode"] = "tier_restricted"
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
    """Classify a polymarket price into the v2 tier banding. Boundaries
    are inclusive on the lower edge: e.g., 0.50 belongs to "50-70", not
    "30-50". This matches the strategy's reject-band logic in
    spot_aware_v2._is_tier_rejected which checks ``lo <= price < hi``."""
    if price is None:
        return "?"
    if price < 0.30:
        return "15-30"
    if price < 0.50:
        return "30-50"
    if price < 0.70:
        return "50-70"
    return "70-85"


def _classify_fire_tier(fire: dict[str, Any], settled: dict[str, Any] | None) -> str:
    """Classify the tier this fire ACTUALLY traded in. Prefers fill price
    (the truth of the transaction); falls back to snapshot.best_ask
    (what the strategy decided against); falls back to price_limit (the
    worst-case ceiling — only relevant if neither fill nor ask is
    recorded). Audit 2026-05-10 fixed a misleading classification where
    price_limit=0.50 (a hard cap that protects against maker fills
    landing in the reject band) was mis-classified as a 50-70% tier
    fire even though the actual fill was at fill_price=0.481 in 30-50%."""
    fill = (fire.get("fill") or {}).get("price_filled")
    if fill is not None:
        return tier_bucket(float(fill))
    if settled is not None:
        s_fill = (settled.get("fill_at_settle") or {}).get("price_filled")
        if s_fill is not None:
            return tier_bucket(float(s_fill))
    snap = fire.get("snapshot") or {}
    ask = snap.get("best_ask")
    if ask is not None:
        return tier_bucket(float(ask))
    return tier_bucket(fire.get("price_limit"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily roll-up for v2 soak — see design/bot_v3_roadmap.md Phase 3."
    )
    parser.add_argument(
        "--since",
        type=str,
        default=DEFAULT_V2_DEPLOY_UTC.isoformat(),
        help="ISO timestamp; only fires after this are counted as v2 soak data.",
    )
    args = parser.parse_args()
    since = dt.datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.UTC)

    fired: list[dict[str, Any]] = []
    settled: dict[str, dict[str, Any]] = {}
    for p in sorted(DECISIONS_DIR.glob("*.jsonl")):
        if p.suffix == ".bak":
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            kind = r.get("kind")
            if kind == "fired":
                fired.append(r)
            elif kind == "settled":
                settled[r["decision_id"]] = r

    trades = []
    for f in fired:
        ts = dt.datetime.fromtimestamp(f["decision_ts_ns"] / 1e9, tz=dt.UTC)
        if ts < since:
            continue
        s = settled.get(f["decision_id"]) or {}
        rat = parse_rationale(f.get("rationale", ""))
        pnl = s.get("pnl_usd") or 0.0
        trades.append(
            {
                "ts": ts,
                "side": f["side"],
                "tier": _classify_fire_tier(f, s if s else None),
                "delta_bps": rat["delta_bps"] or 0.0,
                "ev": rat["ev"] or 0.0,
                "strategy": rat["strategy"],
                "mode": rat["mode"],
                "pnl": pnl,
                "won": pnl > 0,
                "lost": pnl < 0,
                "resolution_source": s.get("resolution_source"),
            }
        )
    trades.sort(key=lambda t: t["ts"])

    if not trades:
        print(
            f"No fires after {since.isoformat()}. v2 may not have fired yet (it's pickier than v1)."
        )
        return

    now = dt.datetime.now(tz=dt.UTC)
    elapsed_h = (now - since).total_seconds() / 3600

    print("=" * 78)
    print("V2 SOAK DAILY ROLL-UP")
    print(f"  generated:           {now.isoformat()}")
    print(f"  v2 deploy timestamp: {since.isoformat()}")
    print(f"  elapsed:             {elapsed_h:.1f}h ({elapsed_h / 24:.2f}d)")
    print(f"  fires since deploy:  {len(trades)}")
    print("=" * 78)

    n_won = sum(1 for t in trades if t["won"])
    n_lost = sum(1 for t in trades if t["lost"])
    pnl = sum(t["pnl"] for t in trades)
    wr_denom = n_won + n_lost
    wr = (100.0 * n_won / wr_denom) if wr_denom else 0.0
    avg_pnl = pnl / wr_denom if wr_denom else 0.0
    print("\n[1] AGGREGATE since v2 deploy")
    print(f"  fires:           {len(trades)}")
    print(f"  WR:              {wr:.1f}% (n={wr_denom} settled+filled)")
    print(f"  cumulative PnL:  ${pnl:+.2f}")
    print(f"  avg/trade:       ${avg_pnl:+.3f}")
    fire_rate_per_day = len(trades) * 24.0 / elapsed_h if elapsed_h > 0 else 0
    print(f"  fire rate:       {fire_rate_per_day:.0f}/day")

    print("\n[2] STRATEGY/MODE SPLIT (separates v2 fires from leftover v1+aggressive)")
    by_strategy: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_strategy[(t["strategy"], t["mode"])].append(t)
    for (strat, mode), rows in sorted(by_strategy.items()):
        won = sum(1 for r in rows if r["won"])
        lost = sum(1 for r in rows if r["lost"])
        rwr = (100.0 * won / max(won + lost, 1)) if (won + lost) else 0.0
        rpnl = sum(r["pnl"] for r in rows)
        print(
            f"  strategy={strat} mode={mode}  "
            f"n={len(rows):3d}  WR={rwr:5.1f}%  PnL=${rpnl:+8.2f}"
        )

    print("\n[3] PER-TIER (the test of v2's tier-restriction)")
    by_tier = defaultdict(list)
    for t in trades:
        by_tier[t["tier"]].append(t)
    for tier in ["15-30", "30-50", "50-70", "70-85"]:
        rows = by_tier.get(tier, [])
        if not rows:
            continue
        won = sum(1 for r in rows if r["won"])
        lost = sum(1 for r in rows if r["lost"])
        rwr = (100.0 * won / max(won + lost, 1)) if (won + lost) else 0.0
        rpnl = sum(r["pnl"] for r in rows)
        avg = rpnl / max(won + lost, 1) if (won + lost) else 0.0
        print(
            f"  tier {tier}%  n={len(rows):3d}  WR={rwr:5.1f}%  PnL=${rpnl:+8.2f}  avg=${avg:+.3f}"
        )
    if any(by_tier.get("50-70", [])):
        print("  WARNING: 50-70% tier should be ZERO under v2 — these are leftover v1 fires.")

    print("\n[4] PER-DAY (UTC)")
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_day[t["ts"].strftime("%Y-%m-%d")].append(t)
    cum = 0.0
    for d in sorted(by_day):
        rows = by_day[d]
        won = sum(1 for r in rows if r["won"])
        lost = sum(1 for r in rows if r["lost"])
        rwr = (100.0 * won / max(won + lost, 1)) if (won + lost) else 0.0
        rpnl = sum(r["pnl"] for r in rows)
        cum += rpnl
        print(f"  {d}  fires={len(rows):3d}  WR={rwr:5.1f}%  daily=${rpnl:+8.2f}  cum=${cum:+8.2f}")

    print("\n[5] RESOLUTION_SOURCE SPLIT (validates instant-settle is working)")
    by_source: dict[str | None, int] = defaultdict(int)
    for t in trades:
        by_source[t["resolution_source"]] += 1
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        label = "(none/legacy)" if src is None else src
        print(f"  resolution_source={label}  n={n}")

    print("\n[6] SOAK GATE PROGRESS (per Phase 3 of design/bot_v3_roadmap.md)")
    print("  Gate criteria:")
    if pnl > 5.0:
        print(f"    cumulative PnL > +$5         OK    (current ${pnl:+.2f})")
    elif pnl > -10.0:
        print(f"    marginal (within ±$10)        WATCH  (current ${pnl:+.2f})")
    else:
        print(f"    cumulative PnL < -$10         BREACH (current ${pnl:+.2f})")
    target_days = 7
    print(
        f"  Soak progress: {elapsed_h / 24:.2f}d / {target_days}d ({100 * elapsed_h / 24 / target_days:.0f}%)"
    )

    print()
    print("=" * 78)
    print("END OF V2 SOAK ROLL-UP")
    print("=" * 78)


if __name__ == "__main__":
    main()

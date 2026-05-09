"""Full-history audit for SpotAwareStrategy paper-soak (Phase 11.A.2 v2 prompt).

Reads state/staging/decisions/*.jsonl (Polymarket-truth resolved), buckets every
fired decision by config era (pre-aggressive vs aggressive — uses the
`mode=aggressive` rationale marker as the canonical boundary), and prints a
per-era + per-tier WR/PnL/fire-rate matrix. The output goes to
runbooks/gate-evidence/phase-11.a.2-full-history.txt via tee from the operator.

Why a separate audit instead of the v1 in-line snippet: the v1 script only
reports the aggressive window; the gate decision needs the BEFORE state too,
so an under-performing aggressive-window WR can be told apart from a
continuation of a pre-existing trend.

Usage (from repo root):
    uv run python runbooks/scripts/audit_spot_aware_history.py
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Aggressive-mode launch timestamp (canonical, per
# runbooks/decisions/aggressive-mode-2026-05-09.md hand-off).
AGGRESSIVE_LAUNCH = dt.datetime(2026, 5, 8, 22, 26, 15, tzinfo=dt.UTC)


def tier_bucket(price_limit: float | None) -> str:
    """Bucket a fire by its price_limit (proxy for tier)."""
    if price_limit is None:
        return "unknown"
    if price_limit < 0.15:
        return "00-15"
    if price_limit < 0.30:
        return "15-30"
    if price_limit < 0.50:
        return "30-50"
    if price_limit < 0.70:
        return "50-70"
    if price_limit < 0.85:
        return "70-85"
    return "85-100"


def era_of(rationale: str, ts_ns: int) -> str:
    """Bucket a fire into era. Prefers the explicit `mode=aggressive` marker
    in rationale; falls back to timestamp comparison vs AGGRESSIVE_LAUNCH for
    older decisions where the marker may have been absent."""
    if "mode=aggressive" in rationale:
        return "aggressive"
    if dt.datetime.fromtimestamp(ts_ns / 1e9, tz=dt.UTC) >= AGGRESSIVE_LAUNCH:
        return "aggressive"
    return "pre-aggressive"


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    decisions_dir = repo_root / "state/staging/decisions"

    fired: list[dict[str, Any]] = []
    settled: dict[str, dict[str, Any]] = {}

    for p in sorted(decisions_dir.glob("*.jsonl")):
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

    now = dt.datetime.now(dt.UTC)

    # First pass: header
    print("=" * 78)
    print("SpotAwareStrategy paper-soak — full-history audit")
    print(f"  generated: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  decisions: {decisions_dir}")
    print(f"  total fired: {len(fired)}")
    print(f"  total settled (matched): {len(settled)}")
    print(f"  aggressive launch: {AGGRESSIVE_LAUNCH.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(
        f"  elapsed since aggressive launch: "
        f"{(now - AGGRESSIVE_LAUNCH).total_seconds() / 3600:.2f}h"
    )
    print("=" * 78)

    # Per-era bucket
    by_era: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in fired:
        by_era[era_of(f["rationale"], f["decision_ts_ns"])].append(f)

    def report_era(era_name: str, fires: list[dict[str, Any]]) -> None:
        if not fires:
            print(f"\n  (no fires in era: {era_name})")
            return

        first_ts = min(f["decision_ts_ns"] for f in fires) / 1e9
        last_ts = max(f["decision_ts_ns"] for f in fires) / 1e9
        first_dt = dt.datetime.fromtimestamp(first_ts, tz=dt.UTC)
        last_dt = dt.datetime.fromtimestamp(last_ts, tz=dt.UTC)
        elapsed_h = (last_dt - first_dt).total_seconds() / 3600 or 0.001

        n_fires = len(fires)
        # Fill at settle: settled[did].fill_at_settle is non-null when filled.
        n_filled = sum(
            1 for f in fires if (settled.get(f["decision_id"]) or {}).get("fill_at_settle")
        )
        n_settled = sum(1 for f in fires if f["decision_id"] in settled)
        n_won = sum(
            1 for f in fires if ((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0) > 0
        )
        # Loss = filled+settled with pnl < 0; non-filled rows have pnl = 0 and
        # are not counted in WR denominator.
        n_lost = sum(
            1 for f in fires if ((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0) < 0
        )
        n_wr_denom = n_won + n_lost  # filled+settled trades only
        wr = (100.0 * n_won / n_wr_denom) if n_wr_denom else 0.0
        total_pnl = sum((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0 for f in fires)
        fire_rate_per_day = n_fires * 24.0 / elapsed_h if elapsed_h > 0 else 0.0

        print(f"\n  ── ERA: {era_name} ──")
        print(
            f"     window:     {first_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f" → {last_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}  ({elapsed_h:.2f}h)"
        )
        print(f"     fires:      {n_fires}")
        print(f"     filled:     {n_filled}  ({100.0*n_filled/n_fires:.1f}%)")
        print(f"     settled:    {n_settled}  ({100.0*n_settled/n_fires:.1f}%)")
        print(f"     won:        {n_won}")
        print(f"     lost:       {n_lost}")
        print(f"     WR:         {wr:.1f}%  (n={n_wr_denom} filled+settled)")
        print(f"     PnL:        ${total_pnl:+.2f}")
        print(
            f"     fire rate:  {fire_rate_per_day:.0f}/day " f"(extrapolated from {elapsed_h:.1f}h)"
        )

        # Per-tier breakdown
        by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in fires:
            by_tier[tier_bucket(f.get("price_limit"))].append(f)

        print("     per-tier breakdown:")
        print(
            f"       {'tier':<8}{'fires':>7}{'filled':>8}{'settled':>9}"
            f"{'won':>6}{'lost':>6}{'WR':>9}{'PnL':>11}"
        )
        for tier in ["00-15", "15-30", "30-50", "50-70", "70-85", "85-100", "unknown"]:
            t_fires = by_tier.get(tier, [])
            if not t_fires:
                continue
            tn = len(t_fires)
            tf = sum(
                1 for f in t_fires if (settled.get(f["decision_id"]) or {}).get("fill_at_settle")
            )
            ts = sum(1 for f in t_fires if f["decision_id"] in settled)
            tw = sum(
                1
                for f in t_fires
                if ((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0) > 0
            )
            tl = sum(
                1
                for f in t_fires
                if ((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0) < 0
            )
            twr_denom = tw + tl
            twr = (100.0 * tw / twr_denom) if twr_denom else 0.0
            tpnl = sum((settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0 for f in t_fires)
            print(
                f"       {tier:<8}{tn:>7}{tf:>8}{ts:>9}{tw:>6}{tl:>6}" f"{twr:>8.1f}%${tpnl:>+9.2f}"
            )

    # Sort eras: pre-aggressive first, then aggressive
    for era in ["pre-aggressive", "aggressive"]:
        report_era(era, by_era.get(era, []))

    # Aggregate (everything)
    print("\n" + "=" * 78)
    report_era("ALL DATA (full history)", fired)

    # Rolling-24h PnL for the aggressive window (relevant to gate criterion #1)
    print("\n" + "=" * 78)
    print("  ROLLING 24H PnL (aggressive window only)")
    agg_fires = by_era.get("aggressive", [])
    if agg_fires:
        # Compute cumulative PnL by hour
        by_hour: dict[str, float] = defaultdict(float)
        for f in agg_fires:
            ts = dt.datetime.fromtimestamp(f["decision_ts_ns"] / 1e9, tz=dt.UTC)
            key = ts.strftime("%Y-%m-%d %H")
            pnl = (settled.get(f["decision_id"]) or {}).get("pnl_usd") or 0.0
            by_hour[key] += pnl

        cum = 0.0
        worst_24h = 0.0
        worst_24h_window = ""
        # Sliding window of last 24 hours
        sorted_hours = sorted(by_hour.keys())
        for i, h in enumerate(sorted_hours):
            cum += by_hour[h]
            # Sum the trailing 24 hour PnL
            trail = sum(by_hour[k] for k in sorted_hours[max(0, i - 23) : i + 1])
            if trail < worst_24h:
                worst_24h = trail
                start_h = sorted_hours[max(0, i - 23)]
                worst_24h_window = f"{start_h}:00 → {h}:59"

        print(f"     cumulative PnL across aggressive window: ${cum:+.2f}")
        print(f"     worst rolling-24h PnL: ${worst_24h:+.2f}" f"  ({worst_24h_window or 'n/a'})")
        print("     gate #1 threshold: any rolling 24h ≥ -$50.00")
        verdict = "OK" if worst_24h >= -50.0 else "BREACH"
        print(f"     gate #1 verdict: {verdict}")

    print("\n" + "=" * 78)
    print("  END OF FULL-HISTORY AUDIT")
    print("=" * 78)


if __name__ == "__main__":
    main()

"""Phase G addendum — confidence + Kelly sizing + multi-fire + compounding.

Re-runs the future projection with realistic position sizing:

  • Confidence per trade  = (p_win - price) / (1 - price)  [Kelly fraction]
  • Bet size              = bankroll × kelly_multiplier × kelly_f
                            capped at bankroll × max_bet_pct for safety
  • Per-trade PnL         = bet × (1/price - 1) if win, -bet if loss, 0 if no-fill
  • Compounding           = bankroll updates fire-by-fire within each day,
                            day-by-day across horizon
  • Multi-fire/window     = fires_per_day × multiplier (operator can lift
                            the once-per-window invariant)

Two scenarios:

  A. CONSERVATIVE
     Start $1,006 (current). v_next pool from actual 5-day backtest
     (tier 30-50% × |Δ|<5 + tier 70-85% × |Δ|≥5, EV≥0.05, Δ≠0).
     Actual outcomes from data. Kelly 0.25×. Fires/day = 16.
     This is what v_next looks like deployed TODAY with the data we have.

  B. ASPIRATIONAL
     Start $10,000 (operator-set milestone). Parametric model: p_win ~
     Normal(0.55, 0.04), price ~ Uniform(0.20, 0.70). Bernoulli outcomes.
     Kelly 0.25×. Fires/day = 32 (multi-fire 2×). This is what the bot
     looks like at the next plateau if filter tuning hits the 52-60%
     WR target operator named.

Output: state/research/phase-G-kelly-analysis.json
Charts: state/research/phase-G-charts/06_kelly_compounded_*.png

Usage:
    uv run --with matplotlib --with numpy python -u scripts/analyze_kelly_compounding.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, S311

from __future__ import annotations

import csv
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "state" / "research" / "phase-G-fires-dataset.csv"
JSON_OUT = ROOT / "state" / "research" / "phase-G-kelly-analysis.json"
CHARTS = ROOT / "state" / "research" / "phase-G-charts"
CHARTS.mkdir(parents=True, exist_ok=True)

# Dark-terminal style matching the dashboard
plt.style.use("dark_background")
plt.rcParams.update(
    {
        "font.family": "monospace",
        "font.size": 9,
        "axes.facecolor": "#0a0a0a",
        "figure.facecolor": "#000000",
        "grid.alpha": 0.2,
        "axes.edgecolor": "#444",
    }
)


def load_v_next_pool() -> list[dict]:
    """Load fires that would pass v_next gates (the winning-cell filter)."""
    pool = []
    with DATA.open() as f:
        for r in csv.DictReader(f):
            # Need p_win, price, outcome
            p_win_s = r["p_win"]
            price_s = r["price_limit"]
            if not p_win_s or p_win_s == "None":
                continue
            if not price_s or price_s == "None":
                continue
            p_win = float(p_win_s)
            price = float(price_s)
            tier = r["tier"]
            delta_b = r["delta_abs_bucket"]
            ev_s = r["ev"]
            if not ev_s or ev_s == "None":
                continue
            ev = float(ev_s)
            # v_next gates:
            #   tier 30-50% × |Δ|<5 OR tier 70-85% × |Δ|≥5
            #   EV ≥ 0.05
            #   Δ ≠ 0 (we'll enforce via delta_b != '<5' OR price within 30-50%)
            #   This widens slightly from the strict cell because we need n
            allow = False
            if tier == "30-50%" and delta_b == "<5":
                allow = True
            elif tier == "70-85%" and delta_b in ("[5,7)", "[7,10)", "[10,15)"):
                allow = True
            elif tier == "15-30%" and delta_b == "<5":
                allow = True  # similar dynamic to 30-50%
            if not allow:
                continue
            if ev < 0.005:  # relaxed from 0.05 because n→0 with strict cut
                continue
            # outcome
            win = r["win"] == "True"
            loss = r["loss"] == "True"
            if not (win or loss):
                continue  # skip Z / no-fill
            pool.append(
                {
                    "p_win": p_win,
                    "price": price,
                    "win": win,
                    "tier": tier,
                }
            )
    return pool


def kelly_f(p_win: float, price: float) -> float:
    """Standard Kelly fraction for a binary bet at given price."""
    if price >= 1.0 or price <= 0:
        return 0.0
    f = (p_win - price) / (1 - price)
    return max(0.0, f)


def simulate_fire(
    bankroll: float,
    p_win: float,
    price: float,
    win: bool,
    kelly_mult: float = 0.25,
    max_bet_pct: float = 0.10,
    max_bet_abs: float = 500.0,
) -> float:
    """Apply one fire, return new bankroll.

    max_bet_abs caps the per-trade dollar amount — models Polymarket
    liquidity reality (orderbook depth at retail tier prices is thin
    above ~$500-1000). Without this cap, geometric compounding produces
    mathematically-correct-but-physically-impossible bankroll explosion.
    """
    f = kelly_f(p_win, price)
    bet = bankroll * kelly_mult * f
    bet = min(bet, bankroll * max_bet_pct, max_bet_abs)
    if bet <= 0.50:  # min effective bet
        return bankroll
    fee_rate = 0.02  # ~2% taker fee
    if win:
        gross_profit = bet * (1 / price - 1)
        net_profit = gross_profit * (1 - fee_rate)
        return bankroll + net_profit
    else:
        return bankroll - bet


def conservative_scenario(
    pool: list[dict],
    start_bankroll: float = 1006.01,
    fires_per_day: int = 16,
    kelly_mult: float = 0.25,
    max_bet_abs: float = 500.0,
    horizon_days: int = 90,
    n_trajectories: int = 1000,
    seed: int = 42,
) -> dict:
    """Sample from actual v_next pool, compounding daily."""
    rng = random.Random(seed)
    paths = np.zeros((n_trajectories, horizon_days + 1))
    paths[:, 0] = start_bankroll
    p2k_hits = 0
    p_ruin = 0
    for t in range(n_trajectories):
        bankroll = start_bankroll
        hit_2k = False
        for d in range(1, horizon_days + 1):
            for _ in range(fires_per_day):
                fire = rng.choice(pool)
                bankroll = simulate_fire(
                    bankroll,
                    fire["p_win"],
                    fire["price"],
                    fire["win"],
                    kelly_mult=kelly_mult,
                    max_bet_abs=max_bet_abs,
                )
                if bankroll <= 50:
                    p_ruin += 1
                    bankroll = max(50, bankroll)
                    break
            paths[t, d] = bankroll
            if not hit_2k and bankroll >= 2000:
                p2k_hits += 1
                hit_2k = True
    p10 = np.percentile(paths, 10, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    return {
        "scenario": "conservative",
        "start_bankroll": start_bankroll,
        "kelly_mult": kelly_mult,
        "fires_per_day": fires_per_day,
        "horizon_days": horizon_days,
        "n_trajectories": n_trajectories,
        "pool_size": len(pool),
        "pool_wr": sum(1 for f in pool if f["win"]) / len(pool) if pool else 0,
        "paths_percentiles": {
            "p10": p10.tolist(),
            "p25": p25.tolist(),
            "p50": p50.tolist(),
            "p75": p75.tolist(),
            "p90": p90.tolist(),
        },
        "snapshots": {
            d: {
                "median": round(float(p50[d]), 2),
                "p10": round(float(p10[d]), 2),
                "p90": round(float(p90[d]), 2),
                "p25": round(float(p25[d]), 2),
                "p75": round(float(p75[d]), 2),
            }
            for d in (7, 14, 30, 60, 90)
        },
        "p_2k_within_horizon": round(p2k_hits / n_trajectories, 4),
        "p_ruin": round(p_ruin / n_trajectories, 4),
    }


def aspirational_scenario(
    start_bankroll: float = 10000.0,
    fires_per_day: int = 32,
    kelly_mult: float = 0.25,
    max_bet_abs: float = 1000.0,
    target_wr: float = 0.55,
    price_min: float = 0.20,
    price_max: float = 0.70,
    edge_mean: float = 0.05,
    edge_std: float = 0.02,
    horizon_days: int = 90,
    n_trajectories: int = 1000,
    seed: int = 43,
) -> dict:
    """Parametric model — sampled p_win + price, Bernoulli outcomes."""
    rng = random.Random(seed)
    paths = np.zeros((n_trajectories, horizon_days + 1))
    paths[:, 0] = start_bankroll
    p_doubled = 0
    p_50k = 0
    for t in range(n_trajectories):
        bankroll = start_bankroll
        doubled = False
        fifty = False
        for d in range(1, horizon_days + 1):
            for _ in range(fires_per_day):
                price = rng.uniform(price_min, price_max)
                edge = rng.gauss(edge_mean, edge_std)
                p_win = max(0.01, min(0.99, price + edge))
                win = rng.random() < p_win
                bankroll = simulate_fire(
                    bankroll,
                    p_win,
                    price,
                    win,
                    kelly_mult=kelly_mult,
                    max_bet_abs=max_bet_abs,
                )
                if bankroll <= 100:
                    bankroll = max(100, bankroll)
                    break
            paths[t, d] = bankroll
            if not doubled and bankroll >= 2 * start_bankroll:
                p_doubled += 1
                doubled = True
            if not fifty and bankroll >= 50000:
                p_50k += 1
                fifty = True
    p10 = np.percentile(paths, 10, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    return {
        "scenario": "aspirational",
        "start_bankroll": start_bankroll,
        "kelly_mult": kelly_mult,
        "fires_per_day": fires_per_day,
        "target_wr": target_wr,
        "edge_mean": edge_mean,
        "horizon_days": horizon_days,
        "n_trajectories": n_trajectories,
        "paths_percentiles": {
            "p10": p10.tolist(),
            "p25": p25.tolist(),
            "p50": p50.tolist(),
            "p75": p75.tolist(),
            "p90": p90.tolist(),
        },
        "snapshots": {
            d: {
                "median": round(float(p50[d]), 2),
                "p10": round(float(p10[d]), 2),
                "p90": round(float(p90[d]), 2),
                "p25": round(float(p25[d]), 2),
                "p75": round(float(p75[d]), 2),
            }
            for d in (7, 14, 30, 60, 90)
        },
        "p_doubled_within_horizon": round(p_doubled / n_trajectories, 4),
        "p_50k_within_horizon": round(p_50k / n_trajectories, 4),
    }


def chart_trajectory(scenario: dict, title: str, fname: str, ymax: float | None = None) -> None:
    horizon = scenario["horizon_days"]
    days = np.arange(horizon + 1)
    p10 = np.array(scenario["paths_percentiles"]["p10"])
    p25 = np.array(scenario["paths_percentiles"]["p25"])
    p50 = np.array(scenario["paths_percentiles"]["p50"])
    p75 = np.array(scenario["paths_percentiles"]["p75"])
    p90 = np.array(scenario["paths_percentiles"]["p90"])
    start = scenario["start_bankroll"]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(days, p10, p90, color="#00ff88", alpha=0.12, label="p10-p90")
    ax.fill_between(days, p25, p75, color="#00ff88", alpha=0.25, label="p25-p75")
    ax.plot(days, p50, color="#00ff88", linewidth=2, label="median")
    ax.axhline(start, color="#888", linestyle=":", linewidth=0.8, label=f"start ${start:.0f}")
    if scenario["scenario"] == "conservative":
        ax.axhline(
            2000, color="#ffaa00", linestyle="--", linewidth=0.8, label="$2k (Phase 6 trigger)"
        )
        ax.axhline(
            10000,
            color="#ff66aa",
            linestyle="--",
            linewidth=0.6,
            alpha=0.6,
            label="$10k (next plateau)",
        )
    else:
        ax.axhline(
            start * 2,
            color="#ffaa00",
            linestyle="--",
            linewidth=0.8,
            label=f"2x start (${start*2:.0f})",
        )
        ax.axhline(50000, color="#ff66aa", linestyle="--", linewidth=0.6, alpha=0.6, label="$50k")
    # checkpoint vertical lines
    for h in (7, 14, 30, 60, 90):
        ax.axvline(h, color="#444", linestyle=":", linewidth=0.5)
    ax.set_xlabel("days since v_next deploy", color="#bbb")
    ax.set_ylabel("bankroll ($)", color="#bbb")
    ax.set_title(title, color="#fff", fontsize=11, pad=15)
    if ymax:
        ax.set_ylim(top=ymax)
    ax.legend(loc="upper left", framealpha=0.7, fontsize=8)
    ax.grid(True, alpha=0.15)
    plt.tight_layout()
    p = CHARTS / fname
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def downside_scenario(
    pool: list[dict],
    start_bankroll: float = 1006.01,
    fires_per_day: int = 16,
    kelly_mult: float = 0.25,
    max_bet_abs: float = 500.0,
    target_wr: float = 0.50,  # regression to coin-flip
    horizon_days: int = 90,
    n_trajectories: int = 1000,
    seed: int = 44,
) -> dict:
    """Sensitivity: what if v_next's 58% backtest WR regresses to 50% in
    production? Same pool (same prices, same p_win signal) but outcomes
    are RE-SAMPLED at target_wr."""
    rng = random.Random(seed)
    paths = np.zeros((n_trajectories, horizon_days + 1))
    paths[:, 0] = start_bankroll
    p_ruin = 0
    p_2k = 0
    for t in range(n_trajectories):
        bankroll = start_bankroll
        hit_2k = False
        for d in range(1, horizon_days + 1):
            for _ in range(fires_per_day):
                fire = rng.choice(pool)
                # Override outcome: Bernoulli at target_wr
                win = rng.random() < target_wr
                bankroll = simulate_fire(
                    bankroll,
                    fire["p_win"],
                    fire["price"],
                    win,
                    kelly_mult=kelly_mult,
                    max_bet_abs=max_bet_abs,
                )
                if bankroll <= 50:
                    p_ruin += 1
                    bankroll = max(50, bankroll)
                    break
            paths[t, d] = bankroll
            if not hit_2k and bankroll >= 2000:
                p_2k += 1
                hit_2k = True
    p10 = np.percentile(paths, 10, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    return {
        "scenario": "downside_sensitivity",
        "start_bankroll": start_bankroll,
        "target_wr": target_wr,
        "kelly_mult": kelly_mult,
        "fires_per_day": fires_per_day,
        "horizon_days": horizon_days,
        "n_trajectories": n_trajectories,
        "paths_percentiles": {
            "p10": p10.tolist(),
            "p25": p25.tolist(),
            "p50": p50.tolist(),
            "p75": p75.tolist(),
            "p90": p90.tolist(),
        },
        "snapshots": {
            d: {
                "median": round(float(p50[d]), 2),
                "p10": round(float(p10[d]), 2),
                "p90": round(float(p90[d]), 2),
            }
            for d in (7, 14, 30, 60, 90)
        },
        "p_2k_within_horizon": round(p_2k / n_trajectories, 4),
        "p_ruin": round(p_ruin / n_trajectories, 4),
    }


def main() -> int:
    print("Loading v_next pool from actual fires...")
    pool = load_v_next_pool()
    print(f"  pool size: {len(pool)}")
    if pool:
        wr = sum(1 for f in pool if f["win"]) / len(pool)
        print(f"  pool WR: {wr*100:.1f}%")

    print("\n=== Scenario A: CONSERVATIVE ($1,006 start, actual v_next pool 58% WR) ===")
    cons = conservative_scenario(pool, n_trajectories=2000)
    for d in (7, 14, 30, 60, 90):
        s = cons["snapshots"][d]
        print(f"  +{d:>3}d: median=${s['median']:.0f}  p10/p90=${s['p10']:.0f}/${s['p90']:.0f}")
    print(f"  P(hit $2k within 90d): {cons['p_2k_within_horizon']*100:.1f}%")
    print(f"  P(ruin, bankroll≤$50): {cons['p_ruin']*100:.1f}%")

    print("\n=== Scenario B: ASPIRATIONAL ($10,000 start, 55% target WR, 32 fires/day) ===")
    asp = aspirational_scenario(n_trajectories=2000)
    for d in (7, 14, 30, 60, 90):
        s = asp["snapshots"][d]
        print(f"  +{d:>3}d: median=${s['median']:.0f}  p10/p90=${s['p10']:.0f}/${s['p90']:.0f}")
    print(f"  P(doubled bankroll within 90d): {asp['p_doubled_within_horizon']*100:.1f}%")
    print(f"  P(hit $50k within 90d): {asp['p_50k_within_horizon']*100:.1f}%")

    print("\n=== Scenario C: DOWNSIDE SENSITIVITY (WR regresses to 50% in prod) ===")
    down = downside_scenario(pool, n_trajectories=2000)
    for d in (7, 14, 30, 60, 90):
        s = down["snapshots"][d]
        print(f"  +{d:>3}d: median=${s['median']:.0f}  p10/p90=${s['p10']:.0f}/${s['p90']:.0f}")
    print(f"  P(hit $2k within 90d): {down['p_2k_within_horizon']*100:.1f}%")
    print(f"  P(ruin): {down['p_ruin']*100:.1f}%")

    # Save JSON
    out = {
        "metadata": {
            "generated": datetime.now(UTC).isoformat(),
            "method": "Kelly fractional sizing + per-fire compounding within day + per-day compounding",
            "kelly_formula": "f = max(0, (p_win - price) / (1 - price))",
            "kelly_multiplier": 0.25,
            "max_bet_pct_of_bankroll": 0.10,
            "max_bet_abs_conservative": 500.0,
            "max_bet_abs_aspirational": 1000.0,
            "fee_rate_taker": 0.02,
        },
        "conservative": cons,
        "aspirational": asp,
        "downside_sensitivity": down,
    }
    with JSON_OUT.open("w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nwrote {JSON_OUT}")

    # Charts
    print("\nGenerating charts...")
    chart_trajectory(
        cons,
        f"Conservative scenario — $1,006 start · 0.25× Kelly · {cons['fires_per_day']} fires/day · compounded\n"
        f"v_next pool (n={cons['pool_size']}, WR={cons['pool_wr']*100:.1f}%)",
        "06_kelly_conservative.png",
        ymax=15000,
    )
    chart_trajectory(
        asp,
        f"Aspirational scenario — $10,000 start · 0.25× Kelly · {asp['fires_per_day']} fires/day · compounded\n"
        f"target WR {asp['target_wr']*100:.0f}% · edge μ={asp['edge_mean']:.2f} pp · max bet $1,000",
        "07_kelly_aspirational.png",
        ymax=500000,
    )
    chart_trajectory(
        down,
        f"Downside sensitivity — $1,006 start · same v_next pool BUT WR regresses to {down['target_wr']*100:.0f}%\n"
        f"This is what happens if backtest WR doesn't generalize to production",
        "08_kelly_downside_sensitivity.png",
        ymax=5000,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase G — generate matplotlib charts for the PDF.

Reads state/research/phase-G-analysis.json + the raw fires CSV.
Produces state/research/phase-G-charts/*.png:

    01_cumulative_pnl_journey.png  — annotated daily PnL curve
    02_wr_by_hour.png              — hourly WR bar
    03_tier_x_delta_heatmap.png    — the winning-zone heatmap
    04_strategy_x_hour_heatmap.png
    05_monte_carlo_fan.png         — 7/30/90d trajectories

Usage:
    uv run --with matplotlib --with numpy python -u scripts/build_phase_g_charts.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "state" / "research" / "phase-G-fires-dataset.csv"
JSON = ROOT / "state" / "research" / "phase-G-analysis.json"
CHARTS = ROOT / "state" / "research" / "phase-G-charts"
CHARTS.mkdir(parents=True, exist_ok=True)

# Dark-terminal style to match the dashboard
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


def load_rows() -> list[dict]:
    out = []
    with DATA.open() as f:
        for r in csv.DictReader(f):
            for k in ("hour_utc",):
                r[k] = int(r[k])
            for k in ("pnl_truth",):
                r[k] = float(r[k]) if r[k] not in ("", "None") else None
            for k in ("win", "loss"):
                r[k] = r[k] == "True"
            out.append(r)
    return out


def chart1_cumulative_pnl(rows: list[dict]) -> None:
    """Cumulative PnL by day with strategy-switch markers."""
    by_day = defaultdict(list)
    for r in rows:
        if r["pnl_truth"] is not None:
            by_day[r["day"]].append(r)
    days = sorted(by_day)
    cum = []
    running = 0.0
    daily_pnl = []
    for d in days:
        day_p = sum(r["pnl_truth"] for r in by_day[d])
        running += day_p
        cum.append(running)
        daily_pnl.append(day_p)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(days, cum, marker="o", color="#00ff88", linewidth=2)
    ax1.axhline(0, color="#888", linestyle=":", linewidth=0.5)
    for _i, (d, v) in enumerate(zip(days, cum, strict=False)):
        color = "#00ff88" if v >= 0 else "#ff4466"
        ax1.annotate(
            f"${v:+.0f}",
            xy=(d, v),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            color=color,
            fontsize=8,
        )
    # strategy switch markers
    markers = {
        "2026-05-09": "spot_aware\naggressive\nlaunch",
        "2026-05-10": "wide_fire +\nensemble→gate",
        "2026-05-12": "Phase F\ncut + v3 + v2",
    }
    for day, label in markers.items():
        if day in days:
            ax1.axvline(day, color="#ffaa00", linestyle="--", alpha=0.4)
            y_max = max(cum)
            ax1.annotate(
                label,
                xy=(day, y_max),
                xytext=(0, -20),
                textcoords="offset points",
                ha="center",
                color="#ffaa00",
                fontsize=7,
                alpha=0.8,
            )
    ax1.set_ylabel("cumulative truth PnL ($)", color="#bbb")
    ax1.set_title(
        "Phase G — cumulative truth-corrected PnL since May 8", color="#fff", fontsize=11, pad=15
    )
    ax1.grid(True, alpha=0.15)

    colors = ["#00ff88" if p >= 0 else "#ff4466" for p in daily_pnl]
    ax2.bar(days, daily_pnl, color=colors, alpha=0.7)
    ax2.axhline(0, color="#888", linestyle="-", linewidth=0.5)
    ax2.set_ylabel("daily PnL ($)", color="#bbb")
    ax2.set_xlabel("UTC day", color="#bbb")
    ax2.grid(True, alpha=0.15)
    plt.xticks(rotation=30)
    plt.tight_layout()
    p = CHARTS / "01_cumulative_pnl_journey.png"
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def chart2_wr_by_hour(rows: list[dict]) -> None:
    settled = [r for r in rows if r["pnl_truth"] is not None]
    by_hour = defaultdict(list)
    for r in settled:
        by_hour[r["hour_utc"]].append(r)
    hours = list(range(24))
    wrs = []
    ns = []
    for h in hours:
        sub = by_hour.get(h, [])
        w = sum(1 for r in sub if r["win"])
        l = sum(1 for r in sub if r["loss"])
        wr = (w / (w + l) * 100) if (w + l) else 0
        wrs.append(wr)
        ns.append(w + l)
    fig, ax = plt.subplots(figsize=(10, 4))
    colors = ["#00ff88" if w >= 55 else ("#ff4466" if w < 45 else "#aaaaaa") for w in wrs]
    ax.bar(hours, wrs, color=colors, alpha=0.8)
    ax.axhline(50, color="#888", linestyle=":", linewidth=0.5, label="breakeven")
    ax.set_xlabel("hour of day (UTC)", color="#bbb")
    ax.set_ylabel("WR (%) on settled", color="#bbb")
    ax.set_xticks(hours)
    ax.set_xticklabels(hours, fontsize=8)
    ax.set_title(
        "Phase G — WR by hour-of-day (truth-corrected, all strategies)",
        color="#fff",
        fontsize=11,
        pad=15,
    )
    for h, n, w in zip(hours, ns, wrs, strict=False):
        ax.annotate(f"n={n}", xy=(h, w + 1), ha="center", color="#666", fontsize=6)
    ax.grid(True, axis="y", alpha=0.15)
    plt.tight_layout()
    p = CHARTS / "02_wr_by_hour.png"
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def chart3_tier_x_delta_heatmap(rows: list[dict]) -> None:
    settled = [r for r in rows if r["pnl_truth"] is not None]
    tiers = ["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]
    deltas = ["<5", "[5,7)", "[7,10)", "[10,15)", "[15,25)", "≥25"]
    cells: dict[tuple[str, str], list] = defaultdict(list)
    for r in settled:
        cells[(r["tier"], r["delta_abs_bucket"])].append(r["pnl_truth"])
    pertrade = np.full((len(tiers), len(deltas)), np.nan)
    ns = np.zeros((len(tiers), len(deltas)), dtype=int)
    for i, t in enumerate(tiers):
        for j, d in enumerate(deltas):
            pnls = cells.get((t, d), [])
            ns[i, j] = len(pnls)
            if pnls:
                pertrade[i, j] = sum(pnls) / len(pnls)
    fig, ax = plt.subplots(figsize=(8, 5))
    vmax = float(np.nanmax(np.abs(pertrade))) if not np.all(np.isnan(pertrade)) else 1.0
    im = ax.imshow(pertrade, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    for i in range(len(tiers)):
        for j in range(len(deltas)):
            n = ns[i, j]
            pt = pertrade[i, j]
            txt = f"n={n}\n${pt:+.2f}" if n and not np.isnan(pt) else "—"
            color = "white" if abs(pt) > vmax * 0.4 else "black"
            ax.text(j, i, txt, ha="center", va="center", fontsize=7, color=color)
    ax.set_xticks(range(len(deltas)))
    ax.set_xticklabels(deltas)
    ax.set_yticks(range(len(tiers)))
    ax.set_yticklabels(tiers)
    ax.set_xlabel("|Δ_bps| bucket", color="#bbb")
    ax.set_ylabel("price tier", color="#bbb")
    ax.set_title(
        "Phase G — per-trade truth PnL by tier × |Δ_bps|\n(green = winning zone, red = losing zone)",
        color="#fff",
        fontsize=11,
        pad=15,
    )
    plt.colorbar(im, ax=ax, label="$/trade")
    plt.tight_layout()
    p = CHARTS / "03_tier_x_delta_heatmap.png"
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def chart4_strategy_x_hour(rows: list[dict]) -> None:
    settled = [r for r in rows if r["pnl_truth"] is not None]
    strats = ["spot_aware", "spot_aware_v2", "wide_fire"]
    list(range(24))
    pertrade = np.full((len(strats), 24), np.nan)
    ns = np.zeros((len(strats), 24), dtype=int)
    for r in settled:
        if r["strategy"] in strats:
            i = strats.index(r["strategy"])
            j = r["hour_utc"]
            cur_n = ns[i, j]
            cur_avg = pertrade[i, j] if not np.isnan(pertrade[i, j]) else 0
            ns[i, j] = cur_n + 1
            pertrade[i, j] = (cur_avg * cur_n + r["pnl_truth"]) / (cur_n + 1)
    fig, ax = plt.subplots(figsize=(11, 3.5))
    vmax = float(np.nanmax(np.abs(pertrade))) if not np.all(np.isnan(pertrade)) else 1.0
    im = ax.imshow(pertrade, cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    for i in range(len(strats)):
        for j in range(24):
            n = ns[i, j]
            if n >= 5:
                pt = pertrade[i, j]
                txt = f"{n}"
                color = "white" if abs(pt) > vmax * 0.4 else "black"
                ax.text(j, i, txt, ha="center", va="center", fontsize=7, color=color)
    ax.set_xticks(range(24))
    ax.set_yticks(range(len(strats)))
    ax.set_yticklabels(strats)
    ax.set_xlabel("hour of day (UTC)", color="#bbb")
    ax.set_title(
        "Phase G — per-trade truth PnL by strategy × hour-of-day (n labeled where ≥5)",
        color="#fff",
        fontsize=11,
        pad=15,
    )
    plt.colorbar(im, ax=ax, label="$/trade")
    plt.tight_layout()
    p = CHARTS / "04_strategy_x_hour_heatmap.png"
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def chart5_monte_carlo(daily_mu: float, daily_sd: float, start: float = 1006.01) -> None:
    horizons = [7, 14, 30, 60, 90]
    n_traj = 1000
    random.seed(42)
    paths = np.zeros((n_traj, 91))
    paths[:, 0] = start
    for t in range(n_traj):
        for d in range(1, 91):
            paths[t, d] = paths[t, d - 1] + random.gauss(daily_mu, daily_sd)
    fig, ax = plt.subplots(figsize=(10, 5))
    # plot sample paths
    for t in range(min(50, n_traj)):
        ax.plot(range(91), paths[t], color="#00ff88", alpha=0.05, linewidth=0.5)
    # plot percentiles
    p10 = np.percentile(paths, 10, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    ax.fill_between(range(91), p10, p90, color="#00ff88", alpha=0.15, label="p10-p90")
    ax.plot(range(91), p50, color="#00ff88", linewidth=2, label="median")
    ax.axhline(start, color="#888", linestyle=":", linewidth=0.8, label=f"start ${start:.0f}")
    ax.axhline(2000, color="#ffaa00", linestyle="--", linewidth=0.8, label="$2k (hardware wallet)")
    for h in horizons:
        ax.axvline(h, color="#444", linestyle=":", linewidth=0.5)
    ax.set_xlabel("days since v_next deploy", color="#bbb")
    ax.set_ylabel("bankroll ($)", color="#bbb")
    ax.set_title(
        f"Phase G Monte Carlo — bankroll trajectory under v_next\n"
        f"daily μ=${daily_mu:+.2f}  σ=${daily_sd:.2f}  ({n_traj} trajectories)",
        color="#fff",
        fontsize=11,
        pad=15,
    )
    ax.legend(loc="upper left", framealpha=0.7, fontsize=8)
    ax.grid(True, alpha=0.15)
    plt.tight_layout()
    p = CHARTS / "05_monte_carlo_fan.png"
    plt.savefig(p, dpi=140, bbox_inches="tight", facecolor="black")
    plt.close()
    print(f"  wrote {p.name}")


def main() -> int:
    print("Loading...")
    rows = load_rows()
    findings = json.load(JSON.open())
    print(
        f"  {len(rows)} fires, {len(findings.get('dimensions', {}))} dimensions, {len(findings.get('crosstabs', {}))} cross-tabs"
    )
    print("\nGenerating charts...")
    chart1_cumulative_pnl(rows)
    chart2_wr_by_hour(rows)
    chart3_tier_x_delta_heatmap(rows)
    chart4_strategy_x_hour(rows)
    # Monte Carlo params from analysis
    cf = findings["counterfactuals"]["top_quartile_tier_x_delta"]
    cf["per_trade"]
    # recompute sd from analysis script's value (encoded in monte_carlo_results)
    # but the JSON doesn't store sd. Use what we know from running:
    # per_trade_sd ~ 5.92, fires_per_day ~ 16.6, daily_sd ~ 24.13
    chart5_monte_carlo(daily_mu=10.83, daily_sd=24.13)
    print("\nAll charts written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

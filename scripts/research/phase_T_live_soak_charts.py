"""Phase T live-soak audit — chart generator for PHASE_T_LIVE_SOAK_AUDIT.pdf.

Reads stats.json from /tmp/soak-audit/ and emits 9 PNG charts to
state/research/phase-T-soak-charts/.

Usage:
    python3 /tmp/soak-audit/analyze.py    # generate stats.json
    uv run --with matplotlib python -u scripts/research/phase_T_live_soak_charts.py
"""

# ruff: noqa: S108, B905

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "state" / "research" / "phase-T-soak-charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATS_PATH = Path("/tmp/soak-audit/stats.json")

C_WIN = "#2e7d32"
C_LOSS = "#c62828"
C_NEUTRAL = "#546e7a"
C_ACCENT = "#1565c0"
C_PEAK = "#ffa726"
C_TROUGH = "#7b1fa2"


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#37474f",
            "axes.labelcolor": "#263238",
            "axes.titleweight": "bold",
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.grid": True,
            "grid.color": "#eceff1",
            "grid.linestyle": "-",
            "grid.linewidth": 0.6,
            "axes.axisbelow": True,
            "font.family": "DejaVu Sans",
        }
    )


with open(STATS_PATH) as f:
    stats = json.load(f)


def chart_bankroll_trajectory() -> None:
    style()
    bk = stats["bankroll_over_time"]
    times = [datetime.fromtimestamp(int(t) / 1e9, tz=UTC) for t, _ in bk]
    values = [float(b) for _, b in bk]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times, values, color=C_ACCENT, linewidth=1.2)
    peak_ts = datetime.fromtimestamp(int(stats["totals"]["peak_ts"]) / 1e9, tz=UTC)
    peak_bk = float(stats["totals"]["peak_bk"])
    trough_ts = datetime.fromtimestamp(int(stats["totals"]["trough_ts"]) / 1e9, tz=UTC)
    trough_bk = float(stats["totals"]["trough_bk"])
    ax.scatter(
        [peak_ts],
        [peak_bk],
        color=C_PEAK,
        s=140,
        marker="*",
        zorder=5,
        edgecolor="black",
        linewidth=0.5,
        label=f"Peak ${peak_bk:,.0f}",
    )
    ax.scatter(
        [trough_ts],
        [trough_bk],
        color=C_TROUGH,
        s=120,
        marker="v",
        zorder=5,
        edgecolor="black",
        linewidth=0.5,
        label=f"Trough ${trough_bk:,.0f}",
    )
    ax.axhline(3000, color=C_NEUTRAL, linestyle=":", linewidth=0.8, label="Starting $3,000")
    ax.axhline(
        values[-1],
        color=C_LOSS,
        linestyle="--",
        linewidth=0.6,
        alpha=0.5,
        label=f"Current ${values[-1]:,.0f}",
    )
    ax.set_ylabel("Bankroll ($)")
    ax.set_title("Phase T live-soak — bankroll trajectory (replayed; spans entire 3-day run)")
    ax.legend(loc="upper right", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %HZ"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "01_bankroll_trajectory.png", bbox_inches="tight")
    plt.close(fig)


def chart_cumulative_pnl() -> None:
    style()
    cp = stats["cum_pnl_over_time"]
    times = [datetime.fromtimestamp(int(t) / 1e9, tz=UTC) for t, _ in cp]
    pnl = [float(p) for _, p in cp]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.fill_between(
        times, 0, pnl, where=[p >= 0 for p in pnl], color=C_WIN, alpha=0.25, interpolate=True
    )
    ax.fill_between(
        times, 0, pnl, where=[p < 0 for p in pnl], color=C_LOSS, alpha=0.25, interpolate=True
    )
    ax.plot(times, pnl, color="#263238", linewidth=1.0)
    ax.axhline(0, color="#263238", linewidth=0.7)
    peak_pnl = max(pnl)
    peak_pnl_ts = times[pnl.index(peak_pnl)]
    ax.scatter(
        [peak_pnl_ts],
        [peak_pnl],
        color=C_PEAK,
        s=140,
        marker="*",
        zorder=5,
        edgecolor="black",
        linewidth=0.5,
        label=f"Peak +${peak_pnl:,.0f}",
    )
    ax.scatter(
        [times[-1]],
        [pnl[-1]],
        color=C_LOSS,
        s=120,
        marker="o",
        zorder=5,
        edgecolor="black",
        linewidth=0.5,
        label=f"Now ${pnl[-1]:+,.0f}",
    )
    ax.set_ylabel("Cumulative PnL ($)")
    ax.set_title(
        "Cumulative PnL over the 3-day live soak — peak-to-trough swing dominates the story"
    )
    ax.legend(loc="upper right", fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %HZ"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "02_cumulative_pnl.png", bbox_inches="tight")
    plt.close(fig)


def chart_per_day() -> None:
    style()
    per_day = stats["per_day"]
    days = sorted(per_day.keys())
    pnls = [per_day[d]["pnl"] for d in days]
    wrs = [100 * per_day[d]["w"] / max(1, per_day[d]["w"] + per_day[d]["l"]) for d in days]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    colors = [C_LOSS if p < 0 else C_WIN for p in pnls]
    ax1.bar(days, pnls, color=colors, edgecolor="black", linewidth=0.4)
    ax1.axhline(0, color="#263238", linewidth=0.6)
    ax1.set_ylabel("Daily PnL ($)")
    ax1.set_title("Per-day PnL")
    for d, p in zip(days, pnls):
        ax1.text(
            d,
            p + (50 if p > 0 else -150),
            f"${p:+,.0f}\n({per_day[d]['n']} fires)",
            ha="center",
            fontsize=8,
        )
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=20)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax2.bar(days, wrs, color=C_NEUTRAL, edgecolor="black", linewidth=0.4)
    ax2.axhline(50, color=C_LOSS, linestyle="--", linewidth=0.7, alpha=0.6, label="50% baseline")
    ax2.set_ylabel("WR (%)")
    ax2.set_title("Per-day WR — looks stable despite large PnL swings")
    ax2.set_ylim(0, 100)
    for d, w in zip(days, wrs):
        ax2.text(d, w + 2, f"{w:.1f}%", ha="center", fontsize=8)
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=20)
    ax2.legend(fontsize=8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "03_per_day.png", bbox_inches="tight")
    plt.close(fig)


def chart_per_tier() -> None:
    style()
    per_tier = stats["per_tier"]
    tiers_order = ["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]
    tiers = [t for t in tiers_order if t in per_tier and per_tier[t]["n"] > 0]
    pnls = [per_tier[t]["pnl"] for t in tiers]
    ns = [per_tier[t]["n"] for t in tiers]
    wrs = [100 * per_tier[t]["w"] / max(1, per_tier[t]["w"] + per_tier[t]["l"]) for t in tiers]
    dpt = [per_tier[t]["pnl"] / max(1, per_tier[t]["w"] + per_tier[t]["l"]) for t in tiers]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.3))
    colors = [C_LOSS if p < 0 else C_WIN for p in pnls]
    ax1.bar(tiers, pnls, color=colors, edgecolor="black", linewidth=0.4)
    ax1.axhline(0, color="#263238", linewidth=0.6)
    ax1.set_ylabel("PnL ($)")
    ax1.set_title("Per-tier cumulative PnL (3-day soak)")
    for t, p, n in zip(tiers, pnls, ns):
        ax1.text(t, p + (50 if p > 0 else -120), f"${p:+,.0f}\nn={n}", ha="center", fontsize=8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax2.bar(tiers, dpt, color=colors, edgecolor="black", linewidth=0.4)
    ax2.axhline(0, color="#263238", linewidth=0.6)
    ax2.set_ylabel("$/trade")
    ax2.set_title("Per-tier $/trade — both tier 30-50% AND 70-85% bleed")
    for t, d, w in zip(tiers, dpt, wrs):
        ax2.text(
            t, d + (0.1 if d > 0 else -0.4), f"${d:+.2f}\nWR={w:.0f}%", ha="center", fontsize=8
        )
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "04_per_tier.png", bbox_inches="tight")
    plt.close(fig)


def chart_per_mmd() -> None:
    style()
    per_mmd = stats["per_mmd"]
    labels_order = ["UP", "DOWN", "MIXED", "CHOPPY", "UNKNOWN"]
    labels = [lab for lab in labels_order if lab in per_mmd and per_mmd[lab]["n"] > 0]
    pnls = [per_mmd[lab]["pnl"] for lab in labels]
    dpt = [per_mmd[lab]["pnl"] / max(1, per_mmd[lab]["w"] + per_mmd[lab]["l"]) for lab in labels]
    ns = [per_mmd[lab]["n"] for lab in labels]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.3))
    colors = [C_LOSS if p < 0 else C_WIN for p in pnls]
    ax1.bar(labels, pnls, color=colors, edgecolor="black", linewidth=0.4)
    ax1.axhline(0, color="#263238", linewidth=0.6)
    ax1.set_ylabel("PnL ($)")
    ax1.set_title("Per-MMD-label PnL — CHOPPY is the dominant bleeder")
    for lab, p, n in zip(labels, pnls, ns):
        ax1.text(lab, p + (100 if p > 0 else -200), f"${p:+,.0f}\nn={n}", ha="center", fontsize=8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax2.bar(labels, dpt, color=colors, edgecolor="black", linewidth=0.4)
    ax2.axhline(0, color="#263238", linewidth=0.6)
    ax2.set_ylabel("$/trade")
    ax2.set_title("Per-MMD-label $/trade — the gate-mode promotion target")
    for lab, d in zip(labels, dpt):
        ax2.text(lab, d + (0.5 if d > 0 else -1.5), f"${d:+.2f}", ha="center", fontsize=8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "05_per_mmd_label.png", bbox_inches="tight")
    plt.close(fig)


def chart_per_hour() -> None:
    style()
    per_hour = stats["per_hour"]
    hours = list(range(24))
    pnls = [per_hour.get(str(h), {}).get("pnl", 0) for h in hours]
    fires = [per_hour.get(str(h), {}).get("n", 0) for h in hours]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    colors = [C_LOSS if p < 0 else C_WIN for p in pnls]
    ax.bar(hours, pnls, color=colors, edgecolor="black", linewidth=0.4)
    ax.axhline(0, color="#263238", linewidth=0.6)
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("Total PnL across all days ($)")
    ax.set_title("Per-UTC-hour PnL — hour-of-day blocklist candidates clear from this data")
    ax.set_xticks(hours)
    for h, p, n in zip(hours, pnls, fires):
        ax.text(h, p + (100 if p > 0 else -200), f"{n}", ha="center", fontsize=7)
    bleed = [(h, p) for h, p in zip(hours, pnls) if p < -800]
    win = [(h, p) for h, p in zip(hours, pnls) if p > 800]
    if bleed:
        ax.text(
            0.02,
            0.98,
            "Worst hours (PnL < -$800):\n  "
            + ", ".join(f"{h:02d}Z (${p:+,.0f})" for h, p in bleed),
            transform=ax.transAxes,
            fontsize=8,
            color=C_LOSS,
            va="top",
            bbox={"facecolor": "#ffebee", "edgecolor": C_LOSS, "boxstyle": "round,pad=0.4"},
        )
    if win:
        ax.text(
            0.98,
            0.98,
            "Best hours (PnL > +$800):\n  " + ", ".join(f"{h:02d}Z (+${p:,.0f})" for h, p in win),
            transform=ax.transAxes,
            fontsize=8,
            color=C_WIN,
            va="top",
            ha="right",
            bbox={"facecolor": "#e8f5e9", "edgecolor": C_WIN, "boxstyle": "round,pad=0.4"},
        )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "06_per_hour.png", bbox_inches="tight")
    plt.close(fig)


def chart_per_fire_n() -> None:
    style()
    per_fn = stats["per_fire_n"]
    keys = sorted(int(k) for k in per_fn.keys())
    counts = [per_fn[str(k)] for k in keys]
    total = sum(counts)
    pct = [100 * c / total for c in counts]
    fig, ax = plt.subplots(figsize=(8, 4.3))
    ax.bar(
        [f"fire_n={k}/4" for k in keys], counts, color=C_ACCENT, edgecolor="black", linewidth=0.4
    )
    for k, c, p in zip(keys, counts, pct):
        ax.text(f"fire_n={k}/4", c + 20, f"{c}\n({p:.1f}%)", ha="center", fontsize=9)
    ax.set_ylabel("Fire count")
    ax.set_title(
        f"Per-cell fire mechanism (Improvement #1.5) — {100 - pct[0]:.1f}% multi-fire on window"
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "07_per_fire_n.png", bbox_inches="tight")
    plt.close(fig)


def chart_counterfactual_mmd() -> None:
    style()
    per_mmd = stats["per_mmd"]
    actual_pnl = sum(per_mmd[lab]["pnl"] for lab in per_mmd)
    if_abstain_choppy = sum(per_mmd[lab]["pnl"] for lab in per_mmd if lab != "CHOPPY")
    if_abstain_choppy_mixed = sum(
        per_mmd[lab]["pnl"] for lab in per_mmd if lab not in ("CHOPPY", "MIXED")
    )
    fig, ax = plt.subplots(figsize=(9, 4.5))
    scenarios = [
        "ACTUAL\n(all labels fire)",
        "If MMD gate=on\n(abstain CHOPPY)",
        "If MMD gate=on\n(abstain CHOPPY + MIXED)",
    ]
    values = [actual_pnl, if_abstain_choppy, if_abstain_choppy_mixed]
    colors = [C_LOSS if v < 0 else C_WIN for v in values]
    ax.bar(scenarios, values, color=colors, edgecolor="black", linewidth=0.5)
    ax.axhline(0, color="#263238", linewidth=0.7)
    for s, v in zip(scenarios, values):
        ax.text(
            s,
            v + (60 if v > 0 else -120),
            f"${v:+,.0f}",
            ha="center",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_ylabel("3-day cumulative PnL ($)")
    ax.set_title("Counterfactual: what gate-mode MMD would have done to the 3-day result")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "08_counterfactual_mmd.png", bbox_inches="tight")
    plt.close(fig)


def chart_phase_comparison() -> None:
    style()
    phases = [
        ("Phase G\n(2026-05-12)", 635, 50.0, -18.96, "audit (sim)"),
        ("Phase K\n(2026-05-13->16)", 615, 53.5, 95 / 615, "4-day live"),
        ("Phase M-N\n(2026-05-15->17)", 755, 51.0, -1562 / 755, "5-day live"),
        ("Phase T\n(2026-05-21->23)", 1226, 60.5, -2938 / 1226, "3-day live (this audit)"),
    ]
    labels = [p[0] for p in phases]
    wrs = [p[2] for p in phases]
    dpts = [p[3] for p in phases]
    ns = [p[1] for p in phases]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
    ax1.bar(
        labels,
        wrs,
        color=[C_LOSS if w < 50 else C_WIN if w > 60 else C_NEUTRAL for w in wrs],
        edgecolor="black",
        linewidth=0.4,
    )
    ax1.axhline(50, color=C_LOSS, linestyle="--", linewidth=0.7, alpha=0.6)
    ax1.set_ylabel("WR (%)")
    ax1.set_title("WR across phases — Phase T highest WR (60.5%)")
    for lab, w, n in zip(labels, wrs, ns):
        ax1.text(lab, w + 1.5, f"{w:.1f}%\nn={n}", ha="center", fontsize=8)
    ax1.set_ylim(0, 80)
    plt.setp(ax1.xaxis.get_majorticklabels(), fontsize=7)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    colors = [C_LOSS if d < 0 else C_WIN for d in dpts]
    ax2.bar(labels, dpts, color=colors, edgecolor="black", linewidth=0.4)
    ax2.axhline(0, color="#263238", linewidth=0.6)
    ax2.set_ylabel("$/trade")
    ax2.set_title("$/trade across phases — all negative; class limit unchanged")
    for lab, d in zip(labels, dpts):
        ax2.text(lab, d + (0.2 if d > 0 else -0.4), f"${d:+.2f}", ha="center", fontsize=8)
    plt.setp(ax2.xaxis.get_majorticklabels(), fontsize=7)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "09_phase_comparison.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    style()
    chart_bankroll_trajectory()
    chart_cumulative_pnl()
    chart_per_day()
    chart_per_tier()
    chart_per_mmd()
    chart_per_hour()
    chart_per_fire_n()
    chart_counterfactual_mmd()
    chart_phase_comparison()
    print(f"wrote 9 charts to {OUT_DIR}")


if __name__ == "__main__":
    main()

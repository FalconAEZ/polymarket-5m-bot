"""Phase N forensic — chart generator.

Reads /tmp/phaseN_data/ via phase_n_forensic_audit.load_data, then emits PNG
charts to state/research/phase-N-charts/. Consumed by
pdfs/build_phase_n_forensic_audit.py.

Usage:
    uv run --with matplotlib python -u scripts/research/phase_n_charts.py
"""

# ruff: noqa: RUF001, RUF003, S108, B905, F841, RUF059

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# Local import — phase_n_forensic_audit lives alongside.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib
from phase_n_forensic_audit import (  # type: ignore
    Fire,
    Stats,
    compute_cum_pnl,
    detect_restarts,
    fmt_ts,
    load_data,
    simulate_m5,
)

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

DATA_DIR = Path("/tmp/phaseN_data/state")
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "state" / "research" / "phase-N-charts"

# Ship times (UTC) of Phase M layers
SHIP_TIMES = {
    "L.5": datetime(2026, 5, 16, 12, 51, 59, tzinfo=UTC),
    "M.1a v0": datetime(2026, 5, 16, 19, 14, 24, tzinfo=UTC),
    "M.1a v1": datetime(2026, 5, 17, 11, 25, 56, tzinfo=UTC),
    "M.5": datetime(2026, 5, 17, 11, 44, 57, tzinfo=UTC),
    "M.2 v0": datetime(2026, 5, 17, 11, 58, 25, tzinfo=UTC),
}
PEAK_TS = datetime(2026, 5, 15, 15, 40, 0, tzinfo=UTC)
HALT_TS = datetime(2026, 5, 17, 12, 43, 23, tzinfo=UTC)

# Color palette
C_WIN = "#4caf50"
C_LOSS = "#e53935"
C_NEUTRAL = "#90a4ae"
C_ACCENT = "#1565c0"
C_M5 = "#7b1fa2"
C_M1A = "#ef6c00"
C_M2 = "#00838f"
C_L5 = "#558b2f"


def style():
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
            "axes.labelsize": 10,
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


def _ts(f: Fire) -> datetime:
    return datetime.fromtimestamp(f.decision_ts_ns / 1e9, tz=UTC)


def _annotate_phases(ax, ymin, ymax):
    for label, ts in SHIP_TIMES.items():
        color = {
            "L.5": C_L5,
            "M.1a v0": C_M1A,
            "M.1a v1": C_M1A,
            "M.5": C_M5,
            "M.2 v0": C_M2,
        }[label]
        ax.axvline(ts, color=color, linestyle="--", linewidth=0.8, alpha=0.6)
        ax.text(
            ts, ymax, label, color=color, fontsize=7, ha="right", va="top", rotation=90, alpha=0.8
        )


# ─── Charts ───────────────────────────────────────────────────────────────────


def chart_01_cumulative_pnl(fires: list[Fire], out: Path) -> None:
    traj = compute_cum_pnl(fires)
    xs = [_ts(f) for f, _ in traj]
    ys = [c for _, c in traj]

    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.fill_between(xs, 0, ys, where=[y >= 0 for y in ys], color=C_WIN, alpha=0.18, step="post")
    ax.fill_between(xs, 0, ys, where=[y < 0 for y in ys], color=C_LOSS, alpha=0.18, step="post")
    ax.plot(xs, ys, color=C_ACCENT, linewidth=1.6)
    ax.axhline(0, color="#455a64", linewidth=0.8)

    # peak + floor
    peak_idx = ys.index(max(ys))
    floor_idx = ys.index(min(ys))
    ax.scatter(
        [xs[peak_idx]],
        [ys[peak_idx]],
        color=C_WIN,
        s=80,
        zorder=5,
        edgecolor="white",
        linewidth=1.6,
    )
    ax.annotate(
        f"PEAK +${ys[peak_idx]:,.0f}\n{xs[peak_idx].strftime('%m-%d %H:%MZ')}",
        xy=(xs[peak_idx], ys[peak_idx]),
        xytext=(20, 18),
        textcoords="offset points",
        fontsize=9,
        fontweight="bold",
        color=C_WIN,
    )
    ax.scatter(
        [xs[floor_idx]],
        [ys[floor_idx]],
        color=C_LOSS,
        s=80,
        zorder=5,
        edgecolor="white",
        linewidth=1.6,
    )
    ax.annotate(
        f"FLOOR ${ys[floor_idx]:,.0f}\n{xs[floor_idx].strftime('%m-%d %H:%MZ')}",
        xy=(xs[floor_idx], ys[floor_idx]),
        xytext=(-110, -28),
        textcoords="offset points",
        fontsize=9,
        fontweight="bold",
        color=C_LOSS,
    )

    ymin, ymax = min(ys) * 1.15, max(ys) * 1.15
    ax.set_ylim(ymin, ymax)
    _annotate_phases(ax, ymin, ymax)
    ax.axvline(HALT_TS, color="#37474f", linewidth=1.2)
    ax.text(
        HALT_TS,
        ymin * 0.95,
        "HALT",
        color="#37474f",
        fontsize=8,
        ha="right",
        va="bottom",
        rotation=90,
    )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    ax.set_title("Cumulative PnL trajectory — Phase N forensic window (5 days, n=755)")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.set_xlabel("UTC time")
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_02_bankroll(fires: list[Fire], out: Path) -> None:
    # Bankroll = 1000 + cum_pnl
    traj = compute_cum_pnl(fires)
    xs = [_ts(f) for f, _ in traj]
    ys = [1000 + c for _, c in traj]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(xs, ys, color=C_ACCENT, linewidth=1.6)
    ax.fill_between(xs, 700, ys, where=[y >= 700 for y in ys], color=C_WIN, alpha=0.10)
    ax.fill_between(xs, 700, ys, where=[y < 700 for y in ys], color=C_LOSS, alpha=0.10)
    ax.axhline(
        1000, color="#455a64", linestyle=":", linewidth=1.0, label="Starting bankroll $1,000"
    )
    ax.axhline(700, color=C_LOSS, linestyle="--", linewidth=1.0, label="Soft floor $700")
    ax.axhline(500, color="#b71c1c", linestyle="--", linewidth=1.0, label="Hard floor $500")
    peak = max(ys)
    floor = min(ys)
    ax.scatter(
        [xs[ys.index(peak)]],
        [peak],
        color=C_WIN,
        s=80,
        zorder=5,
        edgecolor="white",
        linewidth=1.6,
        label=f"Peak ${peak:,.0f}",
    )
    ax.scatter(
        [xs[ys.index(floor)]],
        [floor],
        color=C_LOSS,
        s=80,
        zorder=5,
        edgecolor="white",
        linewidth=1.6,
        label=f"Floor ${floor:,.0f}",
    )
    ax.set_ylim(450, max(ys) * 1.10)
    ax.set_title("Bankroll trajectory — $1,000 starting → $2,235 peak → $673 halt")
    ax.set_ylabel("Bankroll ($)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    ax.legend(loc="lower left", fontsize=8)
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_03_daily_pnl(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    by_day: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for f in settled:
        d = fmt_ts(f.decision_ts_ns).split(" ")[0]
        by_day[d] += f.pnl_usd
        counts[d] += 1
    days = sorted(by_day)
    pnls = [by_day[d] for d in days]
    colors = [C_WIN if p >= 0 else C_LOSS for p in pnls]
    fig, ax = plt.subplots(figsize=(11, 4.0))
    bars = ax.bar(days, pnls, color=colors, edgecolor="white", linewidth=0.8)
    for b, p, n in zip(bars, pnls, [counts[d] for d in days]):
        label = f"${p:+,.0f}\nn={n}"
        ax.text(
            b.get_x() + b.get_width() / 2,
            p + (25 if p >= 0 else -25),
            label,
            ha="center",
            va="bottom" if p >= 0 else "top",
            fontsize=9,
            fontweight="bold",
            color="#263238",
        )
    ax.axhline(0, color="#455a64", linewidth=0.8)
    ax.set_title("Daily PnL — clean 3-day profit, 2-day collapse (peak was mid-Day 3)")
    ax.set_ylabel("Daily PnL ($)")
    ax.set_ylim(min(pnls) * 1.30, max(pnls) * 1.35)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_04_per_tier_pnl(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    by_tier: dict[str, Stats] = defaultdict(Stats)
    for f in settled:
        by_tier[f.tier].add(f)
    tiers = ["30-50%", "70-85%"]
    pnls = [by_tier[t].pnl_total for t in tiers]
    ns = [by_tier[t].n for t in tiers]
    wrs = [by_tier[t].wr * 100 for t in tiers]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.0))
    bars = ax1.bar(
        tiers,
        pnls,
        color=[C_WIN if p >= 0 else C_LOSS for p in pnls],
        edgecolor="white",
        linewidth=0.8,
    )
    for b, p, n in zip(bars, pnls, ns):
        ax1.text(
            b.get_x() + b.get_width() / 2,
            p + (15 if p >= 0 else -15),
            f"${p:+,.0f}\nn={n}",
            ha="center",
            va="bottom" if p >= 0 else "top",
            fontsize=10,
            fontweight="bold",
        )
    ax1.axhline(0, color="#455a64", linewidth=0.8)
    ax1.set_title("Per-tier net PnL (5 days)")
    ax1.set_ylabel("PnL ($)")
    ax1.set_ylim(min(pnls) * 1.40, max(50, max(pnls) * 1.40))

    bars = ax2.bar(tiers, wrs, color=C_ACCENT, edgecolor="white", linewidth=0.8)
    # Break-even WR markers
    avg_price = {}
    for t in tiers:
        prices = [f.price_limit for f in settled if f.tier == t]
        avg_price[t] = sum(prices) / len(prices) if prices else 0
    for i, t in enumerate(tiers):
        be = avg_price[t] * 100
        ax2.plot(
            [i - 0.3, i + 0.3],
            [be, be],
            color=C_LOSS,
            linewidth=2,
            label="break-even (avg ask)" if i == 0 else None,
        )
        ax2.text(
            i, be + 1.5, f"BE ≈ {be:.1f}%", ha="center", fontsize=8, color=C_LOSS, fontweight="bold"
        )
    for b, wr in zip(bars, wrs):
        ax2.text(
            b.get_x() + b.get_width() / 2,
            wr - 5,
            f"{wr:.1f}%",
            ha="center",
            va="top",
            fontsize=10,
            fontweight="bold",
            color="white",
        )
    ax2.set_title("Per-tier WR vs break-even")
    ax2.set_ylabel("Win-rate (%)")
    ax2.set_ylim(0, 100)
    ax2.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_05_surv_pre_post(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    traj = compute_cum_pnl(fires)
    peak_idx, (peak_fire, _) = max(enumerate(traj), key=lambda kv: kv[1][1])
    peak_ts = peak_fire.decision_ts_ns
    surv = [
        f
        for f in settled
        if f.tier == "30-50%" and f.abs_delta_bps is not None and f.abs_delta_bps >= 5
    ]
    pre = [f for f in surv if f.decision_ts_ns <= peak_ts]
    post = [f for f in surv if f.decision_ts_ns > peak_ts]
    s_pre = Stats()
    s_post = Stats()
    for f in pre:
        s_pre.add(f)
    for f in post:
        s_post.add(f)
    metrics = ["n", "WR (%)", "$/trade", "PnL ($)"]
    pre_vals = [s_pre.n, s_pre.wr * 100, s_pre.per_trade, s_pre.pnl_total]
    post_vals = [s_post.n, s_post.wr * 100, s_post.per_trade, s_post.pnl_total]
    fig, axes = plt.subplots(1, 4, figsize=(11, 3.6))
    for ax, m, pv, pov in zip(axes, metrics, pre_vals, post_vals):
        ax.bar(
            ["pre-peak", "post-peak"],
            [pv, pov],
            color=[C_WIN, C_LOSS],
            edgecolor="white",
            linewidth=0.8,
        )
        ax.set_title(m, fontsize=10)
        ymin = min(0, pv, pov) * 1.25
        ymax = max(pv, pov, 0) * 1.25 if max(pv, pov, 0) > 0 else 5
        ax.set_ylim(ymin, ymax)
        for i, v in enumerate([pv, pov]):
            fmt = f"{v:+.1f}" if abs(v) < 10 else f"{v:+,.0f}"
            ax.text(
                i,
                v + (ymax - ymin) * 0.04,
                fmt,
                ha="center",
                va="bottom" if v >= 0 else "top",
                fontsize=9,
                fontweight="bold",
            )
        ax.axhline(0, color="#455a64", linewidth=0.6)
    fig.suptitle(
        "SURV cell (tier 30-50% × |Δbps|≥5) — pre-peak vs post-peak collapse",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_06_path_a_simulator(fires: list[Fire], out: Path) -> None:
    sim = simulate_m5(fires, n_warmup=20, margin_pp=0.02, reset_on_gap_min=None)
    tl = sim["timeline"]
    fire_ts = [datetime.fromtimestamp(e["ts_ns"] / 1e9, tz=UTC) for e in tl]

    active_ts = [t for t, e in zip(fire_ts, tl) if e["rolling_wr"] is not None]
    active_wr = [e["rolling_wr"] * 100 for e in tl if e["rolling_wr"] is not None]
    active_thr = [e["threshold"] * 100 for e in tl if e["rolling_wr"] is not None]
    abstain_ts = [t for t, e in zip(fire_ts, tl) if e["m5_abstain"]]
    abstain_wr = [e["rolling_wr"] * 100 for e in tl if e["m5_abstain"]]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(
        active_ts, active_wr, color=C_ACCENT, linewidth=1.4, label="Path-A rolling WR (20-fire)"
    )
    ax.plot(
        active_ts,
        active_thr,
        color=C_LOSS,
        linewidth=1.0,
        linestyle="--",
        label="Break-even threshold (mean_price + 2pp)",
    )
    ax.fill_between(
        active_ts,
        active_wr,
        active_thr,
        where=[w < t for w, t in zip(active_wr, active_thr)],
        color=C_LOSS,
        alpha=0.15,
        label="M.5 would-abstain region",
    )
    if abstain_ts:
        ax.scatter(
            abstain_ts,
            abstain_wr,
            color=C_LOSS,
            s=14,
            zorder=5,
            label=f"Fires M.5 would abstain (n={len(abstain_ts)})",
        )
    if sim["m5_first_active_ts_ns"]:
        first = datetime.fromtimestamp(sim["m5_first_active_ts_ns"] / 1e9, tz=UTC)
        ax.axvline(
            first,
            color=C_M5,
            linewidth=1.2,
            label=f"M.5 first activatable: {first.strftime('%m-%d %H:%MZ')}",
        )
    # actual M.5 live window
    m5_ship = SHIP_TIMES["M.5"]
    ax.axvspan(m5_ship, HALT_TS, color=C_M5, alpha=0.08, label="M.5 actually live (58 min)")
    ax.set_ylim(40, 100)
    ax.set_title("M.5 activation simulator — Path-A rolling WR vs break-even threshold")
    ax.set_ylabel("Win-rate / threshold (%)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    ax.legend(loc="lower left", fontsize=7, ncol=2)
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_07_m1a_inversion(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    annotated = [f for f in settled if f.regime]

    # Left panel: M.1a v0 annotated subset, n=83
    regimes = ["chop", "mixed", "trending"]
    label_n = {r: sum(1 for f in annotated if f.regime == r) for r in regimes}
    label_wr = {}
    label_pnl = {}
    for r in regimes:
        sub = [f for f in annotated if f.regime == r]
        s = Stats()
        for f in sub:
            s.add(f)
        label_wr[r] = s.wr * 100 if s.n else 0
        label_pnl[r] = s.pnl_total

    # Right panel: |Δbps| proxy on n=755
    proxy_buckets = [
        (0, 2.5, "0-2.5\n(chop-like)"),
        (2.5, 5, "2.5-5\n(flat)"),
        (5, 10, "5-10\n(active)"),
        (10, 1e9, "10+\n(trending)"),
    ]
    proxy_n = []
    proxy_wr = []
    proxy_pnl = []
    proxy_lbls = []
    for lo, hi, lbl in proxy_buckets:
        sub = [f for f in settled if f.abs_delta_bps is not None and lo <= f.abs_delta_bps < hi]
        s = Stats()
        for f in sub:
            s.add(f)
        proxy_n.append(s.n)
        proxy_wr.append(s.wr * 100 if s.n else 0)
        proxy_pnl.append(s.pnl_total)
        proxy_lbls.append(lbl)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    bars = ax1.bar(
        regimes,
        [label_wr[r] for r in regimes],
        color=[C_WIN, C_LOSS, C_NEUTRAL],
        edgecolor="white",
        linewidth=0.8,
    )
    for b, r in zip(bars, regimes):
        ax1.text(
            b.get_x() + b.get_width() / 2,
            b.get_height() - 5,
            f"n={label_n[r]}\nPnL ${label_pnl[r]:+,.0f}",
            ha="center",
            va="top",
            fontsize=9,
            color="white",
            fontweight="bold",
        )
    ax1.set_title("M.1a v0 ANNOTATED subset (n=83, Sat 19:14Z+)")
    ax1.set_ylabel("WR (%)")
    ax1.set_ylim(0, 100)
    ax1.axhline(50, color="#455a64", linewidth=0.6, linestyle=":")
    ax1.text(
        0.02,
        0.95,
        "Chop > mixed WR → INVERSION suspicion\n(n=23 vs 58; M.1a v1 abstains chop)",
        transform=ax1.transAxes,
        fontsize=8,
        va="top",
        bbox=dict(facecolor="#fff3e0", edgecolor=C_M1A, alpha=0.8),
    )

    bars = ax2.bar(
        proxy_lbls,
        proxy_wr,
        color=[C_LOSS, C_LOSS, C_WIN, C_NEUTRAL],
        edgecolor="white",
        linewidth=0.8,
    )
    for b, n, p in zip(bars, proxy_n, proxy_pnl):
        ax2.text(
            b.get_x() + b.get_width() / 2,
            b.get_height() - 5,
            f"n={n}\nPnL ${p:+,.0f}",
            ha="center",
            va="top",
            fontsize=9,
            color="white",
            fontweight="bold",
        )
    ax2.set_title("|Δbps| PROXY regime on ALL data (n=755)")
    ax2.set_ylabel("WR (%)")
    ax2.set_ylim(0, 100)
    ax2.axhline(50, color="#455a64", linewidth=0.6, linestyle=":")
    ax2.text(
        0.02,
        0.95,
        "Chop-like has LOWER WR → opposite of M.1a v0 finding\n→ M.1a classifier ≠ |Δbps| edge structure",
        transform=ax2.transAxes,
        fontsize=8,
        va="top",
        bbox=dict(facecolor="#fff3e0", edgecolor=C_M1A, alpha=0.8),
    )

    fig.suptitle(
        "M.1a v1 inversion test — annotated subset vs |Δbps| proxy regime",
        fontweight="bold",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_08_hour_heatmap(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    tiers = ["30-50%", "70-85%"]
    grid = [[0.0 for _ in range(24)] for _ in tiers]
    ns = [[0 for _ in range(24)] for _ in tiers]
    for f in settled:
        h = datetime.fromtimestamp(f.decision_ts_ns / 1e9, tz=UTC).hour
        ti = tiers.index(f.tier) if f.tier in tiers else None
        if ti is None:
            continue
        grid[ti][h] += f.pnl_usd
        ns[ti][h] += 1
    fig, ax = plt.subplots(figsize=(11, 3.6))
    vmax = max(max(row) for row in grid)
    vmin = min(min(row) for row in grid)
    bound = max(abs(vmax), abs(vmin))
    im = ax.imshow(grid, cmap="RdYlGn", aspect="auto", vmin=-bound, vmax=bound)
    ax.set_yticks(range(len(tiers)))
    ax.set_yticklabels(tiers)
    ax.set_xticks(range(24))
    ax.set_xticklabels([f"{h:02d}" for h in range(24)])
    ax.set_xlabel("UTC hour")
    ax.set_title(
        "Per-UTC-hour × tier PnL ($) — gaps in J.2 blocklist (currently 22/23/00 × tier 70-85% only)"
    )
    for i in range(len(tiers)):
        for h in range(24):
            v = grid[i][h]
            if abs(v) > 0:
                ax.text(
                    h,
                    i,
                    f"{v:+.0f}\nn{ns[i][h]}",
                    ha="center",
                    va="center",
                    fontsize=6.5,
                    color="white" if abs(v) > bound * 0.55 else "#263238",
                )
    plt.colorbar(im, ax=ax, label="PnL ($)")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_09_daily_breakdown(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    by: dict[tuple[str, str], float] = defaultdict(float)
    days = sorted({fmt_ts(f.decision_ts_ns).split(" ")[0] for f in settled})
    for f in settled:
        d = fmt_ts(f.decision_ts_ns).split(" ")[0]
        cell = f"{f.tier} {f.side[:1]}"
        by[(d, cell)] += f.pnl_usd

    cells = ["30-50% U", "30-50% D", "70-85% D"]
    cell_colors = ["#ff8a65", "#ffb74d", "#ba68c8"]
    x = range(len(days))
    width = 0.26
    fig, ax = plt.subplots(figsize=(11, 4.2))
    for i, (c, col) in enumerate(zip(cells, cell_colors)):
        vals = [by.get((d, c), 0) for d in days]
        offs = [xv + (i - 1) * width for xv in x]
        ax.bar(offs, vals, width=width, color=col, edgecolor="white", linewidth=0.8, label=c)
    ax.axhline(0, color="#455a64", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(days)
    ax.set_ylabel("Daily PnL by cell ($)")
    ax.set_title(
        "Daily PnL × tier × side — Path-A bleeds across 3 days; tier 30-50% DN imploded 05-16"
    )
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_10_restarts(fires: list[Fire], out: Path) -> None:
    gaps = detect_restarts(fires, gap_min=30.0)
    # Two-panel: cum-PnL with restart markers + bar of gap durations
    traj = compute_cum_pnl(fires)
    xs = [_ts(f) for f, _ in traj]
    ys = [c for _, c in traj]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 5.8), gridspec_kw={"height_ratios": [3, 2]})
    ax1.plot(xs, ys, color=C_ACCENT, linewidth=1.4)
    for _, ts_ns, m in gaps:
        ts = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)
        color = C_LOSS if m > 60 else C_NEUTRAL
        ax1.axvline(ts, color=color, alpha=0.5, linewidth=0.8)
    ax1.axhline(0, color="#455a64", linewidth=0.6)
    ax1.set_title(f"Cum-PnL with {len(gaps)} likely-restart markers (gap >30 min between fires)")
    ax1.set_ylabel("Cum PnL ($)")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax1.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))

    # bar chart of gap durations
    gap_ts = [datetime.fromtimestamp(ts_ns / 1e9, tz=UTC) for _, ts_ns, _ in gaps]
    gap_mins = [m for _, _, m in gaps]
    ax2.bar(gap_ts, gap_mins, width=0.05, color=[C_LOSS if m > 60 else C_NEUTRAL for m in gap_mins])
    ax2.set_ylabel("Gap (min)")
    ax2.set_title("Restart gap durations — note the 177-min outage on 05-17 02:46Z")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax2.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_11_delta_bps_buckets(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None and f.abs_delta_bps is not None]
    buckets = [(0, 2.5), (2.5, 5), (5, 10), (10, 1e9)]
    labels = ["0-2.5", "2.5-5", "5-10", "10+"]
    # tier 30-50% and tier 70-85% only
    rows = []
    for t in ("30-50%", "70-85%"):
        row_wr = []
        row_pnl = []
        row_n = []
        for lo, hi in buckets:
            sub = [f for f in settled if f.tier == t and lo <= f.abs_delta_bps < hi]
            s = Stats()
            for f in sub:
                s.add(f)
            row_wr.append(s.wr * 100 if s.n else 0)
            row_pnl.append(s.pnl_total)
            row_n.append(s.n)
        rows.append((t, row_wr, row_pnl, row_n))

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
    x = list(range(len(labels)))
    width = 0.36
    for ax, (t, wr, pnl, ns) in zip(axes, rows):
        b1 = ax.bar([xv - width / 2 for xv in x], wr, width=width, color=C_ACCENT, label="WR (%)")
        ax2 = ax.twinx()
        colors = [C_WIN if p >= 0 else C_LOSS for p in pnl]
        ax2.bar(
            [xv + width / 2 for xv in x],
            pnl,
            width=width,
            color=colors,
            alpha=0.85,
            label="PnL ($)",
        )
        for i, (w, p, n) in enumerate(zip(wr, pnl, ns)):
            ax.text(i - width / 2, w + 2, f"n={n}", ha="center", fontsize=8, color="#263238")
            ax2.text(
                i + width / 2,
                p + (8 if p >= 0 else -8),
                f"${p:+,.0f}",
                ha="center",
                va="bottom" if p >= 0 else "top",
                fontsize=8,
                fontweight="bold",
                color="white" if abs(p) > 200 else "#263238",
            )
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(f"tier {t}: WR + PnL by |Δbps|")
        ax.set_xlabel("|Δbps| bucket")
        ax.set_ylabel("WR (%)")
        ax2.set_ylabel("PnL ($)")
        ax.set_ylim(0, 100)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_12_ch3_surv_contrast(fires: list[Fire], out: Path) -> None:
    settled = [f for f in fires if f.pnl_usd is not None]
    tier_30 = [f for f in settled if f.tier == "30-50%"]
    ch3 = [f for f in tier_30 if f.abs_delta_bps is not None and f.abs_delta_bps < 5]
    surv = [f for f in tier_30 if f.abs_delta_bps is not None and f.abs_delta_bps >= 5]
    s_ch3 = Stats()
    for f in ch3:
        s_ch3.add(f)
    s_surv = Stats()
    for f in surv:
        s_surv.add(f)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8))
    # CH3 timeline: cumulative PnL
    ch3.sort(key=lambda f: f.decision_ts_ns)
    cum = 0.0
    xs = []
    ys = []
    for f in ch3:
        cum += f.pnl_usd
        xs.append(_ts(f))
        ys.append(cum)
    ax1.plot(xs, ys, color=C_LOSS, linewidth=1.4)
    ax1.fill_between(xs, 0, ys, color=C_LOSS, alpha=0.15)
    ax1.axhline(0, color="#455a64", linewidth=0.6)
    j15_fold = datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)  # approx J.1.5 fold time
    ax1.axvline(j15_fold, color=C_M5, linestyle="--", linewidth=1.2)
    ax1.text(
        j15_fold,
        ys[-1] * 0.5 if ys else -100,
        " J.1.5 fold\n no fires after",
        color=C_M5,
        fontsize=8,
        va="center",
    )
    ax1.set_title(f"CH3 cell cumPnL (tier 30-50% × |Δ|<5)  n={s_ch3.n}  ${s_ch3.pnl_total:+,.0f}")
    ax1.set_ylabel("CH3 cum-PnL ($)")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    # SURV timeline: cumulative PnL
    surv.sort(key=lambda f: f.decision_ts_ns)
    cum = 0.0
    xs = []
    ys = []
    for f in surv:
        cum += f.pnl_usd
        xs.append(_ts(f))
        ys.append(cum)
    ax2.plot(xs, ys, color=C_ACCENT, linewidth=1.4)
    ax2.fill_between(xs, 0, ys, where=[y >= 0 for y in ys], color=C_WIN, alpha=0.15)
    ax2.fill_between(xs, 0, ys, where=[y < 0 for y in ys], color=C_LOSS, alpha=0.15)
    ax2.axhline(0, color="#455a64", linewidth=0.6)
    ax2.axvline(PEAK_TS, color="#37474f", linestyle="--", linewidth=1.2)
    ax2.text(
        PEAK_TS,
        ys[-1] * 0.6 if ys else 500,
        " PEAK\n then collapse",
        color="#37474f",
        fontsize=8,
        va="center",
    )
    ax2.set_title(
        f"SURV cell cumPnL (tier 30-50% × |Δ|≥5)  n={s_surv.n}  ${s_surv.pnl_total:+,.0f}"
    )
    ax2.set_ylabel("SURV cum-PnL ($)")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate(rotation=45)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_13_phase_timeline(out: Path) -> None:
    """A pure-narrative timeline panel of all 5 Phases + ship dates + dataset window."""
    events = [
        (datetime(2026, 5, 13, 0, 56, 0, tzinfo=UTC), "H.2.12 path-A ships", C_L5),
        (datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC), "J.1.5 fold (CH3)", C_M5),
        (datetime(2026, 5, 14, 18, 36, 0, tzinfo=UTC), "J.1.6 Kelly 0.15× + replay", C_L5),
        (PEAK_TS, "PEAK +$1,235", C_WIN),
        (SHIP_TIMES["L.5"], "L.5 daily-PnL auto-halt", C_L5),
        (SHIP_TIMES["M.1a v0"], "M.1a v0 regime SHADOW", C_M1A),
        (SHIP_TIMES["M.1a v1"], "M.1a v1 chop ABSTAIN", C_M1A),
        (SHIP_TIMES["M.5"], "M.5 path-A regime wrap", C_M5),
        (SHIP_TIMES["M.2 v0"], "M.2 v0 imbalance SHADOW", C_M2),
        (HALT_TS, "HALT (operator)", C_LOSS),
    ]
    fig, ax = plt.subplots(figsize=(11, 3.0))
    for ts, label, color in events:
        ax.axvline(ts, color=color, linewidth=1.2)
        ax.text(
            ts,
            0.5,
            " " + label,
            color=color,
            rotation=45,
            fontsize=8,
            va="bottom",
            ha="left",
            fontweight="bold",
        )
    ax.set_xlim(datetime(2026, 5, 13, tzinfo=UTC), datetime(2026, 5, 17, 23, tzinfo=UTC))
    ax.set_ylim(0, 1.5)
    ax.set_yticks([])
    ax.set_title("Phase timeline — what shipped when across the dataset window")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def chart_14_hypothesis_attribution(out: Path) -> None:
    """Horizontal bar chart of empirical-loss attribution for the -$1,562 peak-to-floor swing."""
    # Hand-derived from the audit:
    # SURV cell post-peak collapse: -$1,161 (the single largest)
    # Path A post-peak bleed:        -$543 (3-day bleeder, mostly post-peak)
    # Tier 30-50% UP post-peak:      -$276 (5/16 + 5/17 combined)
    # CH3 pre-fold leakage:          -$228 (locked, no post-peak; informational)
    # (these overlap conceptually; the chart should not double-count)
    # We use a tier×side×|Δ|bps decomposition of post-peak fires only:
    contributions = [
        ("SURV cell post-peak (tier 30-50% × |Δ|≥5)", -1161, C_LOSS),
        ("Path A post-peak (tier 70-85% × DN)", -300, C_LOSS),
        ("tier 30-50% UP post-peak", -276, C_LOSS),
        ("tier 30-50% × |Δ|<5 post-peak (negligible)", 0, C_NEUTRAL),
        ("Other / unattributed", 175, C_WIN),
    ]
    labels = [c[0] for c in contributions]
    vals = [c[1] for c in contributions]
    colors = [c[2] for c in contributions]
    fig, ax = plt.subplots(figsize=(11, 3.6))
    bars = ax.barh(labels, vals, color=colors, edgecolor="white", linewidth=0.8)
    for b, v in zip(bars, vals):
        ax.text(
            v + (40 if v >= 0 else -40),
            b.get_y() + b.get_height() / 2,
            f"${v:+,.0f}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=9,
            fontweight="bold",
        )
    ax.axvline(0, color="#455a64", linewidth=0.8)
    ax.set_title("Loss attribution for the peak→floor swing (−$1,562) — post-peak decomposition")
    ax.set_xlabel("Contribution to swing ($)")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fires, _ = load_data(DATA_DIR)
    charts = [
        ("01_cumulative_pnl", chart_01_cumulative_pnl),
        ("02_bankroll_trajectory", chart_02_bankroll),
        ("03_daily_pnl_bar", chart_03_daily_pnl),
        ("04_per_tier_pnl_wr", chart_04_per_tier_pnl),
        ("05_surv_pre_post_peak", chart_05_surv_pre_post),
        ("06_m5_activation_simulator", chart_06_path_a_simulator),
        ("07_m1a_inversion_test", chart_07_m1a_inversion),
        ("08_hour_x_tier_heatmap", chart_08_hour_heatmap),
        ("09_daily_x_tier_x_side", chart_09_daily_breakdown),
        ("10_restart_markers", chart_10_restarts),
        ("11_delta_bps_x_tier", chart_11_delta_bps_buckets),
        ("12_ch3_vs_surv_contrast", chart_12_ch3_surv_contrast),
        ("14_loss_attribution", chart_14_hypothesis_attribution),
    ]
    for name, fn in charts:
        out = OUT_DIR / f"{name}.png"
        try:
            fn(fires, out)
        except TypeError:
            fn(out)  # no-fires charts (e.g. phase timeline)
        print(f"  wrote {out.relative_to(ROOT)}")
    chart_13_phase_timeline(OUT_DIR / "13_phase_timeline.png")
    print(f"  wrote {(OUT_DIR / '13_phase_timeline.png').relative_to(ROOT)}")
    print(f"\nTotal charts written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

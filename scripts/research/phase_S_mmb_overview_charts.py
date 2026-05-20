"""Phase S MMB overview — chart generator for PHASE_S_MMB_OVERVIEW.pdf.

Generates 8 PNG charts to state/research/phase-S-charts/ that the PDF
builder embeds. All numbers sourced from docs cited in the PDF; no live
data (MMB has not fired live yet).

Usage:
    uv run --with matplotlib python -u scripts/research/phase_S_mmb_overview_charts.py
"""

# ruff: noqa: RUF001, RUF002, RUF003

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "state" / "research" / "phase-S-charts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Light-on-white palette — readable when embedded in dark-terminal PDF.
C_WIN = "#2e7d32"
C_LOSS = "#c62828"
C_NEUTRAL = "#546e7a"
C_ACCENT = "#1565c0"
C_BAND_HI = "#81c784"
C_BAND_MID = "#42a5f5"
C_BAND_LO = "#ef5350"
C_MMB = "#00897b"
C_OLD = "#8e24aa"


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


# ---------------------------------------------------------------------------
# Chart 1: Directional-bot phase history — bankroll trajectory + halt points
# ---------------------------------------------------------------------------
def chart_directional_bot_history() -> None:
    """The honest Phase J→K→L→M→N→O history: $1k peak/trough/halt sequence."""
    # Anchor points from memory checkpoints (checkpoint_phase_{J,K,M,O,P}.md).
    events = [
        ("2026-05-14\nJ.1.6 ship\nKelly 0.15x + replay live", 1000, "ship"),
        ("2026-05-15 15:40Z\nPeak", 2235, "peak"),
        ("2026-05-16\nDay-4 daily-loss\ntrips x17", 1095, "trough"),
        ("2026-05-16\nPhase K closed\noperator override", 1095, "milestone"),
        ("2026-05-17 11:25-11:58Z\nFive M.* layers shipped\n(78 min live time)", 800, "ship"),
        ("2026-05-17 12:43Z\nHALT (operator-cooldown)\n$673 / cum -$327", 673, "halt"),
        ("2026-05-17 21:37Z\nPhase O cut → P hard revert\n$1 fire = LOSS -$163", 510, "halt"),
    ]
    xs = list(range(len(events)))
    ys = [e[1] for e in events]
    labels = [e[0] for e in events]
    kinds = [e[2] for e in events]

    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.plot(xs, ys, color=C_NEUTRAL, linewidth=1.5, zorder=1)
    for x, y, kind in zip(xs, ys, kinds, strict=False):
        color = {
            "ship": C_ACCENT,
            "peak": C_WIN,
            "trough": "#fb8c00",
            "milestone": C_NEUTRAL,
            "halt": C_LOSS,
        }[kind]
        marker = {"peak": "*", "halt": "x", "trough": "v", "ship": "o", "milestone": "s"}[kind]
        size = 200 if kind in ("peak", "halt") else 100
        ax.scatter(
            x, y, color=color, marker=marker, s=size, zorder=3, edgecolor="black", linewidth=0.5
        )

    ax.axhline(
        1000, color=C_NEUTRAL, linestyle=":", linewidth=0.8, label="Starting bankroll $1,000"
    )
    ax.axhline(
        2000, color=C_WIN, linestyle=":", linewidth=0.6, alpha=0.5, label="HW-wallet trigger $2,000"
    )
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=0, fontsize=6.5, ha="center")
    ax.set_ylabel("Bankroll ($)")
    ax.set_title("Directional bot phase history — peak, halt, hard revert")
    ax.set_ylim(0, 2500)
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "01_directional_history.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 2: Per-tier × side $/tr — Edge 1 blocklist visualization
# ---------------------------------------------------------------------------
def chart_tier_side_dollar_per_trade() -> None:
    """From mmb-deep-edge-audit-2026-05-20.md §2 Edge 1 (n=21,633 fresh weekly)."""
    tiers = ["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]
    up = [0.09, -0.61, -0.11, 0.04, 0.42, 3.07]
    dn = [4.07, 0.58, 1.63, -0.76, 0.37, 2.75]
    # Mark blocked cells (from Edge 1 blocklist).
    blocked_up = {"15-30%", "30-50%"}
    blocked_dn = {"50-70%"}

    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    x = np.arange(len(tiers))
    w = 0.38
    bars_up = ax.bar(x - w / 2, up, w, label="UP", color=C_ACCENT, edgecolor="black", linewidth=0.4)
    bars_dn = ax.bar(x + w / 2, dn, w, label="DOWN", color=C_MMB, edgecolor="black", linewidth=0.4)

    # Mark blocked bars with a hatch + thick red border.
    for bar, tier in zip(bars_up, tiers, strict=False):
        if tier in blocked_up:
            bar.set_hatch("///")
            bar.set_edgecolor(C_LOSS)
            bar.set_linewidth(1.5)
    for bar, tier in zip(bars_dn, tiers, strict=False):
        if tier in blocked_dn:
            bar.set_hatch("///")
            bar.set_edgecolor(C_LOSS)
            bar.set_linewidth(1.5)

    ax.axhline(0, color="#263238", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(tiers)
    ax.set_ylabel("$/trade")
    ax.set_xlabel("Best-ask tier")
    ax.set_title(
        "Bonereaper fresh-weekly per-tier × side $/trade  (n=21,633 fills 2026-05-19)\n"
        "Hatched red-border = Edge 1 blocklist (MMB does NOT ladder these)"
    )
    ax.legend(loc="upper left", fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Annotate the strongest cell.
    ax.annotate(
        "Strongest cell\n+$4.07/tr × 865 fills",
        xy=(0 + w / 2, 4.07),
        xytext=(0.6, 4.5),
        fontsize=8,
        color=C_WIN,
        arrowprops=dict(arrowstyle="->", color=C_WIN, lw=0.8),
    )
    ax.annotate(
        "Biggest leak\n−$0.76/tr × 3,366 fills",
        xy=(3 + w / 2, -0.76),
        xytext=(3.5, -1.5),
        fontsize=8,
        color=C_LOSS,
        arrowprops=dict(arrowstyle="->", color=C_LOSS, lw=0.8),
    )

    fig.tight_layout()
    fig.savefig(OUT_DIR / "02_tier_side_dollar_per_trade.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 3: Late-window placement edge — Edge 2 visualization
# ---------------------------------------------------------------------------
def chart_late_window_edge() -> None:
    """Time-bucket × side $/tr from audit §2 Edge 2 (n=21,633 fresh weekly)."""
    buckets = ["0-30s", "30-60s", "60-120s", "120-180s", "180-240s", "240-300s"]
    up = [3.64, 1.82, -0.24, 0.08, 0.28, -0.20]
    dn = [12.09, 1.14, 0.39, 0.92, 0.43, 0.07]

    fig, ax = plt.subplots(figsize=(9.5, 4.5))
    x = np.arange(len(buckets))
    w = 0.38
    ax.bar(x - w / 2, up, w, label="UP", color=C_ACCENT, edgecolor="black", linewidth=0.4)
    ax.bar(x + w / 2, dn, w, label="DOWN", color=C_MMB, edgecolor="black", linewidth=0.4)
    ax.axhline(0, color="#263238", linewidth=0.6)
    ax.axvspan(-0.5, 1.5, alpha=0.12, color=C_WIN, label="LATE window (Edge 2: 2x size multiplier)")
    ax.set_xticks(x)
    ax.set_xticklabels(buckets)
    ax.set_ylabel("$/trade")
    ax.set_xlabel("Seconds remaining in 5-min window  (←  later in window  ←)")
    ax.set_title(
        "Late-window edge — $/trade by seconds-from-resolution  (n=21,633 fresh-weekly fills)"
    )
    ax.legend(loc="upper right", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "03_late_window_edge.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 4 + 5: Projection fan charts — $1k and $10k bankrolls, weeks 1-12
# ---------------------------------------------------------------------------
def _projection_bands(
    start: float, weeks: int = 12
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate three-band weekly bankroll trajectories.

    From mmb-deep-edge-audit-2026-05-20.md §5:
      - low band: queue-position penalty 70% → ~+15% weekly
      - mid band: penalty 50% → ~+80% weekly weeks 1-4, decay after
      - high band: penalty 30% → ~+150% weekly weeks 1-4, decay after market-depth bite
    Decay starts week 4 (market depth begins to bite) and tightens by week 8.
    Hard ceiling: bonereaper turns ~$766k/wk gross on ~$100k bankroll, so MMB's
    realistic depth ceiling is around $30-50k bankroll.
    """
    weeks_arr = np.arange(weeks + 1)
    # Weekly growth rates per band, with decay past week 4 (market depth).
    lo_rate = np.array([0.15] * (weeks + 1))
    mid_rate = np.array(
        [0.80, 0.80, 0.80, 0.80, 0.55, 0.40, 0.30, 0.20, 0.15, 0.10, 0.08, 0.06, 0.05][: weeks + 1]
    )
    hi_rate = np.array(
        [1.50, 1.50, 1.50, 1.20, 0.90, 0.60, 0.40, 0.25, 0.18, 0.12, 0.10, 0.08, 0.06][: weeks + 1]
    )

    def compound(rates: np.ndarray) -> np.ndarray:
        traj = np.zeros(len(rates))
        traj[0] = start
        for i in range(1, len(rates)):
            # Hard market-depth ceiling at $50k effective.
            ceil = 50_000.0
            soft_cap = max(0.0, 1.0 - traj[i - 1] / ceil)
            traj[i] = traj[i - 1] * (1 + rates[i] * soft_cap)
        return traj

    return weeks_arr, compound(lo_rate), compound(mid_rate), compound(hi_rate)


def _draw_fan(ax, start: float, weeks: int = 12) -> None:
    w, lo, mid, hi = _projection_bands(start, weeks)
    ax.fill_between(
        w,
        lo,
        hi,
        color=C_BAND_MID,
        alpha=0.15,
        label="Range (low penalty 70%  ↔  high penalty 30%)",
    )
    ax.fill_between(w, lo, mid, color=C_BAND_LO, alpha=0.12)
    ax.plot(
        w,
        hi,
        color=C_WIN,
        linewidth=1.6,
        label=f"HIGH band (queue penalty 30%) — wk1 +${hi[1] - start:,.0f}",
    )
    ax.plot(
        w,
        mid,
        color=C_ACCENT,
        linewidth=1.8,
        label=f"MID band  (queue penalty 50%) — wk1 +${mid[1] - start:,.0f}",
    )
    ax.plot(
        w,
        lo,
        color=C_LOSS,
        linewidth=1.6,
        label=f"LOW band   (queue penalty 70%) — wk1 +${lo[1] - start:,.0f}",
    )
    ax.axhline(start, color=C_NEUTRAL, linestyle=":", linewidth=0.8)
    ax.axhline(
        50_000,
        color=C_WIN,
        linestyle="--",
        linewidth=0.7,
        alpha=0.6,
        label="Market-depth ceiling ~$50k",
    )
    ax.set_xlabel("Week from go-live")
    ax.set_ylabel("Bankroll ($)")
    ax.set_xticks(range(0, weeks + 1, 2))
    ax.legend(loc="upper left", fontsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, alpha=0.4)


def chart_projection_1k() -> None:
    style()
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    _draw_fan(ax, start=1000)
    ax.set_title(
        "Projection: $1,000 starting bankroll  (3 queue-position penalty bands)\n"
        "Per mmb-deep-edge-audit §5 — assumes edges 1+2 active, MM_CAPS_MODE=pct_bankroll from week 2"
    )
    ax.set_yscale("log")
    ax.set_yticks([1000, 2000, 5000, 10_000, 20_000, 50_000])
    ax.set_yticklabels(["$1k", "$2k", "$5k", "$10k", "$20k", "$50k"])
    fig.tight_layout()
    fig.savefig(OUT_DIR / "04_projection_1k.png", bbox_inches="tight")
    plt.close(fig)


def chart_projection_10k() -> None:
    style()
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    _draw_fan(ax, start=10_000)
    ax.set_title(
        "Projection: $10,000 starting bankroll  (3 queue-position penalty bands)\n"
        "Hypothetical scenario — assumes Day-7 PASS + HW wallet wired (decision #12 at $2k trigger)"
    )
    ax.set_yscale("log")
    ax.set_yticks([10_000, 20_000, 50_000, 100_000])
    ax.set_yticklabels(["$10k", "$20k", "$50k", "$100k"])
    fig.tight_layout()
    fig.savefig(OUT_DIR / "05_projection_10k.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 6: pct_bankroll vs fixed_usd compounding
# ---------------------------------------------------------------------------
def chart_caps_mode_compounding() -> None:
    """From audit §4 — fixed caps choke compounding past ~week 4."""
    weeks = np.arange(13)
    growth = 0.50  # baseline weekly compounding (mid-band, edges active)
    # Fixed caps: cap binds after bankroll hits the cap ceiling.
    # At $1k bankroll, $50 cap = 5% of bankroll. As bankroll grows the cap
    # becomes a smaller pct → compounding slows.
    fixed = np.zeros(13)
    pct = np.zeros(13)
    fixed[0] = pct[0] = 1000.0
    for i in range(1, 13):
        # fixed: growth scales as (cap / bankroll) — effective edge shrinks
        eff_pct = min(0.05, 50.0 / fixed[i - 1])  # 5% pct cap, $50 absolute cap
        fixed[i] = fixed[i - 1] * (1 + growth * (eff_pct / 0.05))
        # pct: cap is always 5% of bankroll, growth rate constant
        pct[i] = pct[i - 1] * (1 + growth)

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.plot(
        weeks,
        fixed,
        color=C_LOSS,
        linewidth=2,
        marker="o",
        markersize=4,
        label="MM_CAPS_MODE=fixed_usd  (current S.5 deploy default)",
    )
    ax.plot(
        weeks,
        pct,
        color=C_WIN,
        linewidth=2,
        marker="s",
        markersize=4,
        label="MM_CAPS_MODE=pct_bankroll  (S.6+ after Day-7 PASS)",
    )
    ax.axhline(1000, color=C_NEUTRAL, linestyle=":", linewidth=0.7, label="$1,000 start")
    ax.axhline(
        50_000, color=C_WIN, linestyle="--", linewidth=0.6, alpha=0.5, label="Market-depth ceiling"
    )
    ax.set_xlabel("Week")
    ax.set_ylabel("Bankroll ($)")
    ax.set_title(
        "Compounding lock — fixed_usd vs pct_bankroll  (assumes +50% weekly mid-band)\n"
        "Cap shrinks as bankroll grows in fixed mode → mathematical lid around $5-10k"
    )
    ax.set_yscale("log")
    ax.set_yticks([1000, 5000, 10_000, 50_000, 100_000])
    ax.set_yticklabels(["$1k", "$5k", "$10k", "$50k", "$100k"])
    ax.legend(loc="upper left", fontsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "06_caps_mode_compounding.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 7: System architecture block diagram
# ---------------------------------------------------------------------------
def chart_architecture_diagram() -> None:
    fig, ax = plt.subplots(figsize=(9.5, 6.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    def box(x, y, w, h, label, color="#cfd8dc", text_color="#263238", fontsize=9, lw=1.0):
        rect = plt.Rectangle(
            (x, y), w, h, facecolor=color, edgecolor="black", linewidth=lw, zorder=2
        )
        ax.add_patch(rect)
        ax.text(
            x + w / 2,
            y + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            zorder=3,
        )

    def arrow(x1, y1, x2, y2, label="", color="#263238", style="->"):
        ax.annotate(
            "",
            xy=(x2, y2),
            xytext=(x1, y1),
            arrowprops=dict(arrowstyle=style, color=color, lw=1.0),
            zorder=1,
        )
        if label:
            ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 1, label, ha="center", fontsize=7, color=color)

    # On-chain layer (top)
    box(2, 85, 20, 10, "MetaMask EOA\n(PK_SIGNER)", color="#fff9c4")
    box(28, 85, 22, 10, "Polymarket Safe proxy\n(POLY_FUNDER)", color="#ffe082")
    box(56, 85, 20, 10, "CTF Exchange\n0x4bFb...8982E", color="#ffcdd2")
    box(82, 85, 16, 10, "USDC.e\n0x2791...4174", color="#c8e6c9")
    arrow(22, 90, 28, 90, "owns")
    arrow(50, 90, 56, 90, "approves\n(MAX_UINT256)")
    arrow(76, 90, 82, 90, "spends")

    # CLOB API layer
    box(
        20,
        67,
        60,
        10,
        "Polymarket CLOB API  (https://clob.polymarket.com)\n"
        "L1 EIP-712 order signing  +  L2 HMAC-SHA256 (CLOB_API_KEY/SECRET/PASSPHRASE)",
        color="#b3e5fc",
    )
    arrow(50, 85, 50, 77, "")

    # Bot core (middle)
    box(2, 48, 18, 11, "run_mm_live.py\n(VPS entrypoint)\n+ 4 preflight gates", color="#d1c4e9")
    box(24, 48, 16, 11, "MmRunner\n(orchestration)", color="#d1c4e9")
    box(44, 48, 18, 11, "MarketMakerStrategy\nLadderPlanner", color="#b39ddb")
    box(66, 48, 16, 11, "RiskGate\n+ RiskCaps", color="#9575cd")
    box(86, 48, 12, 11, "J7Priors\n(kelly_mult)", color="#7e57c2")
    arrow(20, 53, 24, 53, "")
    arrow(40, 53, 44, 53, "")
    arrow(62, 53, 66, 53, "")
    arrow(82, 53, 86, 53, "")
    arrow(50, 67, 50, 59, "place /\ncancel")

    # Edges layer (annotated on strategy)
    box(
        38,
        35,
        30,
        8,
        "Edge 1: per-tier-side blocklist\nEdge 2: late-window 2x size",
        color="#fff59d",
        fontsize=7.5,
    )
    arrow(53, 48, 53, 43, "")

    # Bankroll / state layer
    box(2, 25, 18, 8, "decision log\nstate/mm-decisions/", color="#e1bee7")
    box(24, 25, 16, 8, "halt sentinel\nstate/halt.sentinel", color="#ef9a9a")
    box(44, 25, 18, 8, "allowance audit\nstate/mm-allowance.json", color="#e1bee7")
    box(66, 25, 32, 8, "bankroll replay\n(replay_bankroll over decision log)", color="#e1bee7")
    arrow(11, 33, 11, 48, "")
    arrow(32, 33, 32, 48, "")
    arrow(82, 33, 82, 48, "")

    # Safety + ops layer (bottom)
    box(2, 10, 18, 8, "heartbeat 5s\n2-miss → halt", color="#ffab91")
    box(24, 10, 18, 8, "Telegram alerter\n(/halt control)", color="#ffcc80")
    box(46, 10, 18, 8, "dashboard\n:8505", color="#80deea")
    box(68, 10, 14, 8, "litestream\n→ S3", color="#80cbc4")
    box(84, 10, 14, 8, "tg-alerter\nRedis sink", color="#ffcc80")
    arrow(11, 18, 11, 25, "")
    arrow(32, 18, 32, 25, "")

    # Title
    ax.text(
        50, 99, "Phase S MMB — system architecture", ha="center", fontsize=12, fontweight="bold"
    )
    fig.tight_layout()
    fig.savefig(OUT_DIR / "07_architecture.png", bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Chart 8: Backtest tier PnL (Session 2 sim, n=12,332 positions)
# ---------------------------------------------------------------------------
def chart_backtest_tier_pnl() -> None:
    """From mmb-backtest-2026-05-20.md Per-tier MMB PnL table."""
    tiers = ["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]
    pnls = [-1440.76, 266.08, 1261.34, 1399.02, 707.39, -606.71]
    n_positions = [1007, 1102, 3306, 4406, 1586, 925]
    colors = [C_LOSS if p < 0 else C_WIN for p in pnls]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.5, 4.2))

    ax1.bar(tiers, pnls, color=colors, edgecolor="black", linewidth=0.4)
    ax1.axhline(0, color="#263238", linewidth=0.6)
    ax1.set_ylabel("MMB sim PnL ($)")
    ax1.set_title("Per-tier sim PnL  (7-day backtest, $1k bankroll, n=12,332 positions)")
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    for tier, p in zip(tiers, pnls, strict=False):
        ax1.text(
            tier,
            p + (50 if p > 0 else -100),
            f"${p:+,.0f}",
            ha="center",
            fontsize=7.5,
            color="#263238",
        )

    # Show why <15% loses despite priors-table edge.
    ax2.bar(tiers, n_positions, color=C_NEUTRAL, edgecolor="black", linewidth=0.4)
    ax2.set_ylabel("n positions")
    ax2.set_title("Per-tier position count")
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "08_backtest_tier_pnl.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    style()
    chart_directional_bot_history()
    chart_tier_side_dollar_per_trade()
    chart_late_window_edge()
    chart_projection_1k()
    chart_projection_10k()
    chart_caps_mode_compounding()
    chart_architecture_diagram()
    chart_backtest_tier_pnl()
    print(f"wrote 8 charts to {OUT_DIR}")


if __name__ == "__main__":
    main()

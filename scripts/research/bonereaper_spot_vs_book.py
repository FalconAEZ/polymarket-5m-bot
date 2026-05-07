"""Bonereaper spot-vs-book correlation analysis — test the "did they read spot?" question.

Follow-up to bonereaper_microstructure.py. After both market-making and
late-window-sniping hypotheses fell, the remaining open question for the
operator is: **does Bonereaper use BTC spot price information to pick a
side?** The microstructure data showed they enter early (first minute most
common), constantly (96.7% market coverage), with tiny edges concentrated
on favorites. None of that tells us WHAT signals their side selection.

This script joins the bonereaper trade dump (output of
bonereaper_microstructure.py) against captured BTC spot ticks (Binance
trades parquet from a sibling worktree's Phase 4 capture) and asks:

  1. For each Bonereaper trade, what was the BTC spot price at:
     - window_ts (window open, the resolution reference S0)
     - trade.ts (entry, St)
  2. Δ_bps = 10000 * (St - S0) / S0 — how much has price moved in the
     window so far at entry time?
  3. Was Bonereaper's bet "spot-aligned" (UP bet when Δ > 0, DOWN bet
     when Δ < 0) or "contrarian"?
  4. Does their win rate scale with |Δ_bps| in the spot-aligned bucket?

If win rate at large positive Δ_bps for UP bets is meaningfully above the
implied probability at entry, we've found their signal: they bet UP when
spot has already moved up, paying less than fair value because Polymarket
hasn't fully repriced.

Caveats:
  - Captured spot data is small (a few hours of 2026-05-06/07). Most
    bonereaper trades will NOT have matching spot data; we report on
    the overlap subset only.
  - Binance + Coinbase trade ticks; using Binance as canonical (highest
    BTC volume venue worldwide).

Usage:
  uv run python -u scripts/research/bonereaper_spot_vs_book.py \
    --trades-json state/research/bonereaper/microstructure-trades.json \
    --ticks-root /path/to/bold-galileo-2d56ca/ticks

Output:
  runbooks/research/bonereaper-spot-vs-book-<date>.md
  state/research/bonereaper/spot-vs-book-joined.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = PROJECT_ROOT / "state" / "research" / "bonereaper"
RUNBOOK_DIR = PROJECT_ROOT / "runbooks" / "research"

# Δ_bps buckets (where 1 bp = 0.01% price change relative to window-open S0)
# 5-min BTC moves: typical 0-20 bps, occasional 50+ bps.
DELTA_BUCKETS_BPS: list[tuple[float, float, str]] = [
    (-1e9, -50.0, "Δ<-50bps (down hard)"),
    (-50.0, -20.0, "-50..-20bps"),
    (-20.0, -10.0, "-20..-10bps"),
    (-10.0, -5.0, "-10..-5bps"),
    (-5.0, 5.0, "-5..+5bps (flat)"),
    (5.0, 10.0, "+5..+10bps"),
    (10.0, 20.0, "+10..+20bps"),
    (20.0, 50.0, "+20..+50bps"),
    (50.0, 1e9, "Δ>+50bps (up hard)"),
]


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_binance_ticks(ticks_root: Path) -> pl.DataFrame:
    """Load all binance_*.parquet under ticks_root/<date>/, extract (ts_s, price_usd)."""
    frames: list[pl.DataFrame] = []
    for date_dir in sorted(ticks_root.glob("*")):
        if not date_dir.is_dir():
            continue
        for path in sorted(date_dir.glob("binance_*.parquet")):
            try:
                df = pl.read_parquet(path)
            except Exception as e:
                print(f"    skip {path.name}: {e}", flush=True)
                continue
            # Decode payload to extract trade price; the 'p' field is a string usd price.
            df = df.filter(pl.col("kind") == "trade")
            df = df.with_columns(
                ts_s=(pl.col("ts_utc_ns") / 1_000_000_000).cast(pl.Int64),
                price=pl.col("payload_json").str.json_path_match("$.p").cast(pl.Float64),
            )
            df = df.select(["ts_s", "price"]).filter(pl.col("price").is_not_null())
            frames.append(df)
    if not frames:
        return pl.DataFrame({"ts_s": [], "price": []})
    out = pl.concat(frames).sort("ts_s")
    return out


def _build_per_second_index(ticks: pl.DataFrame) -> dict[int, float]:
    """Forward-fill price by second; return {ts_s: last_known_price}.

    Bonereaper trade lookup is point-in-time; binance has multiple ticks
    per second. Take the latest price within each second.
    """
    if ticks.is_empty():
        return {}
    grouped = ticks.group_by("ts_s").agg(pl.col("price").last().alias("price"))
    return dict(zip(grouped["ts_s"].to_list(), grouped["price"].to_list(), strict=True))


def _spot_at(per_second: dict[int, float], ts_s: int, *, max_lookback_s: int = 30) -> float | None:
    """Forward-fill: latest known price at or before ts_s, within max_lookback_s."""
    for delta in range(0, max_lookback_s + 1):
        p = per_second.get(ts_s - delta)
        if p is not None:
            return p
    return None


def _bucket_delta(delta_bps: float) -> str:
    for lo, hi, label in DELTA_BUCKETS_BPS:
        if lo <= delta_bps < hi:
            return label
    return DELTA_BUCKETS_BPS[-1][2]


def _join(
    trades: list[dict[str, Any]], per_second: dict[int, float]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Add S0, St, delta_bps, alignment to each trade where spot is available."""
    joined: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    for t in trades:
        ts_s = int(t.get("ts") or 0)
        window_ts = t.get("window_ts")
        if not ts_s or window_ts is None:
            skipped["missing_ts_or_window"] += 1
            continue
        s0 = _spot_at(per_second, int(window_ts))
        st = _spot_at(per_second, ts_s)
        if s0 is None or st is None or s0 <= 0:
            skipped["no_spot_data"] += 1
            continue
        delta_bps = 10_000.0 * (st - s0) / s0
        outcome = t.get("outcome") or ""
        side_up = outcome.lower() == "up"
        side_down = outcome.lower() == "down"
        # Aligned: bet up when price went up; bet down when price went down.
        if (side_up and delta_bps > 0) or (side_down and delta_bps < 0):
            alignment = "aligned"
        elif (side_up and delta_bps < 0) or (side_down and delta_bps > 0):
            alignment = "contrarian"
        else:
            alignment = "flat"  # delta == 0 or unknown side
        joined.append(
            {
                **t,
                "spot_open_usd": s0,
                "spot_at_entry_usd": st,
                "delta_bps": round(delta_bps, 2),
                "alignment": alignment,
                "delta_bucket": _bucket_delta(delta_bps),
                "is_up": side_up,
                "is_down": side_down,
            }
        )
    return joined, dict(skipped)


def _summarize(joined: list[dict[str, Any]]) -> dict[str, Any]:
    by_alignment: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )
    by_delta: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )
    by_side_delta: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )
    by_alignment_pricetier: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )

    for t in joined:
        align = t.get("alignment") or "?"
        delta_b = t.get("delta_bucket") or "?"
        notional = float(t.get("notional") or 0.0)
        pnl = float(t.get("gross_pnl") or 0.0)
        won = int(bool(t.get("won")))
        side = "UP" if t.get("is_up") else ("DOWN" if t.get("is_down") else "?")

        price = float(t.get("price") or 0.0)
        if price >= 0.85:
            ptier = "85-100%"
        elif price >= 0.70:
            ptier = "70-85%"
        elif price >= 0.50:
            ptier = "50-70%"
        elif price >= 0.30:
            ptier = "30-50%"
        elif price >= 0.15:
            ptier = "15-30%"
        else:
            ptier = "<15%"

        for d in (
            by_alignment[align],
            by_delta[delta_b],
            by_side_delta[(side, delta_b)],
            by_alignment_pricetier[(align, ptier)],
        ):
            d["trades"] += 1
            d["wins"] += won
            d["notional"] += notional
            d["pnl"] += pnl
    return {
        "by_alignment": dict(by_alignment),
        "by_delta": dict(by_delta),
        "by_side_delta": dict(by_side_delta),
        "by_alignment_pricetier": dict(by_alignment_pricetier),
    }


def _fmt_row(d: dict[str, Any]) -> str:
    n = d["trades"]
    if n == 0:
        return "0 | — | — | — | —"
    wr = d["wins"] / n
    pt = d["pnl"] / n
    return f"{n:,} | {wr:.1%} | ${d['notional']:,.0f} | ${d['pnl']:+,.0f} | ${pt:+,.2f}"


def _render_md(
    joined: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    n_input_trades: int,
    skipped: dict[str, int],
    elapsed_s: float,
) -> str:
    lines: list[str] = []
    today = _today_utc_str()
    lines.append("# Bonereaper spot-vs-book correlation")
    lines.append("")
    lines.append(
        f"Run date: {today}. Input bonereaper trades: {n_input_trades:,}. Joined "
        f"with captured BTC spot: {len(joined):,}. Skipped: {sum(skipped.values()):,} "
        f"({skipped}). Fetch+join time: {elapsed_s:.1f}s."
    )
    lines.append("")
    lines.append(
        "**Question under test:** does Bonereaper use BTC spot information to pick a "
        "side? Test: for each trade, compare entry-time spot to window-open spot, "
        "compute Δ_bps = 10000x(St - S0)/S0, classify alignment (UP+Δ>0 OR DOWN+Δ<0 "
        "= aligned; opposite = contrarian; Δ≈0 = flat), and look at win-rate per "
        "alignment bucket and per Δ_bps bucket."
    )
    lines.append("")

    if not joined:
        lines.append(
            "**No trades joined.** Captured spot data does not overlap the "
            "Bonereaper trade timestamps. Need more capture coverage."
        )
        return "\n".join(lines)

    # Headline
    total = len(joined)
    wins = sum(1 for t in joined if t.get("won"))
    pnl = sum(float(t.get("gross_pnl") or 0.0) for t in joined)
    notional = sum(float(t.get("notional") or 0.0) for t in joined)
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- **{total:,} trades** with spot data joined")
    lines.append(f"- Win rate: **{wins / total:.1%}** ({wins:,}/{total:,})")
    lines.append(f"- Gross notional: ${notional:,.2f}")
    lines.append(f"- Gross PnL: ${pnl:+,.2f}")
    lines.append("")

    # By alignment (THE main test)
    lines.append("## By alignment (the main test)")
    lines.append("")
    lines.append("| alignment | trades | win-rate | notional | gross PnL | per-trade |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for align in ("aligned", "contrarian", "flat"):
        d = summary["by_alignment"].get(align)
        if d:
            lines.append(f"| {align} | {_fmt_row(d)} |")
    lines.append("")
    aligned = summary["by_alignment"].get("aligned", {"trades": 0, "wins": 0})
    contrarian = summary["by_alignment"].get("contrarian", {"trades": 0, "wins": 0})
    if aligned.get("trades", 0) > 50 and contrarian.get("trades", 0) > 50:
        wr_a = aligned["wins"] / aligned["trades"]
        wr_c = contrarian["wins"] / contrarian["trades"]
        gap = wr_a - wr_c
        lines.append(
            f"**Aligned vs contrarian win-rate gap:** {gap:+.1%} "
            f"(aligned {wr_a:.1%} vs contrarian {wr_c:.1%})."
        )
        if gap >= 0.05:
            lines.append("→ **Suggests Bonereaper IS spot-aware** when picking sides.")
        elif gap <= -0.05:
            lines.append("→ **Suggests Bonereaper is anti-spot** (contrarian/mean-reversion).")
        else:
            lines.append("→ **No clear spot-awareness signal in this sample.**")
        lines.append("")

    # By Δ bucket
    lines.append("## By Δ_bps bucket (entry-time spot move since window open)")
    lines.append("")
    lines.append("| Δ_bps bucket | trades | win-rate | notional | gross PnL | per-trade |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for _, _, label in DELTA_BUCKETS_BPS:
        d = summary["by_delta"].get(label)
        if d and d["trades"] > 0:
            lines.append(f"| {label} | {_fmt_row(d)} |")
    lines.append("")

    # By side x Δ
    lines.append("## By side x Δ_bps (does UP bet win more when spot moves up?)")
    lines.append("")
    lines.append("| side | Δ bucket | trades | win-rate | notional | gross PnL | per-trade |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for side in ("UP", "DOWN"):
        for _, _, label in DELTA_BUCKETS_BPS:
            d = summary["by_side_delta"].get((side, label))
            if d and d["trades"] > 5:
                lines.append(f"| {side} | {label} | {_fmt_row(d)} |")
    lines.append("")

    # By alignment x price tier
    lines.append("## By alignment x price tier (where the alignment edge lands)")
    lines.append("")
    lines.append(
        "| alignment | price tier | trades | win-rate | notional | gross PnL | per-trade |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for align in ("aligned", "contrarian", "flat"):
        for ptier in ("<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"):
            d = summary["by_alignment_pricetier"].get((align, ptier))
            if d and d["trades"] > 5:
                lines.append(f"| {align} | {ptier} | {_fmt_row(d)} |")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")
    if aligned.get("trades", 0) > 50 and contrarian.get("trades", 0) > 50:
        wr_a = aligned["wins"] / aligned["trades"]
        wr_c = contrarian["wins"] / contrarian["trades"]
        gap = wr_a - wr_c
        if gap >= 0.10:
            lines.append(
                "- **Hypothesis SUPPORTED**: aligned trades win meaningfully "
                "more often than contrarian. Bonereaper appears to use spot "
                "data to pick sides. Next step: a `design/spot_aware_strategy.md` "
                "doc describing the trigger this implies (gap between book "
                "implied probability and spot-derived probability) before any "
                "code lands. Anti-vibe rule #1."
            )
        elif gap >= 0.05:
            lines.append(
                "- **Hypothesis WEAK SUPPORT**: small but real gap between "
                "aligned and contrarian. May be noise at this sample size; "
                "would need broader spot-tick coverage to be confident."
            )
        elif gap >= -0.05:
            lines.append(
                "- **Hypothesis INCONCLUSIVE**: no meaningful gap between "
                "aligned and contrarian win rates. Bonereaper's signal "
                "lives somewhere other than naive spot-vs-book."
            )
        else:
            lines.append(
                "- **Hypothesis REJECTED in opposite direction**: contrarian "
                "trades win more often. Bonereaper may be a mean-reversion "
                "trader, not a momentum follower."
            )
    else:
        lines.append(
            "- **Insufficient sample** (<50 trades in either alignment "
            "bucket). Need broader spot-tick capture."
        )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Spot lookup is forward-fill within 30s. Accuracy degrades on "
        "sparse-tick periods; a 5s gap to a 1-bp move shouldn't change "
        "bucket assignment but could on edge cases."
    )
    lines.append(
        "- Binance ticks only. Coinbase + oracle would refine but the "
        "Binance feed dominates BTC volume so this is a reasonable proxy."
    )
    lines.append(
        "- Captured spot covers a tiny window of bonereaper's full activity. "
        "Findings here are suggestive, not conclusive."
    )
    lines.append(
        "- Δ_bps is computed entry vs window-open, not entry vs immediate-prior. "
        "A trade entering at t=200s with the price unchanged from window-open "
        "but having round-tripped is bucketed as 'flat' even though the path "
        "was volatile."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trades-json",
        type=Path,
        default=STATE_DIR / "microstructure-trades.json",
        help="Output of bonereaper_microstructure.py",
    )
    parser.add_argument(
        "--ticks-root",
        type=Path,
        required=True,
        help="Path to a directory of <date>/binance_*.parquet capture files.",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Markdown output path (default runbooks/research/bonereaper-spot-vs-book-<date>.md).",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=STATE_DIR / "spot-vs-book-joined.json",
    )
    args = parser.parse_args(argv)

    started = time.time()

    print(f"==> loading trades from {args.trades_json}", flush=True)
    payload = json.loads(args.trades_json.read_text(encoding="utf-8"))
    raw_trades = payload.get("trades") or []
    print(f"    {len(raw_trades):,} trades loaded", flush=True)

    print(f"==> loading binance ticks from {args.ticks_root}", flush=True)
    ticks = _load_binance_ticks(args.ticks_root)
    print(f"    {len(ticks):,} binance trade rows", flush=True)
    if ticks.is_empty():
        print("    no binance ticks found; aborting", flush=True)
        return 1
    ts_min = int(ticks["ts_s"].min())
    ts_max = int(ticks["ts_s"].max())
    print(
        f"    spot ts range: {ts_min} → {ts_max} "
        f"({(ts_max - ts_min) / 60:.1f} minutes of coverage)",
        flush=True,
    )

    per_second = _build_per_second_index(ticks)
    print(f"    {len(per_second):,} unique seconds in spot index", flush=True)

    print("==> joining trades against spot...", flush=True)
    joined, skipped = _join(raw_trades, per_second)
    print(
        f"    {len(joined):,} joined, {sum(skipped.values()):,} skipped {dict(skipped)}", flush=True
    )

    summary = _summarize(joined)
    elapsed = time.time() - started

    md = _render_md(
        joined,
        summary,
        n_input_trades=len(raw_trades),
        skipped=skipped,
        elapsed_s=elapsed,
    )

    out_md = args.out_md or (RUNBOOK_DIR / f"bonereaper-spot-vs-book-{_today_utc_str()}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    # Slim json — only the joined rows, not the raw 26MB.
    args.out_json.write_text(
        json.dumps(
            {
                "n_input": len(raw_trades),
                "n_joined": len(joined),
                "skipped": skipped,
                "elapsed_s": elapsed,
                "spot_ts_min": ts_min,
                "spot_ts_max": ts_max,
                "trades": joined,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(md)
    print()
    print(f"==> wrote markdown report to {out_md}")
    print(f"==> wrote joined trade rows to {args.out_json}")
    print(f"==> elapsed: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

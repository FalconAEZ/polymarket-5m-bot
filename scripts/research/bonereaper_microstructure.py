"""Bonereaper microstructure analysis — entry-time vs resolution-time distribution.

Tests the 2026-05-08 operator hypothesis: Bonereaper is a late-window favorite
sniper on Polymarket BTC 5-min markets. Mechanism: in the final 30-60s of a
window, BTC spot price has often moved decisively but Polymarket's CLOB
hasn't fully repriced; a fast trader can buy the favorite at <$1 implied
probability and collect on near-certain resolution.

Method:
  1. Enumerate all `btc-updown-5m-<ts>` slugs over the last N days.
  2. Resolve via Gamma to get conditionId + outcomePrices (resolution).
  3. Pull bonereaper's trades per market via Data API combined filter.
  4. For each fill, compute `seconds_before_resolution = (window_ts + 300) - trade.ts`.
  5. Bucket by entry price tier (matching the predicts.guru breakdown) AND by
     time-before-resolution. Report counts, win-rate, gross PnL.

Verdict bucket: if >40% of fills at >=70¢ entry tier land in the last 60s of
their window, hypothesis confirmed → drives a `design/late_window_sniper.md`
follow-up. If they're roughly uniform across the window, hypothesis killed.

Output:
  runbooks/research/bonereaper-microstructure-<date>.md   (markdown report)
  state/research/bonereaper/microstructure-trades.json    (raw enriched trades)

Usage:
  uv run python -u scripts/research/bonereaper_microstructure.py [--days N]

Reuses _api.py + a few helpers from weekly_audit.py; this is observability,
not a strategy artifact, so it lives under scripts/research and runbooks/
research per the existing convention.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _api import (  # type: ignore[import-not-found]
    fetch_event_by_slug_simple,
    fetch_user_trades_on_market,
)

BONEREAPER_ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
WINDOW_S = 300

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = PROJECT_ROOT / "state" / "research" / "bonereaper"
RUNBOOK_DIR = PROJECT_ROOT / "runbooks" / "research"

# Time-before-resolution buckets in seconds. Window is 300s; finer buckets
# in the last minute because that's where the hypothesis predicts mass.
TIME_BUCKETS_S: list[tuple[int, int, str]] = [
    (0, 30, "0-30s"),
    (30, 60, "30-60s"),
    (60, 120, "60-120s"),
    (120, 180, "120-180s"),
    (180, 240, "180-240s"),
    (240, 300, "240-300s"),
    (300, 10**9, ">300s (post-resolve)"),
]
PRICE_TIERS: list[tuple[float, float, str]] = [
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
]


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _generate_btc5m_slugs(now_unix: int, days: int) -> list[str]:
    """Per-window slug enumeration (mirrors weekly_audit._generate_btc5m_slugs)."""
    end_window = (now_unix // WINDOW_S) * WINDOW_S
    lookback = days * 86400
    start_window = end_window - lookback
    return [f"btc-updown-5m-{ts}" for ts in range(start_window, end_window + 1, WINDOW_S)]


def _resolve_event_concurrent(
    slugs: list[str], *, max_workers: int = 16
) -> dict[str, dict[str, Any]]:
    """slug -> event-with-markets[] dict. Missing slugs are dropped."""
    out: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=httpx.Timeout(15.0, read=15.0)) as cli:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_slug = {ex.submit(fetch_event_by_slug_simple, s, client=cli): s for s in slugs}
            done = 0
            for fut in as_completed(fut_to_slug):
                slug = fut_to_slug[fut]
                done += 1
                if done % 200 == 0:
                    print(f"    resolved {done}/{len(slugs)} slugs", flush=True)
                try:
                    ev = fut.result()
                except Exception as exc:
                    print(f"    skip {slug}: {exc}", flush=True)
                    continue
                if ev is not None:
                    out[slug] = ev
    return out


def _resolve_trades_concurrent(
    user: str,
    market_pairs: list[tuple[str, str]],
    *,
    max_workers: int = 16,
) -> list[dict[str, Any]]:
    """Pull trades for `user` on every (slug, conditionId) pair concurrently."""
    fills: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(15.0, read=15.0)) as cli:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_to_pair = {
                ex.submit(fetch_user_trades_on_market, user, cid, client=cli): (slug, cid)
                for slug, cid in market_pairs
            }
            done = 0
            for fut in as_completed(fut_to_pair):
                slug, _cid = fut_to_pair[fut]
                done += 1
                if done % 200 == 0:
                    print(f"    pulled {done}/{len(market_pairs)} markets", flush=True)
                try:
                    rows = fut.result()
                except Exception as exc:
                    print(f"    skip {slug}: {exc}", flush=True)
                    continue
                for r in rows:
                    r = dict(r)
                    r["slug"] = slug
                    fills.append(r)
    return fills


def _parse_window_ts(slug: str) -> int | None:
    """Pull the unix-second window-start out of `btc-updown-5m-<ts>`."""
    parts = slug.rsplit("-", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _enrich_trade(trade: dict[str, Any], market: dict[str, Any]) -> dict[str, Any] | None:
    """Compute (price, size, side, won, gross_pnl, time_to_resolution) for one fill."""
    outcomes_raw = market.get("outcomes")
    outcome_prices_raw = market.get("outcomePrices")
    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
    outcome_prices = (
        json.loads(outcome_prices_raw)
        if isinstance(outcome_prices_raw, str)
        else (outcome_prices_raw or [])
    )

    if (
        not market.get("closed")
        or not outcomes
        or len(outcome_prices) != 2
        or "1" not in outcome_prices
    ):
        return None

    side = (trade.get("side") or "BUY").upper()
    price = float(trade.get("price") or 0.0)
    size = float(trade.get("size") or 0.0)
    if size <= 0:
        return None
    traded_outcome = trade.get("outcome")
    traded_idx_raw = trade.get("outcomeIndex")
    try:
        traded_idx = int(traded_idx_raw) if traded_idx_raw is not None else None
    except (TypeError, ValueError):
        traded_idx = None
    if traded_idx is None and traded_outcome in outcomes:
        traded_idx = outcomes.index(traded_outcome)
    if traded_idx is None or not (0 <= traded_idx < len(outcome_prices)):
        return None

    won_token = outcome_prices[traded_idx] == "1"
    if side == "BUY":
        gross_pnl = (1.0 - price) * size if won_token else (-price) * size
    else:  # SELL
        gross_pnl = (price - 1.0) * size if won_token else price * size

    slug = trade.get("slug") or ""
    window_ts = _parse_window_ts(slug)
    trade_ts = int(trade.get("timestamp") or 0)
    seconds_before_resolution: int | None = None
    seconds_after_window_open: int | None = None
    if window_ts is not None and trade_ts > 0:
        resolution_ts = window_ts + WINDOW_S
        seconds_before_resolution = resolution_ts - trade_ts
        seconds_after_window_open = trade_ts - window_ts

    return {
        "ts": trade_ts,
        "window_ts": window_ts,
        "seconds_before_resolution": seconds_before_resolution,
        "seconds_after_window_open": seconds_after_window_open,
        "tx_hash": trade.get("transactionHash"),
        "slug": slug,
        "side": side,
        "price": price,
        "size": size,
        "notional": price * size,
        "outcome": traded_outcome,
        "won": gross_pnl > 0,
        "gross_pnl": gross_pnl,
    }


def _bucket_time(seconds_before_resolution: int | None) -> str:
    if seconds_before_resolution is None:
        return "unknown"
    if seconds_before_resolution < 0:
        return ">300s (post-resolve)"
    for lo, hi, label in TIME_BUCKETS_S:
        if lo <= seconds_before_resolution < hi:
            return label
    return ">300s (post-resolve)"


def _bucket_price(price: float) -> str:
    for lo, hi, label in PRICE_TIERS:
        if lo <= price < hi:
            return label
    return "85-100%"


def _summarize(enriched: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce summary tables: by time-bucket, by price-tier, joint."""
    by_time: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )
    by_price: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )
    joint: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "notional": 0.0, "pnl": 0.0}
    )

    for t in enriched:
        tb = _bucket_time(t.get("seconds_before_resolution"))
        pb = _bucket_price(float(t.get("price") or 0.0))
        for d in (by_time[tb], by_price[pb], joint[(pb, tb)]):
            d["trades"] += 1
            d["wins"] += int(bool(t.get("won")))
            d["notional"] += float(t.get("notional") or 0.0)
            d["pnl"] += float(t.get("gross_pnl") or 0.0)
    return {"by_time": dict(by_time), "by_price": dict(by_price), "joint": dict(joint)}


def _render_md(
    enriched: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    days: int,
    n_markets_with_trades: int,
    n_markets_total: int,
    elapsed_s: float,
) -> str:
    lines: list[str] = []
    today = _today_utc_str()
    lines.append("# Bonereaper microstructure — entry-time vs resolution-time")
    lines.append("")
    lines.append(
        f"Run date: {today}. Wallet: `{BONEREAPER_ADDR}`. Lookback: {days} days. "
        f"Markets enumerated: {n_markets_total}; markets with bonereaper trades: "
        f"{n_markets_with_trades}. Trades analysed: {len(enriched)}. "
        f"Fetch time: {elapsed_s:.1f}s."
    )
    lines.append("")
    lines.append(
        "**Hypothesis under test (operator's 2026-05-08 framing):** Bonereaper "
        "is a *late-window favorite sniper* — most fills at >=70¢ entry land "
        "in the final 30-60s of a 5-min window, exploiting spot-vs-book lag "
        "on near-certain resolutions."
    )
    lines.append("")

    # ---- Headline numbers ----
    if not enriched:
        lines.append(
            "**No trades found in the lookback window.** Either the wallet went quiet, "
            "the API filter missed something, or the lookback was too short. Bail."
        )
        return "\n".join(lines)

    total_trades = len(enriched)
    total_wins = sum(1 for t in enriched if t.get("won"))
    total_notional = sum(float(t.get("notional") or 0.0) for t in enriched)
    total_pnl = sum(float(t.get("gross_pnl") or 0.0) for t in enriched)
    overall_winrate = total_wins / total_trades

    lines.append("## Headline")
    lines.append("")
    lines.append(f"- **{total_trades:,} trades** on BTC 5-min markets in the last {days} days")
    lines.append(f"- **Win rate:** {overall_winrate:.1%} ({total_wins:,}/{total_trades:,})")
    lines.append(f"- **Gross notional:** ${total_notional:,.2f}")
    lines.append(f"- **Gross PnL:** ${total_pnl:+,.2f} (excludes fees / settlement gas)")
    lines.append("")

    # ---- Time-before-resolution distribution ----
    lines.append("## Distribution by time-before-resolution")
    lines.append("")
    lines.append("Bucket = `(window_ts + 300) - trade.ts`. Lower = closer to resolution.")
    lines.append("")
    lines.append("| time bucket | trades | win-rate | notional | gross PnL | per-trade PnL |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for _, _, label in TIME_BUCKETS_S:
        d = summary["by_time"].get(label)
        if not d or d["trades"] == 0:
            continue
        wr = d["wins"] / d["trades"]
        per_trade = d["pnl"] / d["trades"]
        lines.append(
            f"| {label} | {d['trades']:,} | {wr:.1%} | ${d['notional']:,.0f} | "
            f"${d['pnl']:+,.0f} | ${per_trade:+,.2f} |"
        )
    lines.append("")

    # ---- Price-tier distribution ----
    lines.append("## Distribution by entry price tier")
    lines.append("")
    lines.append("Mirrors the predicts.guru breakdown the operator shared.")
    lines.append("")
    lines.append("| price tier | trades | win-rate | notional | gross PnL | per-trade PnL |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for _, _, label in PRICE_TIERS:
        d = summary["by_price"].get(label)
        if not d or d["trades"] == 0:
            continue
        wr = d["wins"] / d["trades"]
        per_trade = d["pnl"] / d["trades"]
        lines.append(
            f"| {label} | {d['trades']:,} | {wr:.1%} | ${d['notional']:,.0f} | "
            f"${d['pnl']:+,.0f} | ${per_trade:+,.2f} |"
        )
    lines.append("")

    # ---- Joint table (the hypothesis test) ----
    lines.append("## Joint table — price tier x time-before-resolution")
    lines.append("")
    lines.append(
        "**This is the hypothesis test.** If the cell at `>=70%` x `0-30s` "
        "(or `30-60s`) holds the bulk of trades AND has the highest per-trade "
        "PnL, the late-window favorite-sniping thesis is confirmed."
    )
    lines.append("")
    time_labels = [lbl for _, _, lbl in TIME_BUCKETS_S]
    header = "| price tier | metric | " + " | ".join(time_labels) + " |"
    sep = "|---|---|" + "|".join(["---:"] * len(time_labels)) + "|"
    lines.append(header)
    lines.append(sep)
    for _, _, plabel in PRICE_TIERS:
        for metric in ("trades", "win-rate", "per-trade PnL"):
            row = [f"| {plabel}", metric]
            for tlabel in time_labels:
                d = summary["joint"].get((plabel, tlabel))
                if not d or d["trades"] == 0:
                    row.append("—")
                    continue
                if metric == "trades":
                    row.append(f"{d['trades']:,}")
                elif metric == "win-rate":
                    row.append(f"{d['wins'] / d['trades']:.1%}")
                else:
                    row.append(f"${d['pnl'] / d['trades']:+,.2f}")
            lines.append(" | ".join(row) + " |")
    lines.append("")

    # ---- Verdict ----
    lines.append("## Verdict")
    lines.append("")
    fav_late_trades = 0
    fav_total_trades = 0
    for plabel in ("70-85%", "85-100%"):
        for tlabel in ("0-30s", "30-60s"):
            d = summary["joint"].get((plabel, tlabel))
            if d:
                fav_late_trades += d["trades"]
        for _, _, tlabel in TIME_BUCKETS_S:
            d = summary["joint"].get((plabel, tlabel))
            if d:
                fav_total_trades += d["trades"]
    fav_late_share = (fav_late_trades / fav_total_trades) if fav_total_trades else 0.0
    lines.append(
        f"- Of all trades at entry price >=70%, **{fav_late_share:.1%}** ({fav_late_trades:,}/"
        f"{fav_total_trades:,}) land in the final 60s of their window."
    )
    if fav_total_trades < 50:
        lines.append("- **Sample too small for a confident verdict** (<50 favorite-tier trades).")
    elif fav_late_share >= 0.40:
        lines.append(
            "- **Hypothesis SUPPORTED**: late-window favorite sniping looks like a real "
            "pattern. Next step: write `design/late_window_sniper.md` describing the "
            "spot-vs-book mispricing trigger this implies, then gate against it before "
            "any code lands. Anti-vibe rule #1."
        )
    elif fav_late_share <= 0.20:
        lines.append(
            "- **Hypothesis REJECTED**: bonereaper's favorite-tier fills are not "
            "concentrated in the final minute. Strategy lives somewhere else. "
            "Re-examine assumptions before pursuing further."
        )
    else:
        lines.append(
            "- **Hypothesis WEAK**: some concentration in the final 60s but not "
            "decisive. Pull more data (longer lookback) or look at alternative "
            "patterns (15m or 1h markets, off-hours regime, etc.)."
        )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Lookback is **last N days only**; the dataset is a slice of bonereaper's "
        "much larger history. predicts.guru shows ~$82M lifetime volume; this audit "
        "samples a tiny fraction. Don't generalise too hard."
    )
    lines.append(
        "- 5-min markets only (slug `btc-updown-5m-`). Bonereaper also trades 15m and "
        "1h BTC markets; their behaviour there could be different."
    )
    lines.append(
        "- Trade timestamps come from Polymarket Data API (off-chain) and reflect "
        "matcher-side timestamps, not on-chain confirmation. Drift of a few seconds "
        "is possible but won't change a 30s vs 240s answer."
    )
    lines.append(
        "- Fees and settlement gas are NOT subtracted from gross PnL. Bonereaper's "
        "real PnL is lower than the gross numbers above."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7, help="Lookback in days (default 7).")
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Markdown output path (default runbooks/research/bonereaper-microstructure-<date>.md).",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=STATE_DIR / "microstructure-trades.json",
        help="Raw enriched-trades JSON output.",
    )
    args = parser.parse_args(argv)

    started = time.time()
    now_unix = int(time.time())

    print(f"== Bonereaper microstructure ({args.days}d lookback) ==", flush=True)
    slugs = _generate_btc5m_slugs(now_unix, args.days)
    print(f"  candidate slugs: {len(slugs):,}", flush=True)

    print("  resolving via Gamma...", flush=True)
    events = _resolve_event_concurrent(slugs)
    print(f"  resolved markets: {len(events):,}", flush=True)

    market_pairs: list[tuple[str, str]] = []
    market_lookup: dict[str, dict[str, Any]] = {}
    for slug, ev in events.items():
        markets_list = ev.get("markets") or []
        if not markets_list:
            continue
        m = markets_list[0]
        cid = m.get("conditionId")
        if not cid:
            continue
        market_pairs.append((slug, cid))
        market_lookup[slug] = m

    print(f"  pulling bonereaper trades on {len(market_pairs):,} markets...", flush=True)
    raw_trades = _resolve_trades_concurrent(BONEREAPER_ADDR, market_pairs)
    print(f"  raw trade rows: {len(raw_trades):,}", flush=True)

    enriched: list[dict[str, Any]] = []
    skipped = 0
    for tr in raw_trades:
        m = market_lookup.get(tr.get("slug") or "")
        if m is None:
            skipped += 1
            continue
        out = _enrich_trade(tr, m)
        if out is None:
            skipped += 1
            continue
        enriched.append(out)
    print(
        f"  enriched: {len(enriched):,} (skipped {skipped} for missing/open market data)",
        flush=True,
    )

    summary = _summarize(enriched)
    elapsed = time.time() - started

    n_markets_with_trades = len({t.get("slug") for t in enriched if t.get("slug")})
    md = _render_md(
        enriched,
        summary,
        days=args.days,
        n_markets_with_trades=n_markets_with_trades,
        n_markets_total=len(events),
        elapsed_s=elapsed,
    )

    out_md = args.out_md or (RUNBOOK_DIR / f"bonereaper-microstructure-{_today_utc_str()}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(
            {
                "wallet": BONEREAPER_ADDR,
                "days": args.days,
                "n_markets_total": len(events),
                "n_markets_with_trades": n_markets_with_trades,
                "elapsed_s": elapsed,
                "trades": enriched,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Print a smaller summary to stdout so the operator sees results immediately.
    print()
    print(md)
    print()
    print(f"==> wrote markdown report to {out_md}")
    print(f"==> wrote raw enriched trades to {args.out_json}")
    print(f"==> elapsed: {elapsed:.1f}s")

    # Return 0 always; this is observability, not a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main())

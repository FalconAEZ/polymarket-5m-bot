"""Scout for small-equity wallets crushing BTC 5-min markets.

Driven by the operator's 2026-05-08 hypothesis: a wallet with $5k equity
making $200/day is a MUCH better template for our $1k bankroll than
Bonereaper at $13M equity. If we find one, we have:
  - A replicable strategy at our actual capital scale
  - A second data point to validate the spot-Δ signal hypothesis
  - Evidence that the edge survives at small capital (no fee-tier rebates)

Method:
  1. Sample N recent BTC 5-min markets (last 7 days, ~200 markets default).
  2. Pull EVERY trade on each (no user filter) via the Data API — gives us
     every wallet that touched these markets.
  3. Aggregate by proxyWallet: trade count, notional volume, distinct
     markets touched.
  4. For top K candidates by notional, query /value?user=<addr> to get
     current equity.
  5. Filter by equity range (default $2k-$50k — small-but-not-tiny).
  6. For each survivor, deep-evaluate (win-rate, PnL, time-bucket) using
     the same _evaluate_trade logic from weekly_audit.py.
  7. Rank by per-dollar PnL efficiency. Emit a markdown comparison table.

This is RECONNAISSANCE. Don't act on the output — feed any candidate
worth investigating into bonereaper_microstructure.py +
bonereaper_spot_vs_book.py for full analysis. Anti-vibe rule #1: design
doc before code, ALWAYS, including for any "let's clone wallet X" idea.

Usage:
  uv run python -u scripts/research/leaderboard_scout.py \
    [--days 7] \
    [--sample-markets 200] \
    [--top-k 30] \
    [--equity-min 2000] \
    [--equity-max 50000]
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
from random import Random
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _api import (  # type: ignore[import-not-found]
    fetch_event_by_slug_simple,
)

DATA_API = "https://data-api.polymarket.com"
WINDOW_S = 300

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUNBOOK_DIR = PROJECT_ROOT / "runbooks" / "research"
STATE_DIR = PROJECT_ROOT / "state" / "research" / "leaderboard"

BONEREAPER_ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"

# Wallets to exclude from candidate set (known venue/aggregator/op-relay addresses).
# Add more as we identify them in output.
EXCLUDE_WALLETS: set[str] = {
    # Polymarket relay / matchmaker addresses appear here when found
}


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _generate_btc5m_slugs(now_unix: int, days: int) -> list[str]:
    end_window = (now_unix // WINDOW_S) * WINDOW_S
    start_window = end_window - days * 86400
    return [f"btc-updown-5m-{ts}" for ts in range(start_window, end_window + 1, WINDOW_S)]


def _resolve_event_concurrent(
    slugs: list[str], *, max_workers: int = 16
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=httpx.Timeout(15.0, read=15.0)) as cli:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(fetch_event_by_slug_simple, s, client=cli): s for s in slugs}
            done = 0
            for fut in as_completed(futures):
                slug = futures[fut]
                done += 1
                if done % 200 == 0:
                    print(f"    resolved {done}/{len(slugs)}", flush=True)
                try:
                    ev = fut.result()
                except Exception as exc:
                    print(f"    skip {slug}: {exc}", flush=True)
                    continue
                if ev is not None:
                    out[slug] = ev
    return out


def _pull_all_market_trades(
    market_pairs: list[tuple[str, str]], *, max_workers: int = 16
) -> list[dict[str, Any]]:
    """Pull every trade on each (slug, conditionId) market — no user filter."""
    fills: list[dict[str, Any]] = []

    def _fetch(slug_cid: tuple[str, str]) -> tuple[str, list[dict[str, Any]]]:
        slug, cid = slug_cid
        with httpx.Client(timeout=httpx.Timeout(15.0, read=15.0)) as cli:
            try:
                r = cli.get(f"{DATA_API}/trades", params={"market": cid, "limit": "500"})
                r.raise_for_status()
                rows = r.json()
                return slug, list(rows) if isinstance(rows, list) else []
            except Exception:
                return slug, []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch, p) for p in market_pairs]
        done = 0
        for fut in as_completed(futures):
            try:
                slug, rows = fut.result()
            except Exception as exc:
                print(f"    fetch error: {exc}", flush=True)
                continue
            for r in rows:
                r = dict(r)
                r["slug"] = slug
                fills.append(r)
            done += 1
            if done % 50 == 0:
                print(
                    f"    pulled trades from {done}/{len(market_pairs)} markets, {len(fills):,} rows",
                    flush=True,
                )
    return fills


def _aggregate_by_wallet(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_wallet: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trades": 0,
            "notional": 0.0,
            "markets": set(),
            "pseudonym": "",
            "name": "",
        }
    )
    for tr in trades:
        wallet = tr.get("proxyWallet")
        if not isinstance(wallet, str) or wallet in EXCLUDE_WALLETS:
            continue
        slug = tr.get("slug") or ""
        try:
            price = float(tr.get("price") or 0.0)
            size = float(tr.get("size") or 0.0)
        except (TypeError, ValueError):
            price = size = 0.0
        d = by_wallet[wallet]
        d["trades"] = int(d["trades"]) + 1
        d["notional"] = float(d["notional"]) + price * size
        markets = d["markets"]
        if isinstance(markets, set):
            markets.add(slug)
        # Pseudonym/name carries through; first non-empty wins.
        if not d["pseudonym"] and tr.get("pseudonym"):
            d["pseudonym"] = str(tr["pseudonym"])
        if not d["name"] and tr.get("name"):
            d["name"] = str(tr["name"])
    out: dict[str, dict[str, Any]] = {}
    for w, d in by_wallet.items():
        markets_set = d["markets"]
        d["unique_markets"] = len(markets_set) if isinstance(markets_set, set) else 0
        del d["markets"]
        out[w] = d
    return out


def _fetch_wallet_value(wallet: str, *, client: httpx.Client) -> float:
    try:
        r = client.get(f"{DATA_API}/value", params={"user": wallet})
        r.raise_for_status()
        body = r.json()
        if isinstance(body, list) and body:
            return float(body[0].get("value") or 0.0)
    except Exception:
        return 0.0
    return 0.0


def _enrich_with_value(
    wallets: dict[str, dict[str, Any]], *, max_workers: int = 16
) -> dict[str, dict[str, Any]]:
    addrs = list(wallets.keys())
    print(f"==> querying /value for {len(addrs)} candidate wallets", flush=True)
    out = {w: dict(d) for w, d in wallets.items()}
    with httpx.Client(timeout=httpx.Timeout(8.0, read=8.0)) as cli:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_fetch_wallet_value, w, client=cli): w for w in addrs}
            done = 0
            for fut in as_completed(futures):
                wallet = futures[fut]
                done += 1
                if done % 100 == 0:
                    print(f"    queried {done}/{len(addrs)}", flush=True)
                try:
                    out[wallet]["value_usd"] = fut.result()
                except Exception:
                    out[wallet]["value_usd"] = 0.0
    return out


def _evaluate_wallet_trades(
    trades: list[dict[str, Any]], event_lookup: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """For one wallet's trades on these markets, compute headline stats.

    Mirrors weekly_audit._evaluate_trade for the win/PnL math; adds
    time-bucket distribution for the spot-aware lens.
    """
    wins = 0
    losses = 0
    notional = 0.0
    pnl = 0.0
    n_skipped = 0
    early_window_trades = 0  # 240-300s before resolution = first minute of window
    last_minute_trades = 0  # 0-60s before resolution
    for tr in trades:
        slug = tr.get("slug") or ""
        ev = event_lookup.get(slug)
        if ev is None or not ev.get("markets"):
            n_skipped += 1
            continue
        market = ev["markets"][0]
        outcomes_raw = market.get("outcomes")
        outcome_prices_raw = market.get("outcomePrices")
        outcomes = (
            json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
        )
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
            n_skipped += 1
            continue
        side = (tr.get("side") or "BUY").upper()
        try:
            price = float(tr.get("price") or 0.0)
            size = float(tr.get("size") or 0.0)
        except (TypeError, ValueError):
            n_skipped += 1
            continue
        if size <= 0:
            n_skipped += 1
            continue
        traded_outcome = tr.get("outcome")
        traded_idx_raw = tr.get("outcomeIndex")
        try:
            traded_idx = int(traded_idx_raw) if traded_idx_raw is not None else None
        except (TypeError, ValueError):
            traded_idx = None
        if traded_idx is None and traded_outcome in outcomes:
            traded_idx = outcomes.index(traded_outcome)
        if traded_idx is None or not (0 <= traded_idx < len(outcome_prices)):
            n_skipped += 1
            continue
        won = outcome_prices[traded_idx] == "1"
        if side == "BUY":
            gross_pnl = (1.0 - price) * size if won else (-price) * size
        else:
            gross_pnl = (price - 1.0) * size if won else price * size
        notional += price * size
        pnl += gross_pnl
        if gross_pnl > 0:
            wins += 1
        else:
            losses += 1
        # Time bucket
        try:
            window_ts = int(slug.rsplit("-", 1)[1])
            trade_ts = int(tr.get("timestamp") or 0)
            seconds_before_resolution = (window_ts + WINDOW_S) - trade_ts
            if 240 <= seconds_before_resolution < 300:
                early_window_trades += 1
            elif 0 <= seconds_before_resolution < 60:
                last_minute_trades += 1
        except (ValueError, IndexError):
            pass
    n_evaluated = wins + losses
    return {
        "evaluated_trades": n_evaluated,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / n_evaluated) if n_evaluated else 0.0,
        "notional": notional,
        "gross_pnl": pnl,
        "per_trade_pnl": (pnl / n_evaluated) if n_evaluated else 0.0,
        "skipped_for_open_or_invalid": n_skipped,
        "early_window_share": ((early_window_trades / n_evaluated) if n_evaluated else 0.0),
        "last_minute_share": ((last_minute_trades / n_evaluated) if n_evaluated else 0.0),
    }


def _render_md(
    survivors: list[dict[str, Any]],
    *,
    days: int,
    n_markets_total: int,
    n_markets_sampled: int,
    n_total_wallets: int,
    n_after_equity_filter: int,
    elapsed_s: float,
    top_k: int,
    equity_min: float,
    equity_max: float,
) -> str:
    today = _today_utc_str()
    lines: list[str] = []
    lines.append("# Polymarket BTC 5-min leaderboard scout")
    lines.append("")
    lines.append(
        f"Run date: {today}. Lookback: {days} days. Markets enumerated: "
        f"{n_markets_total} (sampled: {n_markets_sampled}). Distinct wallets seen: "
        f"{n_total_wallets:,}. Top {top_k} by notional re-queried for equity. "
        f"Filtered to ${equity_min:,.0f}-${equity_max:,.0f}: {n_after_equity_filter}. "
        f"Elapsed: {elapsed_s:.0f}s."
    )
    lines.append("")
    lines.append(
        "**Goal:** find small-equity wallets ($2k-$50k by default) that are "
        "profitably trading BTC 5-min markets at scale — i.e., a more "
        "scale-relevant template for our $1k bankroll than Bonereaper's $13M."
    )
    lines.append("")
    lines.append("## Survivors (ranked by gross PnL on the sample)")
    lines.append("")
    if not survivors:
        lines.append(
            "**No wallets cleared the filter.** Either the equity range was "
            "too narrow, the sample missed the active small operators, or there "
            "genuinely aren't many. Widen `--equity-max` or `--top-k` and re-run."
        )
        return "\n".join(lines)
    lines.append(
        "Reading the columns: `pseudo` is what predicts.guru/Polymarket "
        "shows for the wallet; `equity` is current portfolio value via "
        "/value endpoint; `markets` is unique BTC 5m markets touched in "
        "the sample; `early%` is share of fills in the first minute of "
        "the window (Bonereaper's baseline = 28%); `last60s%` is share "
        "in the final 60s. **per-$ PnL** = gross_pnl ÷ notional, "
        "the closest single number for our 'who has the cleanest edge "
        "per dollar' question."
    )
    lines.append("")
    lines.append(
        "| rank | wallet | pseudo | equity | trades | markets | win-rate | "
        "notional | gross PnL | per-trade | per-$ PnL | early% | last60s% |"
    )
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, row in enumerate(survivors[:top_k], start=1):
        addr = row["wallet"]
        pseudo = row.get("pseudonym") or row.get("name") or "—"
        equity = row.get("value_usd", 0.0)
        trades = row.get("evaluated_trades", 0)
        markets = row.get("unique_markets", 0)
        wr = row.get("win_rate", 0.0)
        notional = row.get("notional", 0.0)
        pnl = row.get("gross_pnl", 0.0)
        per_trade = row.get("per_trade_pnl", 0.0)
        per_dollar = (pnl / notional) if notional else 0.0
        early_pct = row.get("early_window_share", 0.0)
        last_pct = row.get("last_minute_share", 0.0)
        marker = " 🐺" if addr.lower() == BONEREAPER_ADDR.lower() else ""
        addr_short = f"`{addr[:6]}…{addr[-4:]}`{marker}"
        lines.append(
            f"| {i} | {addr_short} | {pseudo[:16]} | ${equity:,.0f} | "
            f"{trades:,} | {markets:,} | {wr:.1%} | ${notional:,.0f} | "
            f"${pnl:+,.0f} | ${per_trade:+,.2f} | {per_dollar:+.2%} | "
            f"{early_pct:.1%} | {last_pct:.1%} |"
        )
    lines.append("")
    lines.append("## Reading the results")
    lines.append("")
    lines.append(
        "- Bonereaper (🐺 marker if present in the table) is our reference. "
        "Their per-$ PnL on the same sample is the benchmark to beat. Anyone "
        "above is plausibly a better template for OUR scale."
    )
    lines.append(
        "- The `early%` column tests the late-window-sniping hypothesis again. "
        "If a wallet has very high `last60s%`, that's a different strategy "
        "from Bonereaper and worth deep-analyzing."
    )
    lines.append(
        "- `equity` is current snapshot value. A wallet with $5k equity, 1,000 "
        "trades, and +$3k gross PnL on the sample is the dream template."
    )
    lines.append(
        "- Per-$ PnL is gross. Real after-fees PnL is lower. Anything above "
        "**+1.5%** is interesting; below **+0.5%** probably isn't."
    )
    lines.append("")
    lines.append("## Next steps for a candidate")
    lines.append("")
    lines.append(
        "If a wallet looks promising, run the full analysis: pass its address "
        "to a `--user` flag (need to extend `bonereaper_microstructure.py` "
        "first — currently hardcoded to BONEREAPER_ADDR). For now, manually "
        "edit the constant and re-run. Then run `bonereaper_spot_vs_book.py` "
        "against the resulting trade dump + the same kline parquet to see if "
        "the spot-Δ alignment pattern reproduces."
    )
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Sample-only volume — we don't have the full 30-day picture for "
        "non-Bonereaper wallets yet. A wallet that's quietly profitable might "
        "show flat numbers if their fills aren't in our sample of markets."
    )
    lines.append(
        "- `equity` is current; a wallet that just cashed out shows $0 even if "
        "they made $50k yesterday."
    )
    lines.append(
        "- Some `proxyWallet` addresses are routing/relay infrastructure, not "
        "individual operators. Watch for round-trip patterns and add to "
        "`EXCLUDE_WALLETS` in this script as we identify them."
    )
    lines.append("- Fees not subtracted from gross PnL. Real after-fees ROI is lower.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--sample-markets", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--equity-min", type=float, default=2000.0)
    parser.add_argument("--equity-max", type=float, default=50000.0)
    parser.add_argument("--min-sample-trades", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260508)
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Default runbooks/research/leaderboard-scout-<date>.md",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Default state/research/leaderboard/scout-<date>.json",
    )
    args = parser.parse_args(argv)

    started = time.time()
    now_unix = int(time.time())

    print(f"== leaderboard scout (lookback {args.days}d) ==", flush=True)
    slugs = _generate_btc5m_slugs(now_unix, args.days)
    print(f"  candidate slugs: {len(slugs):,}", flush=True)

    print("==> resolving via gamma...", flush=True)
    events = _resolve_event_concurrent(slugs)
    print(f"    resolved markets: {len(events):,}", flush=True)

    market_pairs: list[tuple[str, str]] = []
    for slug, ev in events.items():
        markets_list = ev.get("markets") or []
        if not markets_list:
            continue
        cid = markets_list[0].get("conditionId")
        if cid:
            market_pairs.append((slug, cid))

    rng = Random(args.seed)  # noqa: S311 — deterministic sampling for reproducibility, not crypto
    sample_size = min(args.sample_markets, len(market_pairs))
    sampled = rng.sample(market_pairs, sample_size) if market_pairs else []
    print(
        f"==> sampling {sample_size:,} markets uniformly at random (seed={args.seed})",
        flush=True,
    )

    print(f"==> pulling trades from {sample_size:,} sampled markets...", flush=True)
    trades = _pull_all_market_trades(sampled)
    print(f"    raw trades: {len(trades):,}", flush=True)

    by_wallet = _aggregate_by_wallet(trades)
    print(f"    distinct wallets: {len(by_wallet):,}", flush=True)

    # Filter by min sample trades — wallets with <N trades aren't meaningful here.
    candidates = {w: d for w, d in by_wallet.items() if int(d["trades"]) >= args.min_sample_trades}
    print(
        f"    after min-sample-trades filter (>= {args.min_sample_trades}): {len(candidates):,}",
        flush=True,
    )

    # Take top-K by notional volume; query equity for those.
    sorted_candidates = sorted(candidates.items(), key=lambda kv: -float(kv[1]["notional"]))[
        : max(args.top_k, 50)
    ]
    top_wallet_dict = {w: d for w, d in sorted_candidates}
    enriched = _enrich_with_value(top_wallet_dict)

    print(
        f"==> filtering by equity range ${args.equity_min:,.0f}-${args.equity_max:,.0f}",
        flush=True,
    )

    # Per-wallet trade list lookup for evaluation
    wallet_to_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tr in trades:
        w = tr.get("proxyWallet")
        if isinstance(w, str) and w in enriched:
            wallet_to_trades[w].append(tr)

    survivors: list[dict[str, Any]] = []
    for wallet, d in enriched.items():
        equity = float(d.get("value_usd", 0.0))
        # Always include Bonereaper as a reference even if outside the equity band.
        in_range = args.equity_min <= equity <= args.equity_max
        is_reference = wallet.lower() == BONEREAPER_ADDR.lower()
        if not (in_range or is_reference):
            continue
        eval_stats = _evaluate_wallet_trades(wallet_to_trades.get(wallet, []), events)
        survivors.append(
            {
                "wallet": wallet,
                "pseudonym": d.get("pseudonym", ""),
                "name": d.get("name", ""),
                "value_usd": equity,
                "unique_markets": d.get("unique_markets", 0),
                "is_reference": is_reference,
                **eval_stats,
            }
        )

    survivors.sort(key=lambda r: -float(r["gross_pnl"]))
    print(f"    survivors: {len(survivors)}", flush=True)

    elapsed = time.time() - started

    out_md = args.out_md or (RUNBOOK_DIR / f"leaderboard-scout-{_today_utc_str()}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    md = _render_md(
        survivors,
        days=args.days,
        n_markets_total=len(events),
        n_markets_sampled=sample_size,
        n_total_wallets=len(by_wallet),
        n_after_equity_filter=len(survivors),
        elapsed_s=elapsed,
        top_k=args.top_k,
        equity_min=args.equity_min,
        equity_max=args.equity_max,
    )
    out_md.write_text(md, encoding="utf-8")

    out_json = args.out_json or (STATE_DIR / f"scout-{_today_utc_str()}.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(
            {
                "generated_at_utc": _today_utc_str(),
                "days": args.days,
                "sample_markets": sample_size,
                "n_total_wallets": len(by_wallet),
                "equity_min": args.equity_min,
                "equity_max": args.equity_max,
                "elapsed_s": elapsed,
                "survivors": survivors,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(md)
    print()
    print(f"==> wrote markdown report to {out_md}")
    print(f"==> wrote raw survivors to {out_json}")
    print(f"==> elapsed: {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

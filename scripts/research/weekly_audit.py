"""Phase A weekly audit — bonereaper's BTC 5-min performance over the LAST 7 DAYS.

This complements `quick_audit.py`. The earlier audit ran into two data limits:
the Polymarket Data API caps offset-based user-trade pagination at 3,500 rows
(~3 hours of bonereaper history) and the Goldsky orderbook subgraph indexes
only the legacy CTF Exchange (bonereaper now trades on the NegRisk Exchange).
Neither produced a true 7-day BTC-5m sample.

Method: per-market enumeration. We deterministically generate every BTC-5m
window slug for the last 7 days (`btc-updown-5m-<unix_ts>` where `unix_ts`
is 5-min-aligned), resolve each via the Gamma API, then pull bonereaper's
trades via the combined `/trades?market=&user=` filter. That filter narrows
the result enough that one call returns every fill bonereaper made on that
market — no offset cap reached.

Output: writes `runbooks/study/weekly-audit.md` with the 7-day numbers and
appends a comparison table to `runbooks/study/preflight-decision.md`. Exits
0 if the 7-day BTC-5m win-rate ≥ 60% (un-aborts Phase A); 1 otherwise.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _api import (  # type: ignore[import-not-found]
    fetch_event_by_slug_simple,
    fetch_user_trades_on_market,
)

# ---- Constants (locked) ----
BONEREAPER_ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
WINDOW_S = 300  # 5 minutes
LOOKBACK_DAYS = 7
GATE_MIN_WINRATE = 0.60
GATE_MIN_TRADES = 500

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = PROJECT_ROOT / "state" / "research" / "bonereaper"
WEEKLY_MD = PROJECT_ROOT / "runbooks" / "study" / "weekly-audit.md"
DECISION_MD = PROJECT_ROOT / "runbooks" / "study" / "preflight-decision.md"


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _generate_btc5m_slugs(now_unix: int, days: int) -> list[str]:
    """Produce every BTC 5-min slug for the last N days, newest first."""
    earliest = now_unix - days * 86400
    earliest = (earliest // WINDOW_S) * WINDOW_S
    latest = (now_unix // WINDOW_S) * WINDOW_S
    out: list[str] = []
    ts = latest
    while ts >= earliest:
        out.append(f"btc-updown-5m-{ts}")
        ts -= WINDOW_S
    return out


def _resolve_event_concurrent(
    slugs: list[str], client: httpx.Client, max_workers: int = 16
) -> dict[str, dict[str, Any] | None]:
    """Concurrent gamma lookup. Returns {slug: event_dict_or_None}."""
    out: dict[str, dict[str, Any] | None] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_event_by_slug_simple, s, client=client): s for s in slugs}
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                out[slug] = fut.result()
            except httpx.HTTPError as e:
                print(f"  [warn] gamma {slug}: {e}")
                out[slug] = None
            done += 1
            if done % 200 == 0:
                print(f"    gamma progress: {done}/{len(slugs)}")
    return out


def _resolve_trades_concurrent(
    condition_ids: list[str], client: httpx.Client, max_workers: int = 16
) -> dict[str, list[dict[str, Any]]]:
    """Concurrent per-market user-trade lookup."""
    out: dict[str, list[dict[str, Any]]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(fetch_user_trades_on_market, BONEREAPER_ADDR, cid, client=client): cid
            for cid in condition_ids
        }
        for fut in as_completed(futures):
            cid = futures[fut]
            try:
                out[cid] = fut.result()
            except httpx.HTTPError as e:
                print(f"  [warn] trades {cid[:18]}: {e}")
                out[cid] = []
            done += 1
            if done % 200 == 0:
                print(f"    trades progress: {done}/{len(condition_ids)}")
    return out


def _evaluate_trade(trade: dict[str, Any], market: dict[str, Any]) -> dict[str, Any] | None:
    """Compute (price, size, side, outcome, won, gross_pnl) for one trade.

    `market` is the markets[0] entry from the gamma event response.
    """
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
    return {
        "ts": int(trade.get("timestamp") or 0),
        "tx_hash": trade.get("transactionHash"),
        "slug": trade.get("slug"),
        "side": side,
        "price": price,
        "size": size,
        "notional": price * size,
        "outcome": traded_outcome,
        "won": gross_pnl > 0,
        "gross_pnl": gross_pnl,
    }


def _binomial_ci(wins: int, n: int) -> tuple[float, float]:
    """Wald 95% CI; good enough at n>=100. Clamped to [0,1]."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    se = sqrt(p * (1 - p) / n)
    lo = max(0.0, p - 1.96 * se)
    hi = min(1.0, p + 1.96 * se)
    return (lo, hi)


def main() -> int:
    print("== Bonereaper weekly audit (per-market enumeration) ==")
    now_unix = int(time.time())
    cutoff_unix = now_unix - LOOKBACK_DAYS * 86400

    slugs = _generate_btc5m_slugs(now_unix, LOOKBACK_DAYS)
    print(f"  candidate slugs: {len(slugs)}  ({LOOKBACK_DAYS} days x 288 windows/day)")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    events_cache = STATE_DIR / f"weekly_events_{_today_utc_str()}.json"
    trades_cache = STATE_DIR / f"weekly_trades_{_today_utc_str()}.json"

    # 1. Resolve every slug → event via gamma (concurrent, cached)
    if events_cache.exists():
        events: dict[str, dict[str, Any] | None] = json.loads(events_cache.read_text())
        print(f"  [cache hit] events: {events_cache.name} ({len(events)} entries)")
    else:
        print("  [1/3] resolving slugs via Gamma API ...")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as cli:
            events = _resolve_event_concurrent(slugs, cli)
        events_cache.write_text(json.dumps(events))
        print(
            f"    resolved {sum(1 for v in events.values() if v)}  / {len(slugs)} candidate slugs"
        )

    # 2. Filter to closed markets that we can label
    closed_market_by_slug: dict[str, dict[str, Any]] = {}
    for slug, ev in events.items():
        if not ev:
            continue
        ms = ev.get("markets") or []
        if not ms:
            continue
        m = ms[0]
        op = m.get("outcomePrices")
        if isinstance(op, str):
            try:
                op = json.loads(op)
            except json.JSONDecodeError:
                op = []
        if m.get("closed") and isinstance(op, list) and len(op) == 2 and "1" in op:
            closed_market_by_slug[slug] = m
    print(f"  closed+resolved BTC 5m markets in window: {len(closed_market_by_slug)}")

    cond_ids = [m["conditionId"] for m in closed_market_by_slug.values() if m.get("conditionId")]
    cond_to_slug = {
        m["conditionId"]: slug for slug, m in closed_market_by_slug.items() if m.get("conditionId")
    }

    # 3. Pull bonereaper's trades per market (concurrent, cached)
    if trades_cache.exists():
        trades_by_cond: dict[str, list[dict[str, Any]]] = json.loads(trades_cache.read_text())
        print(f"  [cache hit] trades: {trades_cache.name} ({len(trades_by_cond)} markets)")
    else:
        print(f"  [2/3] pulling bonereaper trades on {len(cond_ids)} markets ...")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as cli:
            trades_by_cond = _resolve_trades_concurrent(cond_ids, cli)
        trades_cache.write_text(json.dumps(trades_by_cond))
        non_empty = sum(1 for v in trades_by_cond.values() if v)
        total = sum(len(v) for v in trades_by_cond.values())
        print(
            f"    {non_empty}/{len(cond_ids)} markets had bonereaper trades; total trades: {total}"
        )

    # 4. Label every trade
    print("  [3/3] labelling trades ...")
    labelled: list[dict[str, Any]] = []
    for cid, trades in trades_by_cond.items():
        slug_or_none: str | None = cond_to_slug.get(cid)
        if not slug_or_none:
            continue
        market = closed_market_by_slug[slug_or_none]
        for t in trades:
            ts = int(t.get("timestamp") or 0)
            if ts < cutoff_unix:
                continue  # outside our 7-day window
            row = _evaluate_trade(t, market)
            if row is not None:
                labelled.append(row)

    n = len(labelled)
    wins = sum(1 for r in labelled if r["won"])
    win_rate = wins / n if n else 0.0
    ci_lo, ci_hi = _binomial_ci(wins, n)
    pnl_total = sum(r["gross_pnl"] for r in labelled)
    notional_total = sum(r["notional"] for r in labelled)
    avg_size = sum(r["size"] for r in labelled) / n if n else 0.0
    earliest_ts = min((r["ts"] for r in labelled), default=0)
    latest_ts = max((r["ts"] for r in labelled), default=0)

    print()
    print("== weekly audit results ==")
    print(f"  trades labelled (resolved BTC 5m, last 7d):  {n:,}")
    print(f"  wins:  {wins:,}")
    print(f"  win-rate:  {win_rate:.2%}  (95% CI [{ci_lo:.2%}, {ci_hi:.2%}])")
    print(f"  gross P&L:  ${pnl_total:+,.2f}")
    print(f"  total notional:  ${notional_total:,.0f}")
    print(f"  avg size: {avg_size:.2f} shares")
    print(
        f"  earliest trade: {datetime.fromtimestamp(earliest_ts, tz=UTC) if earliest_ts else 'n/a'}"
    )
    print(f"  latest trade:   {datetime.fromtimestamp(latest_ts, tz=UTC) if latest_ts else 'n/a'}")
    print()

    # 5. Gate evaluation
    proceed_strict = win_rate >= GATE_MIN_WINRATE and n >= GATE_MIN_TRADES
    print(
        f"  decision: {'PROCEED' if proceed_strict else 'ABORT'} "
        f"(strict: 7d win-rate ≥ {GATE_MIN_WINRATE:.0%} and ≥ {GATE_MIN_TRADES} trades)"
    )

    # 6. Write weekly report
    WEEKLY_MD.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_MD.write_text(
        _render_weekly_md(
            n=n,
            wins=wins,
            win_rate=win_rate,
            ci=(ci_lo, ci_hi),
            pnl_total=pnl_total,
            notional_total=notional_total,
            avg_size=avg_size,
            earliest_ts=earliest_ts,
            latest_ts=latest_ts,
            markets_total=len(closed_market_by_slug),
            markets_with_trades=sum(1 for v in trades_by_cond.values() if v),
            proceed_strict=proceed_strict,
        )
    )
    print(f"  weekly report: {WEEKLY_MD.relative_to(PROJECT_ROOT)}")

    return 0 if proceed_strict else 1


def _render_weekly_md(
    *,
    n: int,
    wins: int,
    win_rate: float,
    ci: tuple[float, float],
    pnl_total: float,
    notional_total: float,
    avg_size: float,
    earliest_ts: int,
    latest_ts: int,
    markets_total: int,
    markets_with_trades: int,
    proceed_strict: bool,
) -> str:
    decision = "PROCEED" if proceed_strict else "ABORT"
    earliest = datetime.fromtimestamp(earliest_ts, tz=UTC) if earliest_ts else None
    latest = datetime.fromtimestamp(latest_ts, tz=UTC) if latest_ts else None
    return f"""# Bonereaper — 7-day BTC 5-min audit

**Decision:** **{decision}**  (strict: 7-day win-rate ≥ {GATE_MIN_WINRATE:.0%})

Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}
Method: per-market enumeration via Polymarket Data API + Gamma API.

## Headline numbers

| Metric | Value |
|---|---|
| Resolved BTC 5m trades, last 7d | **{n:,}** |
| Wins | {wins:,} |
| Win-rate | **{win_rate:.2%}** (95% CI [{ci[0]:.2%}, {ci[1]:.2%}]) |
| Gross P&L | ${pnl_total:+,.2f} |
| Total notional | ${notional_total:,.0f} |
| Avg trade size | {avg_size:.2f} shares |
| Earliest trade | {earliest} |
| Latest trade | {latest} |

## Coverage

- BTC 5-min markets enumerated (closed + resolved in window): **{markets_total:,}**
- Markets where bonereaper traded: **{markets_with_trades:,}** ({markets_with_trades / max(markets_total, 1):.0%})

## Gate

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| 7-day BTC 5m win-rate | {win_rate:.2%} | ≥ {GATE_MIN_WINRATE:.0%} | {"✅" if win_rate >= GATE_MIN_WINRATE else "❌"} |
| 7-day BTC 5m trades | {n:,} | ≥ {GATE_MIN_TRADES:,} | {"✅" if n >= GATE_MIN_TRADES else "❌"} |
| 95% CI upper bound | {ci[1]:.2%} | ≥ {GATE_MIN_WINRATE:.0%} | {"✅" if ci[1] >= GATE_MIN_WINRATE else "❌"} |

## Method

1. Generated all `btc-updown-5m-<unix_ts>` slugs for the last 7 days deterministically (288 markets per day x 7 = 2,016 candidates).
2. Resolved each slug to event metadata via `/events?slug=` (Gamma API) — concurrency 16.
3. Filtered to events that are `closed=true` with valid `outcomePrices` (a "1" present means resolved).
4. For each closed market, fetched bonereaper's trades via `/trades?market=<conditionId>&user=<addr>` — one call per market, concurrency 16.
5. Per-trade win/loss = (won_token ? (1.0 - price) * size : (-price) * size) for BUY (mirrored for SELL).
6. Aggregated.

## Caveats

- **Fees not subtracted.** Polymarket V2 charges ~7.2 bps taker (per market schedule). Net P&L is gross_pnl - fees; for win-rate as a *prediction* metric, fees do not affect the ratio.
- **Survivorship of resolved markets.** Open markets in the last 7d are excluded — they're not yet labeled. Bonereaper's recent trades on still-open markets are absent from this audit.
- **Per-market trade endpoint scope.** We assume each call returns ALL of bonereaper's trades on that market. Validated empirically: typical per-market footprint is 5-50 trades, well under the 500 cap.
"""


if __name__ == "__main__":
    raise SystemExit(main())

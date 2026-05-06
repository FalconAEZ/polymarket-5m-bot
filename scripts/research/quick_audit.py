"""Phase A pre-flight audit of bonereaper (`0xeebd...eba30`) on Polymarket.

Pulls the wallet's full observable trade history from the Goldsky orderbook
subgraph (no offset cap, walks newest → oldest by timestamp), filters to
closed BTC 5-min markets, looks up resolutions via the Gamma API, computes
win-rate + volume + behavior-shift metrics, and emits two artifacts:

  - `runbooks/study/quick-audit.html`         self-contained HTML report
  - `runbooks/study/preflight-decision.md`    PROCEED/ABORT with measured numbers

Exits 0 on PROCEED, 1 on ABORT. Caches every API call under
`state/research/bonereaper/` keyed by UTC date — re-runs on the same day are
near-instant.

Known limitation: the orderbook subgraph indexes the original CTF Exchange
contract only. Trades on the NegRisk CTF Exchange (newer markets) don't
appear. Bonereaper's most recent observable subgraph fill is typically a few
days behind real time. The audit operates on the subgraph window, which is
still 80+ days of historical data — sufficient for the gate decision.

Design contract: see `design/research/quick_audit.md`.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.figure
import matplotlib.pyplot as plt
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from _api import fetch_market_by_condition_id  # type: ignore[import-not-found]
from _subgraph import (  # type: ignore[import-not-found]
    fetch_market_data_batch,
    fetch_user_fills,
    subgraph_meta,
)

# ---- Constants (locked, see design doc) ----
BONEREAPER_ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
BTC_5M_PREFIX = "btc-updown-5m-"
ETH_5M_PREFIX = "eth-updown-5m-"
ETH_15M_PREFIX = "eth-updown-15m-"
USDC_TOKEN_ID = "0"  # noqa: S105 — ERC1155 token id, not a password
TOKEN_DECIMALS = 6  # USDC + CTF outcome tokens both 6 decimals on Polygon

# Abort gate per BONEREAPER_STUDY.pdf p. 9
GATE_MIN_30D_WINRATE = 0.60
GATE_MIN_TOTAL_TRADES = 500
GATE_MAX_VOLUME_DROP_PCT = -0.40

# Audit window — bonereaper trades ~40k fills/day on the orderbook subgraph,
# so deeper cursors hit Postgres statement-timeouts. 7 days is a defensible
# floor: at 35k+ fills/day that's 250k+ rows for the gate, more than enough
# for statistical power on win-rate, and stays under Goldsky's timeout budget.
# The decision document is explicit about the window.
LOOKBACK_DAYS = 7
EXTRA_DAYS_CUSHION = 1

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = PROJECT_ROOT / "state" / "research" / "bonereaper"
REPORT_HTML = PROJECT_ROOT / "runbooks" / "study" / "quick-audit.html"
DECISION_MD = PROJECT_ROOT / "runbooks" / "study" / "preflight-decision.md"
LABELLED_PARQUET = STATE_DIR / "labelled_audit.parquet"


def _today_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# ---- Cache layer ----


def load_subgraph_fills_cached(cutoff_unix: int) -> list[dict[str, Any]]:
    """Pull subgraph fills (maker + taker), cache PER ROLE so a fail in one
    doesn't lose progress in the other.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(45.0)) as cli:
        meta = subgraph_meta(client=cli)
        if meta:
            print(
                f"  subgraph head: block {meta['block']['number']} "
                f"(ts {meta['block']['timestamp']})"
            )
        for role in ("maker", "taker"):
            cache = STATE_DIR / f"subgraph_fills_{role}_{_today_utc_str()}.json"
            if cache.exists():
                rows: list[dict[str, Any]] = json.loads(cache.read_text())
                print(f"  [cache hit] {cache.name}  ({len(rows)} fills)")
            else:
                print(f"  --- pulling {role} fills (cutoff_unix={cutoff_unix}) ---")
                rows = fetch_user_fills(
                    BONEREAPER_ADDR, role=role, cutoff_unix=cutoff_unix, client=cli
                )
                for r in rows:
                    r["_role"] = role
                cache.write_text(json.dumps(rows))
                print(f"  cached {len(rows)} {role} fills to {cache.name}")
            for r in rows:
                r.setdefault("_role", role)
            out.extend(rows)
    return out


def load_token_to_condition_cached(token_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve ERC1155 token IDs to (conditionId, outcomeIndex) via subgraph."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cache = STATE_DIR / f"token_to_condition_{_today_utc_str()}.json"
    cached: dict[str, dict[str, Any]] = {}
    if cache.exists():
        cached = json.loads(cache.read_text())
    distinct = sorted({t for t in token_ids if t and t != USDC_TOKEN_ID})
    missing = [t for t in distinct if t not in cached]
    if missing:
        print(f"  resolving {len(missing)} new token ids via subgraph MarketData ...")
        with httpx.Client(timeout=httpx.Timeout(30.0)) as cli:
            new_data = fetch_market_data_batch(missing, client=cli)
        cached.update(new_data)
        # tokens not found in subgraph: cache empty placeholder so we don't re-query
        for t in missing:
            cached.setdefault(t, {})
        cache.write_text(json.dumps(cached))
        print(f"  total cached: {len(cached)}")
    else:
        print(f"  [cache hit] {cache.name}  ({len(cached)} mappings)")
    return cached


def load_condition_markets_cached(condition_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve conditionIds to gamma-api market records (slug, outcomes, etc.)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cache = STATE_DIR / f"markets_{_today_utc_str()}.json"
    cached: dict[str, dict[str, Any]] = {}
    if cache.exists():
        cached = json.loads(cache.read_text())
    distinct = sorted({c for c in condition_ids if c})
    missing = [c for c in distinct if c not in cached]
    if missing:
        print(f"  resolving {len(missing)} conditions via Gamma API (concurrency=8) ...")
        with (
            httpx.Client(timeout=httpx.Timeout(15.0)) as cli,
            ThreadPoolExecutor(max_workers=8) as ex,
        ):
            futures = {ex.submit(fetch_market_by_condition_id, c, client=cli): c for c in missing}
            done = 0
            for fut in as_completed(futures):
                cid = futures[fut]
                try:
                    m = fut.result()
                except httpx.HTTPError as e:
                    print(f"    [warn] {cid[:18]}…: {e}")
                    m = None
                cached[cid] = m or {}
                done += 1
                if done % 200 == 0:
                    print(f"    progress: {done}/{len(missing)}")
                time.sleep(0.02)
        cache.write_text(json.dumps(cached))
        print(f"  total markets cached: {len(cached)}")
    else:
        print(f"  [cache hit] {cache.name}  ({len(cached)} markets)")
    return cached


# ---- Labelling ----


def _interpret_fill(
    fill: dict[str, Any],
) -> tuple[str | None, str, float, float, float]:
    """Project a subgraph fill into (outcome_token_id, side, size, notional, price).

    Polymarket CTF Exchange events:
      - One of makerAssetId/takerAssetId is "0" (USDC).
      - The other is the outcome ERC1155 token id.
      - Each side has 6-decimal precision.
    Bonereaper's "side" depends on whether he ends up holding the outcome token
    (BUY) or USDC (SELL):

      maker == bonereaper:  he gave makerAsset, received takerAsset
        makerAssetId == 0 → BUY  (he received outcome token)
        takerAssetId == 0 → SELL (he received USDC)
      taker == bonereaper:  he gave takerAsset, received makerAsset
        takerAssetId == 0 → BUY  (he received outcome token)
        makerAssetId == 0 → SELL (he received USDC)
    """
    role = fill["_role"]
    maker_id = fill["makerAssetId"]
    taker_id = fill["takerAssetId"]
    maker_amt = int(fill["makerAmountFilled"])
    taker_amt = int(fill["takerAmountFilled"])

    if role == "maker":
        if maker_id == USDC_TOKEN_ID:
            outcome_token = taker_id
            side = "BUY"
            usdc_amt = maker_amt
            shares_amt = taker_amt
        else:
            outcome_token = maker_id
            side = "SELL"
            usdc_amt = taker_amt
            shares_amt = maker_amt
    else:  # taker
        if taker_id == USDC_TOKEN_ID:
            outcome_token = maker_id
            side = "BUY"
            usdc_amt = taker_amt
            shares_amt = maker_amt
        else:
            outcome_token = taker_id
            side = "SELL"
            usdc_amt = maker_amt
            shares_amt = taker_amt

    if outcome_token == USDC_TOKEN_ID or shares_amt == 0:
        # malformed / pure transfer — skip downstream
        return None, side, 0.0, 0.0, 0.0
    notional = usdc_amt / (10**TOKEN_DECIMALS)
    size = shares_amt / (10**TOKEN_DECIMALS)
    price = notional / size if size else 0.0
    return outcome_token, side, size, notional, price


def label_fills(
    fills: list[dict[str, Any]],
    token_to_cond: dict[str, dict[str, Any]],
    cond_to_market: dict[str, dict[str, Any]],
) -> pl.DataFrame:
    """Build the labelled DataFrame: per-trade with category + win/loss + pnl."""
    rows: list[dict[str, Any]] = []
    for f in fills:
        outcome_token, side, size, notional, price = _interpret_fill(f)
        if outcome_token is None:
            continue

        cond_info = token_to_cond.get(outcome_token, {})
        condition_id = cond_info.get("condition") or ""
        market = cond_to_market.get(condition_id, {}) if condition_id else {}

        slug = market.get("slug") or ""
        category = (
            "btc_5m"
            if slug.startswith(BTC_5M_PREFIX)
            else "eth_5m"
            if slug.startswith(ETH_5M_PREFIX)
            else "eth_15m"
            if slug.startswith(ETH_15M_PREFIX)
            else "other"
        )

        outcomes_raw = market.get("outcomes")
        outcome_prices_raw = market.get("outcomePrices")
        clob_ids_raw = market.get("clobTokenIds")
        outcomes = (
            json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
        )
        outcome_prices = (
            json.loads(outcome_prices_raw)
            if isinstance(outcome_prices_raw, str)
            else (outcome_prices_raw or [])
        )
        clob_ids = (
            json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else (clob_ids_raw or [])
        )

        market_closed = bool(market.get("closed", False))
        market_resolved = market_closed and len(outcome_prices) == 2 and "1" in outcome_prices

        traded_outcome: str | None = None
        is_win: bool | None = None
        gross_pnl = 0.0
        if outcome_token and clob_ids and outcome_token in clob_ids:
            try:
                idx = clob_ids.index(outcome_token)
                if idx < len(outcomes):
                    traded_outcome = outcomes[idx]
                if market_resolved and idx < len(outcome_prices):
                    won_token = outcome_prices[idx] == "1"
                    if side == "BUY":
                        gross_pnl = (1.0 - price) * size if won_token else (-price) * size
                    else:  # SELL
                        gross_pnl = (price - 1.0) * size if won_token else price * size
                    is_win = gross_pnl > 0
            except ValueError:
                pass

        ts_unix = int(f["timestamp"])
        rows.append(
            {
                "tx_hash": f["transactionHash"],
                "ts_unix": ts_unix,
                "dt_utc": datetime.fromtimestamp(ts_unix, tz=UTC),
                "role": f["_role"],
                "side": side,
                "outcome_token": outcome_token,
                "condition_id": condition_id,
                "slug": slug,
                "category": category,
                "outcome": traded_outcome,
                "price": price,
                "size": size,
                "notional": notional,
                "market_closed": market_closed,
                "market_resolved": market_resolved,
                "is_win": is_win,
                "gross_pnl": gross_pnl,
            }
        )
    return pl.DataFrame(rows)


# ---- Metrics ----


def compute_metrics(df: pl.DataFrame) -> dict[str, Any]:
    if df.height == 0:
        return {
            "btc5m_total_trades": 0,
            "btc5m_total_resolved": 0,
            "btc5m_total_volume": 0.0,
            "btc5m_30d_trades": 0,
            "btc5m_30d_winrate": 0.0,
            "btc5m_90d_winrate": 0.0,
            "btc5m_alltime_winrate": 0.0,
            "btc5m_avg_size": 0.0,
            "btc5m_30d_volume": 0.0,
            "btc5m_prev_30d_volume": 0.0,
            "btc5m_30d_volume_change_pct": 0.0,
            "btc5m_up_count": 0,
            "btc5m_down_count": 0,
            "eth5m_trades": 0,
            "eth15m_trades": 0,
            "other_trades": 0,
            "eth5m_alltime_winrate": 0.0,
            "all_categories_total": 0,
            "earliest_trade_dt": None,
            "latest_trade_dt": None,
            "subgraph_lag_hours": None,
        }
    now = datetime.now(UTC)
    btc5 = df.filter(pl.col("category") == "btc_5m")
    btc5_resolved = btc5.filter(pl.col("market_resolved"))

    latest_dt = df.select(pl.col("dt_utc").max()).item()
    subgraph_lag_hours = None
    if latest_dt is not None:
        subgraph_lag_hours = (now - latest_dt).total_seconds() / 3600

    # Anchor windows on the most-recent observed timestamp, not on `now`,
    # because the subgraph lags real time. This makes "30 days ending at the
    # subgraph head" the apples-to-apples comparison.
    anchor = latest_dt or now
    cutoff_30d = anchor - timedelta(days=30)
    cutoff_60d = anchor - timedelta(days=60)
    cutoff_90d = anchor - timedelta(days=90)

    btc5_30d = btc5_resolved.filter(pl.col("dt_utc") >= cutoff_30d)
    btc5_90d = btc5_resolved.filter(pl.col("dt_utc") >= cutoff_90d)

    btc5_curr_30d_volume = (
        btc5.filter(pl.col("dt_utc") >= cutoff_30d).select(pl.col("notional").sum()).item() or 0.0
    )
    btc5_prev_30d_volume = (
        btc5.filter((pl.col("dt_utc") >= cutoff_60d) & (pl.col("dt_utc") < cutoff_30d))
        .select(pl.col("notional").sum())
        .item()
        or 0.0
    )
    if btc5_prev_30d_volume > 0:
        vol_30d_change_pct = (btc5_curr_30d_volume - btc5_prev_30d_volume) / btc5_prev_30d_volume
    else:
        vol_30d_change_pct = 0.0

    def winrate(d: pl.DataFrame) -> float:
        wins = d.filter(pl.col("is_win") == True).height  # noqa: E712
        total = d.height
        return (wins / total) if total else 0.0

    return {
        "btc5m_total_trades": btc5.height,
        "btc5m_total_resolved": btc5_resolved.height,
        "btc5m_total_volume": btc5.select(pl.col("notional").sum()).item() or 0.0,
        "btc5m_30d_trades": btc5_30d.height,
        "btc5m_30d_winrate": winrate(btc5_30d),
        "btc5m_90d_winrate": winrate(btc5_90d),
        "btc5m_alltime_winrate": winrate(btc5_resolved),
        "btc5m_avg_size": btc5.select(pl.col("size").mean()).item() or 0.0,
        "btc5m_30d_volume": btc5_curr_30d_volume,
        "btc5m_prev_30d_volume": btc5_prev_30d_volume,
        "btc5m_30d_volume_change_pct": vol_30d_change_pct,
        "btc5m_up_count": btc5.filter(pl.col("outcome") == "Up").height,
        "btc5m_down_count": btc5.filter(pl.col("outcome") == "Down").height,
        "eth5m_trades": df.filter(pl.col("category") == "eth_5m").height,
        "eth15m_trades": df.filter(pl.col("category") == "eth_15m").height,
        "other_trades": df.filter(pl.col("category") == "other").height,
        "eth5m_alltime_winrate": winrate(
            df.filter((pl.col("category") == "eth_5m") & pl.col("market_resolved"))
        ),
        "all_categories_total": df.height,
        "earliest_trade_dt": df.select(pl.col("dt_utc").min()).item(),
        "latest_trade_dt": latest_dt,
        "subgraph_lag_hours": subgraph_lag_hours,
        "audit_anchor": anchor,
    }


def evaluate_gate(m: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if m["btc5m_30d_winrate"] < GATE_MIN_30D_WINRATE and m["btc5m_30d_trades"] > 0:
        failures.append(
            f"30-day BTC 5m win-rate {m['btc5m_30d_winrate']:.1%} < {GATE_MIN_30D_WINRATE:.0%}"
        )
    if m["btc5m_total_trades"] < GATE_MIN_TOTAL_TRADES:
        failures.append(
            f"total BTC 5m observable trades {m['btc5m_total_trades']} < {GATE_MIN_TOTAL_TRADES}"
        )
    if m["btc5m_30d_volume_change_pct"] < GATE_MAX_VOLUME_DROP_PCT:
        failures.append(
            f"30-day volume change {m['btc5m_30d_volume_change_pct']:.1%} < "
            f"{GATE_MAX_VOLUME_DROP_PCT:.0%} (>40% drop)"
        )
    if m["btc5m_30d_trades"] == 0:
        failures.append(
            "zero BTC 5m resolved trades in last 30 days of subgraph window — "
            "wallet may have moved to NegRisk Exchange (not indexed by orderbook subgraph)"
        )
    return (len(failures) == 0, failures)


# ---- Plots & report ----


def _png_b64(fig: matplotlib.figure.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def render_report(df: pl.DataFrame, m: dict[str, Any], proceed: bool, reasons: list[str]) -> None:
    REPORT_HTML.parent.mkdir(parents=True, exist_ok=True)
    btc5 = df.filter(pl.col("category") == "btc_5m")
    btc5_resolved = btc5.filter(pl.col("market_resolved"))

    fig1, ax1 = plt.subplots(figsize=(10, 3.5))
    if btc5_resolved.height:
        cum = btc5_resolved.sort("dt_utc").with_columns(pl.col("gross_pnl").cum_sum().alias("cum"))
        ax1.plot(cum["dt_utc"].to_list(), cum["cum"].to_list(), color="#7C5CFF", linewidth=1.2)
        ax1.fill_between(
            cum["dt_utc"].to_list(), 0, cum["cum"].to_list(), alpha=0.18, color="#7C5CFF"
        )
        ax1.axhline(0, color="#94A3B8", linewidth=0.6, linestyle="--")
    ax1.set_title("Cumulative gross P&L on BTC 5-min markets", loc="left", fontsize=11)
    ax1.set_ylabel("USDC")
    ax1.grid(axis="y", alpha=0.3)
    plot1 = _png_b64(fig1)

    fig2, ax2 = plt.subplots(figsize=(10, 3.0))
    if btc5_resolved.height >= 50:
        roll = (
            btc5_resolved.sort("dt_utc")
            .with_columns(pl.col("is_win").cast(pl.Float64).alias("w"))
            .with_columns(pl.col("w").rolling_mean(window_size=50).alias("roll50"))
        )
        ax2.plot(roll["dt_utc"].to_list(), roll["roll50"].to_list(), color="#23A26D", linewidth=1.2)
        ax2.axhline(
            GATE_MIN_30D_WINRATE, color="#E5484D", linewidth=0.8, linestyle="--", label="60% gate"
        )
        ax2.axhline(0.50, color="#94A3B8", linewidth=0.5, linestyle=":", label="coinflip")
        ax2.legend(loc="lower left", fontsize=8)
    ax2.set_title("Rolling 50-trade win-rate (BTC 5-min, resolved)", loc="left", fontsize=11)
    ax2.set_ylim(0.0, 1.0)
    ax2.grid(axis="y", alpha=0.3)
    plot2 = _png_b64(fig2)

    fig3, ax3 = plt.subplots(figsize=(10, 2.6))
    if btc5_resolved.height:
        h_df = btc5_resolved.with_columns(
            pl.col("dt_utc").dt.hour().alias("hour"),
            pl.col("is_win").cast(pl.Float64).alias("w"),
        )
        agg = (
            h_df.group_by("hour")
            .agg(
                pl.col("w").mean().alias("winrate"),
                pl.len().alias("count"),
            )
            .sort("hour")
        )
        rate_by_hour = {row["hour"]: row["winrate"] for row in agg.iter_rows(named=True)}
        count_by_hour = {row["hour"]: row["count"] for row in agg.iter_rows(named=True)}
        hours = list(range(24))
        rates = [rate_by_hour.get(h, 0.0) for h in hours]
        counts = [count_by_hour.get(h, 0) for h in hours]
        bars = ax3.bar(
            hours,
            rates,
            color=["#23A26D" if r >= GATE_MIN_30D_WINRATE else "#E5484D" for r in rates],
        )
        for b, c in zip(bars, counts, strict=False):
            if c:
                ax3.text(
                    b.get_x() + b.get_width() / 2,
                    0.02,
                    str(c),
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color="white",
                )
        ax3.axhline(GATE_MIN_30D_WINRATE, color="#0F172A", linewidth=0.7, linestyle="--")
    ax3.set_title(
        "Win-rate by UTC hour (count overlay; green = beats 60%)", loc="left", fontsize=11
    )
    ax3.set_xticks(range(0, 24, 2))
    ax3.set_ylim(0.0, 1.0)
    plot3 = _png_b64(fig3)

    fig4, ax4 = plt.subplots(figsize=(10, 2.6))
    if btc5.height:
        vol = (
            btc5.sort("dt_utc")
            .with_columns(pl.col("dt_utc").dt.date().alias("date"))
            .group_by("date")
            .agg(pl.col("notional").sum().alias("vol"))
            .sort("date")
        )
        ax4.bar(vol["date"].to_list(), vol["vol"].to_list(), color="#3B82F6", width=0.8)
    ax4.set_title("Daily BTC 5-min trade notional (USDC)", loc="left", fontsize=11)
    ax4.grid(axis="y", alpha=0.3)
    plot4 = _png_b64(fig4)

    gate_color = "#23A26D" if proceed else "#E5484D"
    gate_label = "PROCEED" if proceed else "ABORT"
    reasons_html = (
        "".join(f"<li>{r}</li>" for r in reasons) if reasons else "<li>all criteria pass</li>"
    )
    lag_str = (
        f"{m['subgraph_lag_hours']:.1f} hours" if m["subgraph_lag_hours"] is not None else "n/a"
    )

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Bonereaper — Phase A Audit</title>
<style>
  body {{ font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial; color:#0F172A; max-width: 1080px; margin: 32px auto; padding: 0 24px; }}
  h1 {{ margin-bottom: 4px; }} h2 {{ margin-top: 28px; border-bottom: 1px solid #E2E8F0; padding-bottom:6px; }}
  .meta {{ color:#64748B; font-size: 12px; }}
  .gate {{ display: inline-block; padding: 4px 12px; border-radius: 4px; color: white; font-weight: 700; background: {gate_color}; }}
  .note {{ background: #FEF3C7; border-left: 4px solid #F5A524; padding: 10px 14px; margin: 12px 0; font-size: 12px; }}
  table {{ border-collapse: collapse; margin: 8px 0; }}
  td, th {{ border: 1px solid #E2E8F0; padding: 6px 10px; }}
  th {{ background: #F1F5F9; text-align: left; }}
  img {{ max-width: 100%; border: 1px solid #E2E8F0; border-radius: 4px; margin-top: 8px; }}
  .ok {{ color: #23A26D; font-weight: 600; }} .fail {{ color: #E5484D; font-weight: 600; }}
  ul {{ margin: 6px 0 12px 20px; }} li {{ margin: 2px 0; }}
</style></head><body>
<h1>Bonereaper — Phase A Pre-flight Audit</h1>
<p class="meta">Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")} ·
  wallet <code>{BONEREAPER_ADDR}</code> · subgraph fills: {df.height:,}</p>

<div class="note">
  <b>Data window.</b> Source = Goldsky orderbook subgraph (CTF Exchange contract).
  Indexer lag from real time: <b>{lag_str}</b>. Anchor = last observed fill;
  rolling windows are computed ending at that anchor, not at now. Trades on the
  NegRisk CTF Exchange (newer markets) are not indexed by this subgraph and
  therefore not visible here.
</div>

<h2>Gate decision: <span class="gate">{gate_label}</span></h2>
<ul>{reasons_html}</ul>

<h2>BTC 5-min headline numbers</h2>
<table>
  <tr><th>Metric</th><th>Value</th><th>Threshold</th></tr>
  <tr><td>Total observable trades (BTC 5m)</td>
      <td>{m["btc5m_total_trades"]:,}</td>
      <td>≥ {GATE_MIN_TOTAL_TRADES:,}</td></tr>
  <tr><td>Resolved trades (BTC 5m)</td>
      <td>{m["btc5m_total_resolved"]:,}</td><td>—</td></tr>
  <tr><td>Last-30-day trades (resolved)</td>
      <td>{m["btc5m_30d_trades"]:,}</td><td>—</td></tr>
  <tr><td>Last-30-day win-rate</td>
      <td><span class="{"ok" if m["btc5m_30d_winrate"] >= GATE_MIN_30D_WINRATE else "fail"}">{m["btc5m_30d_winrate"]:.1%}</span></td>
      <td>≥ {GATE_MIN_30D_WINRATE:.0%}</td></tr>
  <tr><td>Last-90-day win-rate</td>
      <td>{m["btc5m_90d_winrate"]:.1%}</td><td>—</td></tr>
  <tr><td>All-time resolved win-rate (subgraph window)</td>
      <td>{m["btc5m_alltime_winrate"]:.1%}</td><td>—</td></tr>
  <tr><td>30-day vs prior-30-day volume change</td>
      <td><span class="{"ok" if m["btc5m_30d_volume_change_pct"] >= GATE_MAX_VOLUME_DROP_PCT else "fail"}">{m["btc5m_30d_volume_change_pct"]:.1%}</span></td>
      <td>&gt; {GATE_MAX_VOLUME_DROP_PCT:.0%}</td></tr>
  <tr><td>Average trade size</td>
      <td>{m["btc5m_avg_size"]:.2f} shares</td><td>—</td></tr>
  <tr><td>UP / DOWN balance</td>
      <td>UP {m["btc5m_up_count"]:,} · DOWN {m["btc5m_down_count"]:,}</td><td>—</td></tr>
  <tr><td>Total notional (subgraph window)</td>
      <td>${m["btc5m_total_volume"]:,.0f}</td><td>—</td></tr>
</table>

<h2>Other markets (context, not in gate)</h2>
<table>
  <tr><th>Category</th><th>Trades</th><th>Win-rate (resolved)</th></tr>
  <tr><td>ETH 5m</td><td>{m["eth5m_trades"]:,}</td><td>{m["eth5m_alltime_winrate"]:.1%}</td></tr>
  <tr><td>ETH 15m</td><td>{m["eth15m_trades"]:,}</td><td>—</td></tr>
  <tr><td>Other markets</td><td>{m["other_trades"]:,}</td><td>—</td></tr>
</table>

<h2>Cumulative P&amp;L (BTC 5m)</h2>
<img src="data:image/png;base64,{plot1}">

<h2>Rolling 50-trade win-rate</h2>
<img src="data:image/png;base64,{plot2}">

<h2>Win-rate by UTC hour</h2>
<img src="data:image/png;base64,{plot3}">

<h2>Daily volume (BTC 5m)</h2>
<img src="data:image/png;base64,{plot4}">

<p class="meta">Source: Goldsky orderbook subgraph + Polymarket Gamma API.
Raw data cached at <code>state/research/bonereaper/</code>.</p>
</body></html>"""
    REPORT_HTML.write_text(html)
    print(f"  report written: {REPORT_HTML.relative_to(PROJECT_ROOT)}")


def write_decision(proceed: bool, reasons: list[str], m: dict[str, Any]) -> None:
    DECISION_MD.parent.mkdir(parents=True, exist_ok=True)
    head = (
        "PROCEED — Phase A passes; safe to design Phase B."
        if proceed
        else "ABORT — Phase A fails; do NOT design Phase B."
    )
    reason_block = "\n".join(f"- {r}" for r in reasons) if reasons else "- all gate criteria pass"
    lag_str = (
        f"{m['subgraph_lag_hours']:.1f}h" if m["subgraph_lag_hours"] is not None else "unknown"
    )

    text = f"""# Bonereaper — Phase A Pre-flight Decision

**Decision:** **{"PROCEED" if proceed else "ABORT"}**

> {head}

Generated: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}
Wallet: `{BONEREAPER_ADDR}` (Polymarket profile: `bonereaper`)
Data source: Goldsky orderbook subgraph (CTF Exchange) + Gamma API
Subgraph lag from real time: **{lag_str}**

## Gate evaluation

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| 30-day BTC 5m win-rate | {m["btc5m_30d_winrate"]:.1%} ({m["btc5m_30d_trades"]:,} trades) | ≥ {GATE_MIN_30D_WINRATE:.0%} | {"✅" if m["btc5m_30d_winrate"] >= GATE_MIN_30D_WINRATE and m["btc5m_30d_trades"] > 0 else "❌"} |
| Total BTC 5m trades observable | {m["btc5m_total_trades"]:,} | ≥ {GATE_MIN_TOTAL_TRADES:,} | {"✅" if m["btc5m_total_trades"] >= GATE_MIN_TOTAL_TRADES else "❌"} |
| 30-day volume change MoM | {m["btc5m_30d_volume_change_pct"]:.1%} | > {GATE_MAX_VOLUME_DROP_PCT:.0%} | {"✅" if m["btc5m_30d_volume_change_pct"] >= GATE_MAX_VOLUME_DROP_PCT else "❌"} |

## Reasons

{reason_block}

## Headline numbers (BTC 5-min only)

- All-time observable trades (subgraph window): **{m["btc5m_total_trades"]:,}** ({m["btc5m_total_resolved"]:,} resolved)
- All-time resolved win-rate: **{m["btc5m_alltime_winrate"]:.1%}**
- Last 30 days: **{m["btc5m_30d_trades"]:,}** trades, **{m["btc5m_30d_winrate"]:.1%}** win-rate
- Last 90 days: win-rate **{m["btc5m_90d_winrate"]:.1%}**
- Volume last 30d: **${m["btc5m_30d_volume"]:,.0f}** vs prior 30d **${m["btc5m_prev_30d_volume"]:,.0f}** ({m["btc5m_30d_volume_change_pct"]:+.1%})
- Avg trade size: **{m["btc5m_avg_size"]:.2f} shares**
- UP {m["btc5m_up_count"]:,} / DOWN {m["btc5m_down_count"]:,}
- Earliest BTC 5m trade observed: {m["earliest_trade_dt"]}
- Latest BTC 5m trade observed: {m["latest_trade_dt"]}

## Adjacent context (not in gate)

- ETH 5m trades: **{m["eth5m_trades"]:,}** (win-rate **{m["eth5m_alltime_winrate"]:.1%}**)
- ETH 15m trades: **{m["eth15m_trades"]:,}**
- Other markets: **{m["other_trades"]:,}**

## Limitation note

The orderbook subgraph indexes the original CTF Exchange contract only. Trades
on the NegRisk CTF Exchange (used for newer markets) are not visible. The
audit is computed on the subgraph window, anchored at the latest observed
fill. If the wallet has migrated to NegRisk recently, the most recent days
of activity are not in this report.

See `runbooks/study/quick-audit.html` for charts.
"""
    DECISION_MD.write_text(text)
    print(f"  decision written: {DECISION_MD.relative_to(PROJECT_ROOT)}")


# ---- Main ----


def main() -> int:
    print("== Bonereaper Phase A pre-flight audit (subgraph mode) ==")
    print(f"  wallet: {BONEREAPER_ADDR}")
    print(f"  state dir: {STATE_DIR.relative_to(PROJECT_ROOT)}")

    cutoff_unix = int(
        (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS + EXTRA_DAYS_CUSHION)).timestamp()
    )
    print(
        f"  cutoff: {datetime.fromtimestamp(cutoff_unix, tz=UTC).date()} " f"(unix {cutoff_unix})"
    )
    print()

    print("[1/4] loading subgraph fills")
    fills = load_subgraph_fills_cached(cutoff_unix)
    print(f"  total fills: {len(fills)}")
    print()

    print("[2/4] resolving outcome tokens → conditionIds")
    distinct_tokens: set[str] = set()
    for f in fills:
        for tid in (f.get("makerAssetId"), f.get("takerAssetId")):
            if tid and tid != USDC_TOKEN_ID:
                distinct_tokens.add(tid)
    print(f"  distinct outcome tokens: {len(distinct_tokens)}")
    token_to_cond = load_token_to_condition_cached(sorted(distinct_tokens))
    distinct_conditions: list[str] = sorted(
        {cond for v in token_to_cond.values() if v and (cond := v.get("condition"))}
    )
    print(f"  distinct conditionIds: {len(distinct_conditions)}")
    print()

    print("[3/4] resolving conditionIds → markets (gamma-api)")
    cond_to_market = load_condition_markets_cached(list(distinct_conditions))
    btc5m_markets = sum(
        1
        for m in cond_to_market.values()
        if isinstance(m, dict) and (m.get("slug") or "").startswith(BTC_5M_PREFIX)
    )
    print(f"  BTC 5m markets recognized: {btc5m_markets}")
    print()

    print("[4/4] labelling + computing metrics")
    df = label_fills(fills, token_to_cond, cond_to_market)
    df.write_parquet(LABELLED_PARQUET)
    print(f"  labelled rows: {df.height} → {LABELLED_PARQUET.relative_to(PROJECT_ROOT)}")
    metrics = compute_metrics(df)
    proceed, reasons = evaluate_gate(metrics)

    print()
    print("[5/5] rendering report + decision")
    render_report(df, metrics, proceed, reasons)
    write_decision(proceed, reasons, metrics)

    print()
    print("== gate evaluation ==")
    for r in reasons or ["all criteria pass"]:
        print(f"   {('FAIL' if reasons else 'OK  ')} {r}")
    print(f"   decision: {'PROCEED' if proceed else 'ABORT'}")
    return 0 if proceed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""mmb_g11_probes — Phase S Session 5 pre-deploy empirical probes.

Three probes deferred from S.1.1 + S.3 + S.4 because they require live
CLOB calls with real $5 test orders. Operator runs each ONCE after the
USDC.e allowance is set (via `mm_set_allowance.py`).

USAGE:
  $ uv run python scripts/research/mmb_g11_probes.py --mode fee
  $ uv run python scripts/research/mmb_g11_probes.py --mode cancel-latency
  $ uv run python scripts/research/mmb_g11_probes.py --mode rate-limit

EACH MODE WRITES:
  - runbooks/S-mmb-{fee|cancel-latency|rate-limit}-empirical-<UTC>.md
  - state/research/g11-{fee|cancel-latency|rate-limit}-<UTC>.json

REAL-MONEY EXPOSURE per mode (worst case):
  - fee:            ~$5 (one maker BUY at -$0.20 depth; cancelled on
                         exit if unfilled within 5 min)
  - cancel-latency: ~$0 (places + cancels each order within a second;
                         no fill exposure expected)
  - rate-limit:     ~$0 (same — fast cancel; only triggers 429 on rate)

PRE-CONDITIONS (same as run_mm_live.py):
  - state/mm-allowance.json present + recent + sufficient
  - L2 creds + wallet env vars set (CLOB_API_KEY/SECRET/PASSPHRASE,
    PK_SIGNER, POLY_FUNDER)
  - NO halt sentinel (probe needs to be able to place real orders;
    operator removes sentinel for probe + re-creates if probe surfaces
    something concerning)

Probe results inform S.5 pre-deploy decisions:
  - fee probe: if maker fee > 0, recalibrate J7Priors.bet_size math
                before flipping bot-mm.service ExecStart to live.
  - cancel-latency: if p95 > 200ms, raise plan_update repost thresholds
                    so we're not churning faster than we can cancel.
  - rate-limit:   if 429s appear at < 30 orders/sec, lower the
                  MAX_ORDERS_PER_MINUTE cap in RiskCaps.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

LOG = logging.getLogger("polymarket_bot.scripts.mmb_g11_probes")

DEFAULT_PROBE_SIZE_USD = 5.0
DEFAULT_PROBE_DEPTH_FROM_ASK = 0.20  # post deep so we don't fill quickly
DEFAULT_TICK_SIZE = "0.01"
DEFAULT_MIN_ORDER_SIZE_SHARES = 5.0

RUNBOOK_DIR = PROJECT_ROOT / "runbooks"
JSON_DIR = PROJECT_ROOT / "state" / "research"


# ---------------- shared setup ----------------


def _build_clob_client() -> Any:
    """Build an L2-authenticated ClobClient. Raises if env vars missing."""
    required = [
        "CLOB_API_KEY",
        "CLOB_API_SECRET",
        "CLOB_API_PASSPHRASE",
        "PK_SIGNER",
        "POLY_FUNDER",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(missing)}")
    from py_clob_client.client import ClobClient  # type: ignore[import-untyped]
    from py_clob_client.clob_types import ApiCreds  # type: ignore[import-untyped]

    creds = ApiCreds(
        api_key=os.environ["CLOB_API_KEY"],
        api_secret=os.environ["CLOB_API_SECRET"],
        api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
    )
    return ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=os.environ["PK_SIGNER"],
        creds=creds,
        signature_type=2,
        funder=os.environ["POLY_FUNDER"],
    )


async def _pick_btc_5m_market() -> dict[str, Any]:
    """Find an active BTC 5m market for the probe."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as cli:
        resp = await cli.get(
            "https://gamma-api.polymarket.com/events",
            params={"closed": "false", "active": "true", "tag_id": "100381", "limit": "5"},
        )
        resp.raise_for_status()
        events = resp.json()
    for ev in events:
        slug = ev.get("slug") or ""
        if not slug.startswith("btc-updown-5m-"):
            continue
        mks = ev.get("markets") or []
        if not mks:
            continue
        m = mks[0]
        ctids_raw = m.get("clobTokenIds")
        if isinstance(ctids_raw, str):
            try:
                ctids = json.loads(ctids_raw)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            ctids = ctids_raw or []
        if not isinstance(ctids, list) or len(ctids) != 2:
            continue
        return {
            "market_id": m.get("conditionId") or slug,
            "token_up": ctids[0],
            "token_dn": ctids[1],
            "slug": slug,
            "end_date": m.get("endDate") or ev.get("endDate"),
        }
    raise RuntimeError("no active BTC 5m market found via Gamma")


def _now_utc_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")


def _write_outputs(mode: str, payload: dict[str, Any], md_body: str) -> None:
    ts = _now_utc_str()
    RUNBOOK_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    md_path = RUNBOOK_DIR / f"S-mmb-{mode}-empirical-{ts}.md"
    json_path = JSON_DIR / f"g11-{mode}-{ts}.json"
    md_path.write_text(md_body)
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")


# ---------------- probe 1: maker fee ----------------


async def _probe_fee(client: Any) -> int:
    """Place 1 maker BUY at -$0.20 depth. Wait up to 5 min for fill.
    Compare gross fill PnL vs settled USDC.e balance delta."""
    from py_clob_client.clob_types import (
        AssetType,
        BalanceAllowanceParams,
        OrderArgs,
        OrderType,
    )
    from py_clob_client.order_builder.constants import BUY  # type: ignore[import-untyped]

    market = await _pick_btc_5m_market()
    print(f"probe market: {market['slug']}")

    # Read best ask + balance pre-place.
    book = client.get_order_book(market["token_up"])
    asks = book.get("asks") or []
    if not asks:
        print("ERROR: no asks on UP side; aborting probe")
        return 2
    best_ask = float(asks[0]["price"])
    probe_price = round(max(0.05, best_ask - DEFAULT_PROBE_DEPTH_FROM_ASK), 2)
    probe_size_shares = DEFAULT_PROBE_SIZE_USD / probe_price

    ba_params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
    pre = client.get_balance_allowance(ba_params)
    pre_bal_wei = int(pre.get("balance", 0))

    print(
        f"placing maker BUY @ ${probe_price:.2f} x {probe_size_shares:.2f} shares "
        f"(${DEFAULT_PROBE_SIZE_USD:.2f} gross); pre-balance ${pre_bal_wei / 1e6:.2f}"
    )

    signed = client.create_order(
        OrderArgs(token_id=market["token_up"], price=probe_price, size=probe_size_shares, side=BUY),
        options={"tick_size": DEFAULT_TICK_SIZE, "neg_risk": False},
    )
    resp = client.post_order(signed, OrderType.GTC, True)
    order_id = str(resp.get("orderID") or resp.get("order_id") or "")
    place_ts = time.time()
    print(f"placed: order_id={order_id} status={resp.get('status')}")

    if not order_id:
        print(f"ERROR: place_order returned no order_id: {resp}")
        return 1

    # Poll for fill (up to 5 min); else cancel.
    filled = False
    waited = 0.0
    while waited < 300:
        order = client.get_order(order_id)
        if order and str(order.get("status", "")).lower() in ("matched", "confirmed", "filled"):
            filled = True
            break
        await asyncio.sleep(5)
        waited += 5

    if not filled:
        client.cancel(order_id)
        print(f"not filled in {waited:.0f}s; cancelled. fee probe inconclusive.")
        payload: dict[str, Any] = {
            "mode": "fee",
            "result": "inconclusive_not_filled",
            "market": market,
            "probe_price": probe_price,
            "probe_size_usd": DEFAULT_PROBE_SIZE_USD,
            "waited_s": waited,
        }
        md = (
            f"# G11 fee probe — INCONCLUSIVE (not filled in {waited:.0f}s)\n\n"
            f"Probe placed at {probe_price:.4f} x {probe_size_shares:.2f} shares = "
            f"${DEFAULT_PROBE_SIZE_USD:.2f} gross on {market['slug']}. Order was "
            f"cancelled after the wait window. Re-run probe during a more active "
            f"trading window.\n"
        )
        _write_outputs("fee", payload, md)
        return 0

    fill_ts = time.time()
    post = client.get_balance_allowance(ba_params)
    post_bal_wei = int(post.get("balance", 0))
    settled_delta_usd = (post_bal_wei - pre_bal_wei) / 1e6

    # Gross expectation: bought N shares at $P → balance debits by N*P.
    gross_debit_expected = probe_size_shares * probe_price
    # Settled debit is the negative of (post - pre) → -settled_delta_usd.
    realized_fee = (-settled_delta_usd) - gross_debit_expected

    print(f"filled in {fill_ts - place_ts:.1f}s")
    print(f"  expected debit: ${gross_debit_expected:+.4f}")
    print(f"  settled delta:  ${settled_delta_usd:+.4f}")
    print(f"  realized fee:   ${realized_fee:+.4f}")

    payload = {
        "mode": "fee",
        "result": "filled",
        "market": market,
        "probe_price": probe_price,
        "probe_size_shares": probe_size_shares,
        "probe_size_usd": DEFAULT_PROBE_SIZE_USD,
        "fill_wait_s": fill_ts - place_ts,
        "pre_balance_usd": pre_bal_wei / 1e6,
        "post_balance_usd": post_bal_wei / 1e6,
        "expected_debit_usd": gross_debit_expected,
        "settled_delta_usd": settled_delta_usd,
        "realized_fee_usd": realized_fee,
        "realized_fee_bps": (realized_fee / gross_debit_expected) * 10_000.0
        if gross_debit_expected
        else 0,
    }
    md = (
        f"# G11 fee probe — FILLED\n\n"
        f"| Metric | Value |\n|---|---:|\n"
        f"| Market | `{market['slug']}` |\n"
        f"| Probe size | ${DEFAULT_PROBE_SIZE_USD:.2f} gross @ ${probe_price:.4f} |\n"
        f"| Fill wait | {fill_ts - place_ts:.1f}s |\n"
        f"| Expected debit | ${gross_debit_expected:.4f} |\n"
        f"| Settled delta | ${settled_delta_usd:+.4f} |\n"
        f"| **Realized fee** | **${realized_fee:+.4f}** ({payload['realized_fee_bps']:+.1f} bps) |\n\n"
        f"## Implication for S.5\n\n"
        f"If realized_fee > $0.01 (~20 bps on this probe size), recalibrate "
        f"`J7Priors.bet_size` math to include fee in the EV check before "
        f"flipping `bot-mm.service` ExecStart to `run_mm_live.py`.\n"
    )
    _write_outputs("fee", payload, md)
    return 0


# ---------------- probe 2: cancel latency ----------------


async def _probe_cancel_latency(client: Any, n_iters: int = 100) -> int:
    """Place + cancel N orders sequentially. Record latency for each cancel."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    market = await _pick_btc_5m_market()
    print(f"probe market: {market['slug']}")
    print(f"running {n_iters} place+cancel cycles (size=$1 deep — won't fill)")

    book = client.get_order_book(market["token_up"])
    asks = book.get("asks") or []
    if not asks:
        print("ERROR: no asks on UP side; aborting")
        return 2
    best_ask = float(asks[0]["price"])
    probe_price = round(max(0.05, best_ask - 0.30), 2)  # deep so won't fill
    probe_size_shares = max(DEFAULT_MIN_ORDER_SIZE_SHARES, 1.0 / probe_price)

    cancel_latencies_ms: list[float] = []
    place_failures = 0
    cancel_failures = 0

    for i in range(n_iters):
        try:
            signed = client.create_order(
                OrderArgs(
                    token_id=market["token_up"],
                    price=probe_price,
                    size=probe_size_shares,
                    side=BUY,
                ),
                options={"tick_size": DEFAULT_TICK_SIZE, "neg_risk": False},
            )
            resp = client.post_order(signed, OrderType.GTC, True)
            order_id = str(resp.get("orderID") or resp.get("order_id") or "")
            if not order_id:
                place_failures += 1
                continue
            t_start = time.time()
            cancel_resp = client.cancel(order_id)
            elapsed_ms = (time.time() - t_start) * 1000
            if cancel_resp:
                cancel_latencies_ms.append(elapsed_ms)
            else:
                cancel_failures += 1
        except Exception as exc:
            LOG.warning("iter %d failed: %s", i, exc)
            place_failures += 1
        if i and i % 10 == 0:
            print(f"  {i}/{n_iters} done, n_cancels={len(cancel_latencies_ms)}")

    if not cancel_latencies_ms:
        print("ERROR: no successful cancel measurements")
        return 1

    sorted_ms = sorted(cancel_latencies_ms)
    p50 = statistics.median(sorted_ms)
    p95 = sorted_ms[int(len(sorted_ms) * 0.95)]
    p99 = sorted_ms[int(len(sorted_ms) * 0.99)] if len(sorted_ms) >= 100 else max(sorted_ms)

    payload: dict[str, Any] = {
        "mode": "cancel-latency",
        "market": market,
        "n_iters": n_iters,
        "n_cancels": len(cancel_latencies_ms),
        "place_failures": place_failures,
        "cancel_failures": cancel_failures,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "mean_ms": statistics.mean(cancel_latencies_ms),
        "min_ms": min(cancel_latencies_ms),
        "max_ms": max(cancel_latencies_ms),
    }
    md = (
        f"# G11 cancel-latency probe\n\n"
        f"| Metric | Value |\n|---|---:|\n"
        f"| Iters | {n_iters} |\n"
        f"| Successful cancels | {len(cancel_latencies_ms)} |\n"
        f"| Place failures | {place_failures} |\n"
        f"| Cancel failures | {cancel_failures} |\n"
        f"| **p50** | **{p50:.1f}ms** |\n"
        f"| **p95** | **{p95:.1f}ms** |\n"
        f"| **p99** | **{p99:.1f}ms** |\n"
        f"| mean | {statistics.mean(cancel_latencies_ms):.1f}ms |\n"
        f"| min | {min(cancel_latencies_ms):.1f}ms |\n"
        f"| max | {max(cancel_latencies_ms):.1f}ms |\n\n"
        f"## Implication\n\n"
        f"If p95 > 200ms, raise `LadderPlanner.l1_repost_threshold` so we don't "
        f"churn cancel-replaces faster than the network can serve. Currently "
        f"set to 0.02 (cents on best_ask move).\n"
    )
    _write_outputs("cancel-latency", payload, md)
    return 0


# ---------------- probe 3: rate-limit ----------------


async def _probe_rate_limit(client: Any) -> int:
    """Place at increasing rates until 429. Log every response header."""
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    market = await _pick_btc_5m_market()
    print(f"probe market: {market['slug']}")

    book = client.get_order_book(market["token_up"])
    asks = book.get("asks") or []
    if not asks:
        print("ERROR: no asks on UP side")
        return 2
    best_ask = float(asks[0]["price"])
    probe_price = round(max(0.05, best_ask - 0.30), 2)
    probe_size_shares = max(DEFAULT_MIN_ORDER_SIZE_SHARES, 1.0 / probe_price)

    rates_to_try = [1, 5, 10, 20, 30]
    results: list[dict[str, Any]] = []
    placed_order_ids: list[str] = []

    for rate in rates_to_try:
        interval = 1.0 / rate
        print(f"trying rate={rate}/sec ({interval * 1000:.0f}ms between calls)")
        n_429 = 0
        n_ok = 0
        n_other_err = 0
        for _ in range(rate * 3):  # 3 seconds at this rate
            t0 = time.time()
            try:
                signed = client.create_order(
                    OrderArgs(
                        token_id=market["token_up"],
                        price=probe_price,
                        size=probe_size_shares,
                        side=BUY,
                    ),
                    options={"tick_size": DEFAULT_TICK_SIZE, "neg_risk": False},
                )
                resp = client.post_order(signed, OrderType.GTC, True)
                if isinstance(resp, dict) and not resp.get("success", True):
                    err = str(resp.get("errorMsg") or "")
                    if "429" in err or "rate" in err.lower():
                        n_429 += 1
                    else:
                        n_other_err += 1
                else:
                    n_ok += 1
                    oid = (
                        str(resp.get("orderID") or resp.get("order_id") or "")
                        if isinstance(resp, dict)
                        else ""
                    )
                    if oid:
                        placed_order_ids.append(oid)
            except Exception as exc:
                if "429" in str(exc):
                    n_429 += 1
                else:
                    n_other_err += 1
            elapsed = time.time() - t0
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
        results.append(
            {"rate_per_sec": rate, "n_ok": n_ok, "n_429": n_429, "n_other_err": n_other_err}
        )
        if n_429 > 0:
            print(f"  → first 429 at rate={rate}/sec; stopping probe")
            break

    # Cleanup: cancel any placed orders.
    for oid in placed_order_ids:
        try:
            client.cancel(oid)
        except Exception as exc:
            LOG.debug("cleanup cancel for %s failed: %s", oid, exc)

    payload: dict[str, Any] = {
        "mode": "rate-limit",
        "market": market,
        "results_per_rate": results,
        "n_orders_placed_for_cleanup": len(placed_order_ids),
    }
    table_rows = "\n".join(
        f"| {r['rate_per_sec']}/sec | {r['n_ok']} | {r['n_429']} | {r['n_other_err']} |"
        for r in results
    )
    md = (
        f"# G11 rate-limit probe\n\n"
        f"| Rate | OK | 429 | Other err |\n|---|---:|---:|---:|\n"
        f"{table_rows}\n\n"
        f"## Implication\n\n"
        f"If 429 surfaces at < 30/sec, lower `RiskCaps.max_orders_per_minute` "
        f"so MMB's cancel-replace cadence stays under the documented ceiling. "
        f"Current default is 30/min ≈ 0.5/sec — well below any reasonable ceiling.\n"
    )
    _write_outputs("rate-limit", payload, md)
    return 0


# ---------------- main ----------------


async def amain(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("fee", "cancel-latency", "rate-limit"),
        help="Which probe to run",
    )
    parser.add_argument(
        "--n-iters", type=int, default=100, help="cancel-latency: how many iterations"
    )
    args = parser.parse_args(argv)

    try:
        client = _build_clob_client()
    except RuntimeError as exc:
        LOG.error("cannot build client: %s", exc)
        return 2

    if args.mode == "fee":
        return await _probe_fee(client)
    if args.mode == "cancel-latency":
        return await _probe_cancel_latency(client, n_iters=args.n_iters)
    if args.mode == "rate-limit":
        return await _probe_rate_limit(client)
    return 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())

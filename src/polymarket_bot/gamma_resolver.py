"""Gamma-truth resolver — single source of truth for Polymarket-resolved windows.

Used by:
  * scripts/resolve_decisions.py (CLI for back-fill of legacy decisions)
  * src/polymarket_bot/_paper/runner.py (instant-settle path; design at
    design/instant_settlement.md)
  * src/polymarket_bot/dashboard/gamma_resolver.py (re-export shim for
    the dashboard, kept for backward compat with the dashboard branch)

Top-level module (no layer membership) so the import-linter contracts
permit both the dashboard and the live runtime to consume it. See
.importlinter for the contracts.

Pure module: I/O is via the caller-supplied ``httpx.Client`` and the
caller-supplied src/dst paths. No module-level state.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Literal

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
TIMEOUT_S = 15.0
USER_AGENT = "polymarket-bot/gamma_resolver"

SIM_FILL_BUG_THRESHOLD_USD = 0.05


def gamma_resolution(window_ts: int, *, client: httpx.Client) -> Literal["UP", "DOWN"] | None:
    """Return 'UP' | 'DOWN' | None for the BTC 5m updown market at this window_ts.

    None means the market either doesn't exist on Gamma or hasn't resolved
    yet (e.g., still open or pending UMA settlement). Synchronous; the
    caller is responsible for wrapping in asyncio.to_thread when invoked
    from an async context.
    """
    slug = f"btc-updown-5m-{window_ts}"
    try:
        r = client.get(
            f"{GAMMA_BASE}/events",
            params={"slug": slug},
            timeout=TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.HTTPError as e:
        print(f"  gamma fetch fail for {slug}: {e}", file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"  gamma {r.status_code} for {slug}", file=sys.stderr)
        return None
    data = r.json()
    if not data:
        return None
    ev = data[0] if isinstance(data, list) else data
    markets = ev.get("markets") or []
    if not markets:
        return None
    m = markets[0]
    if not m.get("closed"):
        return None
    outcomes = m.get("outcomes") or []
    prices = m.get("outcomePrices") or []
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except (json.JSONDecodeError, TypeError):
            return None
    if len(outcomes) != len(prices) or not outcomes:
        return None
    for label, price in zip(outcomes, prices, strict=False):
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p >= 0.999:
            label_norm = str(label).strip().lower()
            if label_norm == "up":
                return "UP"
            if label_norm == "down":
                return "DOWN"
    return None


def realised_pnl(
    *,
    side: str,
    resolution: str,
    fill: dict[str, Any],
    price_limit: float | None = None,
) -> tuple[float, float, bool]:
    """Mirrors backtest.fills.realised_pnl_usd. shares*price - fees + payout.

    Returns (pnl, effective_fill_price, was_corrected). If the fill was
    logged at a price more than 5 cents below limit (the pre-2026-05-09
    sim-fill bug), recompute PnL using ``price_limit`` as the fill price
    -- the conservative correct value.
    """
    size_filled = float(fill["size_filled"])
    price_filled = float(fill["price_filled"])
    fee = float(fill.get("fee_usd") or 0.0)
    was_corrected = False
    if price_limit is not None and price_filled < price_limit - SIM_FILL_BUG_THRESHOLD_USD:
        usd_stake = size_filled * price_filled
        price_filled = price_limit
        size_filled = usd_stake / price_filled
        was_corrected = True
    cost = size_filled * price_filled
    payout = size_filled if side == resolution else 0.0
    pnl = payout - cost - fee
    return (pnl, price_filled, was_corrected)


def re_resolve_file(
    src: Path, *, client: httpx.Client, dst: Path | None = None
) -> tuple[int, int, int]:
    """Returns (n_settled, n_changed, n_unresolvable).

    Reads from ``src``. Writes to ``dst`` (atomic via tmp+rename). If
    ``dst`` is None, rewrites ``src`` in place (legacy behavior; the CLI
    refuses this -- only library callers may pass None).

    Records that already have ``resolution_source: "polymarket"`` are
    skipped unless they still need a fill correction. Idempotent.
    """
    target = dst if dst is not None else src
    lines = src.read_text(encoding="utf-8").splitlines()
    by_id_side: dict[str, str] = {}
    by_id_window: dict[str, int] = {}
    by_id_limit: dict[str, float] = {}
    n_settled = 0
    n_changed = 0
    n_unresolvable = 0

    for raw in lines:
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if rec.get("kind") == "fired":
            decision_id = rec.get("decision_id")
            side = rec.get("side")
            window_ts = rec.get("window_ts")
            price_limit = rec.get("price_limit")
            if isinstance(decision_id, str) and side in ("UP", "DOWN"):
                by_id_side[decision_id] = side
            if isinstance(decision_id, str) and isinstance(window_ts, int):
                by_id_window[decision_id] = window_ts
            if isinstance(decision_id, str) and isinstance(price_limit, int | float):
                by_id_limit[decision_id] = float(price_limit)

    out: list[str] = []
    for raw in lines:
        if not raw.strip():
            out.append(raw)
            continue
        rec = json.loads(raw)
        if rec.get("kind") != "settled":
            out.append(raw)
            continue
        n_settled += 1
        already_corrected = bool(rec.get("fill_correction"))
        already_resolved = rec.get("resolution_source") == "polymarket"
        fill = rec.get("fill_at_settle")

        if already_resolved and (already_corrected or not isinstance(fill, dict)):
            out.append(raw)
            continue

        decision_id = rec.get("decision_id")
        truth: str | None = None

        if already_resolved:
            r = rec.get("resolution")
            if r in ("UP", "DOWN"):
                truth = r
        else:
            window_ts = rec.get("window_ts") or by_id_window.get(decision_id) or 0
            if not isinstance(window_ts, int) or window_ts <= 0:
                n_unresolvable += 1
                out.append(raw)
                continue
            truth = gamma_resolution(window_ts, client=client)
            if truth is None:
                n_unresolvable += 1
                out.append(raw)
                continue
            old_resolution = rec.get("resolution")
            rec["resolution"] = truth
            rec["resolution_source"] = "polymarket"
            if old_resolution is not None:
                rec["resolution_oracle_local"] = old_resolution

        if truth is None:
            out.append(raw)
            continue

        side = by_id_side.get(decision_id or "")
        old_pnl = rec.get("pnl_usd")
        if isinstance(fill, dict) and side in ("UP", "DOWN"):
            price_limit = by_id_limit.get(decision_id or "")
            new_pnl, eff_fill_price, was_corrected = realised_pnl(
                side=side, resolution=truth, fill=fill, price_limit=price_limit
            )
            rec["pnl_usd"] = new_pnl
            if was_corrected:
                rec["fill_correction"] = {
                    "logged_price_filled": float(fill["price_filled"]),
                    "corrected_price_filled": eff_fill_price,
                    "reason": "pre-fix simulator gave price improvement on maker fill",
                }
            if old_pnl != new_pnl:
                n_changed += 1
        else:
            old_resolution = rec.get("resolution_oracle_local") or rec.get("resolution")
            if old_resolution != truth:
                n_changed += 1

        out.append(json.dumps(rec, separators=(",", ":")))

    write_target = dst is not None or n_changed > 0
    if write_target:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.rename(target)

    return (n_settled, n_changed, n_unresolvable)


def re_resolve_dir(src_dir: Path, dst_dir: Path, *, client: httpx.Client) -> tuple[int, int, int]:
    """Resolve every *.jsonl under ``src_dir``, writing to ``dst_dir``.

    Returns the cumulative (n_settled, n_changed, n_unresolvable). Refuses
    src_dir == dst_dir (orphan-FD-decisions defense). Skips .bak / .tmp.
    """
    src_resolved = src_dir.resolve()
    if dst_dir.exists() and src_resolved == dst_dir.resolve():
        raise ValueError(f"refusing in-place rewrite: src and dst resolve to {src_resolved}")
    dst_dir.mkdir(parents=True, exist_ok=True)

    total_settled = 0
    total_changed = 0
    total_unresolvable = 0
    for p in sorted(src_dir.glob("*.jsonl")):
        if p.name.endswith(".bak") or p.name.endswith(".tmp"):
            continue
        target = dst_dir / p.name
        n_settled, n_changed, n_unresolvable = re_resolve_file(p, client=client, dst=target)
        total_settled += n_settled
        total_changed += n_changed
        total_unresolvable += n_unresolvable
    return (total_settled, total_changed, total_unresolvable)


def poll_gamma_for_resolution(
    window_ts: int,
    *,
    client: httpx.Client,
    timeout_s: float = 30.0,
    interval_s: float = 1.0,
    sleep_fn: Any = None,
    monotonic_fn: Any = None,
) -> Literal["UP", "DOWN"] | None:
    """Poll Gamma every ``interval_s`` seconds for up to ``timeout_s`` seconds.

    Returns the resolution as soon as Gamma reports it, or None on timeout.
    Sync (blocks the calling thread). The runner wraps this in
    ``asyncio.to_thread`` so the event loop keeps running while we poll.

    ``sleep_fn`` and ``monotonic_fn`` are injected for deterministic tests.
    Default to ``time.sleep`` / ``time.monotonic``.
    """
    sleep = sleep_fn if sleep_fn is not None else time.sleep
    monotonic = monotonic_fn if monotonic_fn is not None else time.monotonic
    deadline = monotonic() + timeout_s
    while monotonic() < deadline:
        truth = gamma_resolution(window_ts, client=client)
        if truth is not None:
            return truth
        sleep(interval_s)
    return None

"""Post-hoc re-resolve settled decisions against Polymarket Gamma — the truth.

Why this exists:
  Our local PaperRunner settles via Chainlink AnswerUpdated events on
  Polygon. That feed is push-based (1-2 min heartbeat), so the
  open_oracle/close_oracle we capture at window boundaries can be off by
  up to ~90s vs the exact T / T+300 reads that Polymarket uses. We've
  confirmed at least one window (1778275800) where we said UP and
  Polymarket actually resolved DOWN.

  Until we wire Chainlink Streams (the pull-based, sub-second feed
  Polymarket itself uses), the dashboard reads the wrong PnL on those
  windows. This script reads each settled record, queries Gamma for the
  market's authoritative resolution, and rewrites the JSONL line with
  corrected `resolution` and `pnl_usd`.

Usage:
    # In-place rewrite (legacy, single arg):
    uv run python scripts/resolve_decisions.py state/staging/decisions/

    # Two-arg mode: read from SRC, write to DST atomically. Used by
    # sync_staging.sh so the dashboard never reads a half-resolved view.
    uv run python scripts/resolve_decisions.py SRC_DIR DST_DIR

  Records that already have a Gamma resolution recorded under
  ``resolution_source: "polymarket"`` are skipped. Idempotent. Safe to
  call repeatedly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
TIMEOUT_S = 15.0
USER_AGENT = "polymarket-bot/resolve_decisions"


def gamma_resolution(window_ts: int, *, client: httpx.Client) -> str | None:
    """Return 'UP' | 'DOWN' | None for the market at this window_ts.

    None means the market either doesn't exist on Gamma or hasn't resolved
    yet (e.g., still open or pending UMA settlement).
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
    # Find the winning outcome (price==1 or near-1).
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


SIM_FILL_BUG_THRESHOLD_USD = 0.05


def realised_pnl(
    *,
    side: str,
    resolution: str,
    fill: dict[str, Any],
    price_limit: float | None = None,
) -> tuple[float, float, bool]:
    """Mirrors backtest.fills.realised_pnl_usd. shares*price - fees + payout.

    Returns (pnl, effective_fill_price, was_corrected).

    Pre-2026-05-09 the FillSimulator's pending-fill path could produce a
    fill at a price MUCH lower than the decision's limit (the price-
    improvement-to-the-buyer bug; see fills.py docstring). On a real CLOB
    the maker-style match would have happened at the limit price. If we
    detect such a logged fill (`price_filled < price_limit - 5¢`), we
    treat it as a phantom and recompute PnL using ``price_limit`` as the
    fill price — the conservative correct value.
    """
    size_filled = float(fill["size_filled"])
    price_filled = float(fill["price_filled"])
    fee = float(fill.get("fee_usd") or 0.0)
    was_corrected = False
    if price_limit is not None and price_filled < price_limit - SIM_FILL_BUG_THRESHOLD_USD:
        # Recompute size as it would have been at the limit price (since
        # `size_filled = size_usd / fill_price`), keeping the original
        # USD stake constant.
        usd_stake = size_filled * price_filled  # original notional cost
        # Stake assumed to be the original $5 (or whatever the strategy
        # set); back-derive from the bug-fill: cost = size_filled *
        # price_filled. At the corrected price, cost stays the same; the
        # number of shares is fewer.
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
    ``dst`` is None, rewrites ``src`` in place (legacy behavior).
    """
    target = dst if dst is not None else src
    lines = src.read_text(encoding="utf-8").splitlines()
    by_id_side: dict[str, str] = {}
    by_id_window: dict[str, int] = {}
    n_settled = 0
    n_changed = 0
    n_unresolvable = 0

    by_id_limit: dict[str, float] = {}

    # First pass: collect side+window+price_limit from fired records.
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

    # Second pass: rewrite settled records with Gamma resolution.
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

        # Skip records that are fully processed (resolution corrected AND
        # fill-correction step already done OR no fill to correct).
        if already_resolved and (already_corrected or not isinstance(fill, dict)):
            out.append(raw)
            continue

        decision_id = rec.get("decision_id")
        truth: str | None = None

        if already_resolved:
            # Resolution is already truth; just need to apply the fill
            # correction. No Gamma round-trip needed.
            r = rec.get("resolution")
            if r in ("UP", "DOWN"):
                truth = r
        else:
            # Look up resolution from Gamma.
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

        # Recompute pnl_usd if there's a fill we can score.
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
                marker = " [SIM-FILL-BUG]" if was_corrected else ""
                window_ts_disp = rec.get("window_ts") or "?"
                old_resolution_disp = rec.get("resolution_oracle_local") or rec.get("resolution")
                print(
                    f"  window {window_ts_disp}: side={side} "
                    f"oracle-said={old_resolution_disp} polymarket={truth}  "
                    f"pnl {old_pnl:+.2f} → {new_pnl:+.2f}{marker}"
                )
        else:
            # No fill (or no side) — resolution still gets corrected; PnL stays
            # at whatever the original was (likely 0.0 for unfilled trades).
            if old_resolution != truth:
                n_changed += 1
                print(
                    f"  window {window_ts}: oracle-said={old_resolution} "
                    f"polymarket={truth}  (no fill — PnL unchanged)"
                )

        out.append(json.dumps(rec, separators=(",", ":")))

    # Always write the destination (even on no-changes runs) when in two-arg
    # mode, so the dashboard read path is freshly populated. In-place mode
    # only writes when something changed (legacy behavior).
    write_target = dst is not None or n_changed > 0
    if write_target:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write via tmp + rename — dashboard never reads a partial file.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.rename(target)

    return (n_settled, n_changed, n_unresolvable)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "src_dir",
        type=Path,
        help="Source decisions/ directory containing *.jsonl files.",
    )
    parser.add_argument(
        "dst_dir",
        type=Path,
        nargs="?",
        default=None,
        help="Optional destination dir. Omit for in-place rewrite (legacy mode).",
    )
    args = parser.parse_args()
    src: Path = args.src_dir
    dst: Path | None = args.dst_dir
    if not src.is_dir():
        print(f"not a directory: {src}", file=sys.stderr)
        return 2
    if dst is not None:
        dst.mkdir(parents=True, exist_ok=True)

    paths = sorted(src.glob("*.jsonl"))
    if not paths:
        print("no .jsonl files found")
        return 0

    total_settled = 0
    total_changed = 0
    total_unresolvable = 0
    with httpx.Client() as client:
        for p in paths:
            print(f"== {p.name} ==")
            target = (dst / p.name) if dst is not None else None
            n_settled, n_changed, n_unresolvable = re_resolve_file(p, client=client, dst=target)
            print(f"   settled={n_settled} changed={n_changed} unresolvable={n_unresolvable}")
            total_settled += n_settled
            total_changed += n_changed
            total_unresolvable += n_unresolvable

    print()
    print(
        f"TOTAL settled={total_settled} changed={total_changed} "
        f"unresolvable={total_unresolvable}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

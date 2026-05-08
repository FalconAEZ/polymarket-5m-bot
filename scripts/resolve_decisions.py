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
    uv run python scripts/resolve_decisions.py state/staging/decisions/

  It rewrites the *.jsonl files in-place. The original is preserved at
  *.jsonl.bak the first time it runs; subsequent runs skip the backup.

Idempotent. Safe to call repeatedly. Records that already have a Gamma
resolution recorded under the new ``resolution_source: "polymarket"``
field are skipped.
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


def realised_pnl(*, side: str, resolution: str, fill: dict[str, Any]) -> float:
    """Mirrors backtest.fills.realised_pnl_usd. shares*price - fees + payout."""
    size_filled = float(fill["size_filled"])
    price_filled = float(fill["price_filled"])
    fee = float(fill.get("fee_usd") or 0.0)
    cost = size_filled * price_filled
    payout = size_filled if side == resolution else 0.0
    return payout - cost - fee


def re_resolve_file(path: Path, *, client: httpx.Client) -> tuple[int, int, int]:
    """Returns (n_settled, n_changed, n_unresolvable)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    by_id_side: dict[str, str] = {}
    by_id_window: dict[str, int] = {}
    n_settled = 0
    n_changed = 0
    n_unresolvable = 0

    # First pass: collect side+window from fired records.
    for raw in lines:
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if rec.get("kind") == "fired":
            decision_id = rec.get("decision_id")
            side = rec.get("side")
            window_ts = rec.get("window_ts")
            if isinstance(decision_id, str) and side in ("UP", "DOWN"):
                by_id_side[decision_id] = side
            if isinstance(decision_id, str) and isinstance(window_ts, int):
                by_id_window[decision_id] = window_ts

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
        # Already re-resolved on a prior run?
        if rec.get("resolution_source") == "polymarket":
            out.append(raw)
            continue

        decision_id = rec.get("decision_id")
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

        # Recompute pnl_usd if there's a fill we can score.
        fill = rec.get("fill_at_settle")
        side = by_id_side.get(decision_id or "")
        old_pnl = rec.get("pnl_usd")
        if isinstance(fill, dict) and side in ("UP", "DOWN"):
            new_pnl = realised_pnl(side=side, resolution=truth, fill=fill)
            rec["pnl_usd"] = new_pnl
            if old_pnl != new_pnl:
                n_changed += 1
                print(
                    f"  window {window_ts}: side={side} oracle-said={old_resolution} "
                    f"polymarket={truth}  pnl {old_pnl:+.2f} → {new_pnl:+.2f}"
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

    if n_changed > 0 or any('"resolution_source":"polymarket"' in line for line in out):
        # Backup once if not already backed up.
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            bak.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")

    return (n_settled, n_changed, n_unresolvable)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "decisions_dir",
        type=Path,
        help="Path to a decisions/ directory containing *.jsonl files.",
    )
    args = parser.parse_args()
    if not args.decisions_dir.is_dir():
        print(f"not a directory: {args.decisions_dir}", file=sys.stderr)
        return 2

    paths = sorted(args.decisions_dir.glob("*.jsonl"))
    if not paths:
        print("no .jsonl files found")
        return 0

    total_settled = 0
    total_changed = 0
    total_unresolvable = 0
    with httpx.Client() as client:
        for p in paths:
            print(f"== {p.name} ==")
            n_settled, n_changed, n_unresolvable = re_resolve_file(p, client=client)
            print(f"   settled={n_settled} changed={n_changed} " f"unresolvable={n_unresolvable}")
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

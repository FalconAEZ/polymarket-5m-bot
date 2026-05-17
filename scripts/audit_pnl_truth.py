"""Phase 15.5 Item 1 — PnL truth pass.

Classifies every ``settled`` record in ``state/decisions/*.jsonl`` by the
source of its realised PnL, so the gap between the raw ``sum(pnl_usd)``
(≈ +$2.5k) and the dashboard's reconciled total (~+$22) can be attributed
to a known class.

Classes (decreasing priority — first match wins):

  corrected_by_settled_correction
        A later ``settled_correction`` record overrides the original
        ``settled`` PnL.  Original resolution disagreed with Polymarket
        post-hoc (the May 9 Chainlink-vs-Polymarket class).
  phantom_taker_floor_price
        Taker fill at ``price_filled < 0.06`` AND ``ask_size_top is None``
        at fire time (Phase 11.A phantom-fill signature).
  phantom_taker_no_size_attested
        Taker fill but ``snapshot.ask_size_top`` was ``None`` at fire time
        and ``price_filled < price_limit`` (filled below the limit at a
        depth we never confirmed existed).
  reconciliation_mismatch
        Reported ``pnl_usd`` does not match recomputed PnL from
        (side, resolution, fill_price, size, fee).
  no_fill
        Neither ``fired.fill`` nor ``settled.fill_at_settle`` is set;
        PnL is 0.  Tracked for completeness.
  real_taker_fill
        ``fired.fill`` is set, no phantom flag, PnL recomputes.
  real_maker_fill_at_settle
        ``settled.fill_at_settle`` is set (post-TTL maker fill),
        no phantom flag, PnL recomputes.

Output: per-class ``n``, ``sum_pnl``, ``sum_pnl_corrected`` (if a class
has corrections applied), and top-3 example decision_ids by absolute PnL.

Reconciliation: prints the reduction chain
``raw_total → minus(corrected_delta) → minus(phantom) → "truth"`` so the
gap is fully attributed.
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

DECISIONS_DIR = pathlib.Path("state/decisions")
PHANTOM_PRICE_FLOOR = 0.06
FEE_PER_FILL = 0.001  # observed flat fee on fill records


@dataclass
class Decision:
    decision_id: str
    fired: dict[str, Any] | None = None
    settled: dict[str, Any] | None = None
    corrections: list[dict[str, Any]] = field(default_factory=list)


def load_all() -> dict[str, Decision]:
    by_id: dict[str, Decision] = {}
    for fp in sorted(DECISIONS_DIR.glob("2026-05-*.jsonl")):
        for ln in fp.open():
            r = json.loads(ln.strip())
            did = r["decision_id"]
            d = by_id.setdefault(did, Decision(decision_id=did))
            kind = r["kind"]
            if kind == "fired":
                d.fired = r
            elif kind == "settled":
                d.settled = r
            elif kind == "settled_correction":
                d.corrections.append(r)
    return by_id


def effective_pnl(d: Decision) -> float:
    """PnL after all corrections (last-write-wins)."""
    if d.corrections:
        d.corrections.sort(key=lambda r: r["corrected_ts_ns"])
        return float(d.corrections[-1]["corrected_pnl_usd"])
    if d.settled is None:
        return 0.0
    return float(d.settled.get("pnl_usd") or 0.0)


def original_pnl(d: Decision) -> float:
    if d.settled is None:
        return 0.0
    return float(d.settled.get("pnl_usd") or 0.0)


def fill_record(d: Decision) -> dict[str, Any] | None:
    if d.fired and d.fired.get("fill"):
        return d.fired["fill"]
    if d.settled and d.settled.get("fill_at_settle"):
        return d.settled["fill_at_settle"]
    if d.corrections and d.corrections[-1].get("fill_at_settle"):
        return d.corrections[-1]["fill_at_settle"]
    return None


def recompute_pnl(d: Decision) -> float | None:
    """Recompute PnL from (side, resolution, fill_price, size, fee).

    PnL on a binary outcome share:
        win  = size_filled * (1 - price_filled) - fee
        loss = -size_filled * price_filled - fee   (we paid price, got 0)

    "side" = UP means we bought the UP token; resolution = UP means we win.
    For settled_correction records the corrected_resolution is authoritative.
    """
    fill = fill_record(d)
    if fill is None:
        return 0.0
    if d.fired is None:
        return None
    side = d.fired.get("side")
    resolution = None
    if d.corrections:
        resolution = d.corrections[-1]["corrected_resolution"]
    elif d.settled:
        resolution = d.settled.get("resolution")
    if resolution is None:
        return None
    price = float(fill["price_filled"])
    size = float(fill["size_filled"])
    fee = float(fill.get("fee_usd") or FEE_PER_FILL)
    win = side == resolution
    if win:
        return size * (1.0 - price) - fee
    return -size * price - fee


def classify(d: Decision) -> str:
    if d.corrections:
        return "corrected_by_settled_correction"
    fill = fill_record(d)
    if fill is None:
        return "no_fill"
    price = float(fill["price_filled"])
    fired = d.fired or {}
    snap = fired.get("snapshot") or {}
    ask_size_top = snap.get("ask_size_top")
    price_limit = fired.get("price_limit")
    is_taker = bool(fired.get("fill"))
    if is_taker and price < PHANTOM_PRICE_FLOOR and ask_size_top is None:
        return "phantom_taker_floor_price"
    if (
        is_taker
        and ask_size_top is None
        and price_limit is not None
        and price < float(price_limit) - 1e-6
    ):
        return "phantom_taker_no_size_attested"
    recomputed = recompute_pnl(d)
    reported = effective_pnl(d)
    if recomputed is not None and abs(recomputed - reported) > 0.01:
        return "reconciliation_mismatch"
    return "real_taker_fill" if is_taker else "real_maker_fill_at_settle"


def main() -> None:
    by_id = load_all()
    settled = [d for d in by_id.values() if d.settled is not None]
    print(f"loaded {len(by_id)} decision_ids ({len(settled)} settled)")
    print()

    by_class: dict[str, list[Decision]] = defaultdict(list)
    for d in settled:
        by_class[classify(d)].append(d)

    raw_total = sum(original_pnl(d) for d in settled)
    corrected_total = sum(effective_pnl(d) for d in settled)
    correction_delta = corrected_total - raw_total

    print("=== PER-CLASS BREAKDOWN ===")
    fmt = "  {cls:38s} n={n:4d}  raw=${raw:+10.2f}  effective=${eff:+10.2f}"
    rows: list[tuple[str, int, float, float, list[Decision]]] = []
    for cls, group in by_class.items():
        n = len(group)
        raw_sum = sum(original_pnl(d) for d in group)
        eff_sum = sum(effective_pnl(d) for d in group)
        rows.append((cls, n, raw_sum, eff_sum, group))
    rows.sort(key=lambda r: -abs(r[2]))
    for cls, n, raw_sum, eff_sum, _g in rows:
        print(fmt.format(cls=cls, n=n, raw=raw_sum, eff=eff_sum))
    print()

    print("=== TOP-3 BY |PnL| PER CLASS (decision_id, side, fill_price, eff_pnl, raw_pnl) ===")
    for cls, _n, _r, _e, group in rows:
        group.sort(key=lambda d: -abs(original_pnl(d)))
        print(f"  -- {cls} --")
        for d in group[:3]:
            fill = fill_record(d) or {}
            side = (d.fired or {}).get("side", "?")
            ask = ((d.fired or {}).get("snapshot") or {}).get("ask_size_top")
            print(
                f"    id={d.decision_id[:8]}  side={side}  price={fill.get('price_filled')!s:>6}  "
                f"size={fill.get('size_filled')!s:>10.10}  ask_size_top={ask}  "
                f"eff=${effective_pnl(d):+8.2f}  raw=${original_pnl(d):+8.2f}"
            )
    print()

    print("=== RECONCILIATION CHAIN ===")
    print(f"  RAW sum(settled.pnl_usd)                    = ${raw_total:+10.2f}")
    print(f"  + correction delta (settled_correction)     = ${correction_delta:+10.2f}")
    print("  ----------------------------------------------")
    print(f"  = corrected sum                             = ${corrected_total:+10.2f}")
    phantom_classes = (
        "phantom_taker_floor_price",
        "phantom_taker_no_size_attested",
    )
    phantom_eff = sum(
        effective_pnl(d) for cls, _n, _r, _e, group in rows for d in group if cls in phantom_classes
    )
    phantom_raw = sum(
        original_pnl(d) for cls, _n, _r, _e, group in rows for d in group if cls in phantom_classes
    )
    print(f"  - phantom_taker (effective)                 = ${phantom_eff:+10.2f}")
    print(f"  - phantom_taker (raw, for ref)              = ${phantom_raw:+10.2f}")
    print("  ----------------------------------------------")
    print(
        f"  = TRUE PnL (corrected, phantom-free)        = ${corrected_total - phantom_eff:+10.2f}"
    )
    print()

    # Detect repeat corrections — a correction-of-a-correction.
    multi = [d for d in settled if len(d.corrections) > 1]
    if multi:
        print(f"=== {len(multi)} decision_ids with >1 correction (correction-of-correction) ===")
        for d in multi[:5]:
            trail = ", ".join(f"{c['corrected_pnl_usd']:+.2f}" for c in d.corrections)
            print(
                f"  id={d.decision_id[:8]}  n_corrections={len(d.corrections)}  " f"trail=[{trail}]"
            )
        print()


if __name__ == "__main__":
    main()

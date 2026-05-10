"""Phase 13 audit — bucket never-filled fires by ask-gap and report counterfactual WR.

V2 successor to the VPS-local /tmp/audit_unfilled.py. Reads one or more
state/decisions/<UTC-date>.jsonl files, joins fired ↔ settled records by
decision_id, and classifies each fired record into one of:

    filled_at_fire      — taker fill at fire-time (fired.fill is set)
    filled_at_settle    — maker fill at settle-time (settled.fill_at_settle is set)
    never_filled        — neither path filled; bucket by (best_ask - price_limit)
    no_settle           — fired but no settled record present (pending or lost)

For never_filled records, the gap = best_ask - price_limit is bucketed
into 0-1¢ / 1-2¢ / 2-5¢ / >5¢ / floor_guard (price_limit >= best_ask but
no fill, typically depth=None at the floor) / OTHER. For each bucket we
compute the COUNTERFACTUAL win rate = "would we have won if we'd filled
at best_ask?" — defined as resolution == fired.side, joined from the
settled record. Output is a per-day and aggregate Markdown table that
informs Phase 13's `SPOT_AWARE_LIMIT_LIFT_BPS` decision per the locked
master plan §4 (lift only when the bucket's counterfactual W ≥ 50%).

Usage:
    python scripts/audit_unfilled_v2.py state/decisions/2026-05-10.jsonl
    python scripts/audit_unfilled_v2.py state/decisions/*.jsonl
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Gap bucket edges in dollars (price_limit < best_ask side).
# Bucket name -> (lower-exclusive, upper-inclusive) gap in dollars.
GAP_BUCKETS: list[tuple[str, float, float]] = [
    ("0-1c", 0.0, 0.01),
    ("1-2c", 0.01, 0.02),
    ("2-5c", 0.02, 0.05),
    (">5c", 0.05, math.inf),
]


@dataclass
class BucketStat:
    """Aggregate counters for one (outcome, gap-bucket) cell."""

    n: int = 0
    n_with_resolution: int = 0
    n_would_win: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)

    def wr_pct(self) -> float | None:
        if self.n_with_resolution == 0:
            return None
        return 100.0 * self.n_would_win / self.n_with_resolution

    def wilson95(self) -> tuple[float, float] | None:
        """Two-sided 95% Wilson CI on counterfactual W rate."""
        n = self.n_with_resolution
        if n == 0:
            return None
        p = self.n_would_win / n
        z = 1.96
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return (max(0.0, center - half) * 100.0, min(1.0, center + half) * 100.0)


def classify_fired(
    fired_rec: dict[str, Any],
    settled_rec: dict[str, Any] | None,
) -> tuple[str, str | None, float | None]:
    """Return (outcome, gap_bucket_or_None, gap_cents_or_None)."""
    fill = fired_rec.get("fill")
    if fill is not None:
        return ("filled_at_fire", None, None)

    if settled_rec is None:
        return ("no_settle", None, None)

    if settled_rec.get("fill_at_settle") is not None:
        return ("filled_at_settle", None, None)

    # never_filled — bucket by gap.
    snap = fired_rec.get("snapshot") or {}
    price_limit = fired_rec.get("price_limit")
    best_ask = snap.get("best_ask")
    if price_limit is None or best_ask is None:
        return ("never_filled", "missing_book", None)

    gap = best_ask - price_limit
    if gap <= 0:
        # price_limit >= best_ask but didn't fill — usually floor-guard refusal
        # at ask <= floor, or depth=None safety guard. Distinguish floor vs OTHER.
        ask_size = snap.get("ask_size_top")
        if best_ask <= 0.05 and ask_size is None:
            return ("never_filled", "floor_guard", round(gap * 100, 2))
        return ("never_filled", "OTHER", round(gap * 100, 2))

    for name, lo, hi in GAP_BUCKETS:
        if lo < gap <= hi:
            return ("never_filled", name, round(gap * 100, 2))
    return ("never_filled", "OTHER", round(gap * 100, 2))


def would_have_won(
    fired_rec: dict[str, Any],
    settled_rec: dict[str, Any] | None,
) -> bool | None:
    """Counterfactual: would the trade have won at best_ask?"""
    if settled_rec is None:
        return None
    resolution = settled_rec.get("resolution")
    if not resolution:
        return None
    side = fired_rec.get("side")
    if not side:
        return None
    return bool(resolution == side)


def load_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (fired_by_did, settled_by_did)."""
    fired: dict[str, dict[str, Any]] = {}
    settled: dict[str, dict[str, Any]] = {}
    for line in path.open():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        did = r.get("decision_id")
        if not did:
            continue
        kind = r.get("kind")
        if kind == "fired":
            fired[did] = r
        elif kind == "settled":
            settled[did] = r
        elif kind == "settled_correction":
            # Correction merged into settled — overlay corrected pnl + resolution.
            base = settled.setdefault(did, {})
            base.update({k: v for k, v in r.items() if k != "kind"})
    return fired, settled


def audit_one_day(path: Path) -> dict[str, Any]:
    """Run the audit for a single day. Returns the structured result."""
    fired, settled = load_jsonl(path)

    outcomes: Counter[str] = Counter()
    buckets: dict[str, BucketStat] = defaultdict(BucketStat)

    for did, fr in fired.items():
        sr = settled.get(did)
        outcome, bucket, gap_cents = classify_fired(fr, sr)
        outcomes[outcome] += 1
        if outcome != "never_filled" or bucket is None:
            continue
        b = buckets[bucket]
        b.n += 1
        won = would_have_won(fr, sr)
        if won is not None:
            b.n_with_resolution += 1
            if won:
                b.n_would_win += 1
        if len(b.examples) < 5:
            snap = fr.get("snapshot") or {}
            b.examples.append(
                {
                    "decision_id": did,
                    "window_ts": fr.get("window_ts"),
                    "side": fr.get("side"),
                    "price_limit": fr.get("price_limit"),
                    "best_ask": snap.get("best_ask"),
                    "best_bid": snap.get("best_bid"),
                    "gap_cents": gap_cents,
                    "resolution": sr.get("resolution") if sr else None,
                    "would_win": won,
                    "rationale": (fr.get("rationale") or "")[:80],
                }
            )

    return {
        "path": str(path),
        "n_fired": len(fired),
        "outcomes": dict(outcomes),
        "buckets": buckets,
    }


def merge_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum per-day results into one aggregate."""
    agg_outcomes: Counter[str] = Counter()
    agg_buckets: dict[str, BucketStat] = defaultdict(BucketStat)
    n_fired_total = 0

    for r in results:
        n_fired_total += r["n_fired"]
        for k, v in r["outcomes"].items():
            agg_outcomes[k] += v
        for name, bs in r["buckets"].items():
            tgt = agg_buckets[name]
            tgt.n += bs.n
            tgt.n_with_resolution += bs.n_with_resolution
            tgt.n_would_win += bs.n_would_win
            for ex in bs.examples:
                if len(tgt.examples) < 10:
                    tgt.examples.append(ex)

    return {
        "n_fired": n_fired_total,
        "outcomes": dict(agg_outcomes),
        "buckets": agg_buckets,
    }


def print_outcome_summary(label: str, n_fired: int, outcomes: dict[str, int]) -> None:
    print(f"\n## {label}")
    print(f"  total fired:        {n_fired}")
    if n_fired == 0:
        return
    for k in ("filled_at_fire", "filled_at_settle", "never_filled", "no_settle"):
        v = outcomes.get(k, 0)
        pct = 100.0 * v / n_fired
        print(f"  {k:<20s} {v:>5d}  ({pct:5.1f}%)")
    n_filled = outcomes.get("filled_at_fire", 0) + outcomes.get("filled_at_settle", 0)
    print(f"  FILL RATE:          {100.0 * n_filled / n_fired:.1f}%")


def print_bucket_table(buckets: dict[str, BucketStat]) -> None:
    """Print the gap-bucket counterfactual-WR table."""
    print("\n### never_filled bucket counterfactual WR")
    print("")
    print(
        "| bucket       |     n | n_resolved | counterfactual_W | 95% CI         | examples (gap¢ side res) |"
    )
    print(
        "|--------------|-------|------------|------------------|----------------|--------------------------|"
    )

    bucket_order = ["0-1c", "1-2c", "2-5c", ">5c", "floor_guard", "OTHER", "missing_book"]
    for name in bucket_order:
        bs = buckets.get(name)
        if bs is None or bs.n == 0:
            continue
        wr = bs.wr_pct()
        ci = bs.wilson95()
        wr_str = f"{wr:5.1f}%" if wr is not None else "  n/a "
        ci_str = f"[{ci[0]:5.1f}, {ci[1]:5.1f}]" if ci is not None else "       n/a       "
        ex_strs = []
        for ex in bs.examples[:3]:
            gap = ex.get("gap_cents")
            side = ex.get("side")
            res = ex.get("resolution") or "?"
            ex_strs.append(f"{gap}¢ {side}->{res}")
        ex_str = ", ".join(ex_strs)
        print(
            f"| {name:<12s} | {bs.n:>5d} | {bs.n_with_resolution:>10d} | {wr_str:>16s} | {ci_str:<14s} | {ex_str} |"
        )


def main(paths: list[Path]) -> int:
    if not paths:
        print(
            "usage: python scripts/audit_unfilled_v2.py state/decisions/<date>.jsonl [...]",
            file=sys.stderr,
        )
        return 2

    per_day: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            print(f"WARN: missing {p}", file=sys.stderr)
            continue
        r = audit_one_day(p)
        per_day.append(r)
        print_outcome_summary(p.name, r["n_fired"], r["outcomes"])
        print_bucket_table(r["buckets"])

    if len(per_day) > 1:
        agg = merge_results(per_day)
        print_outcome_summary(f"AGGREGATE ({len(per_day)} days)", agg["n_fired"], agg["outcomes"])
        print_bucket_table(agg["buckets"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main([Path(a) for a in sys.argv[1:]]))

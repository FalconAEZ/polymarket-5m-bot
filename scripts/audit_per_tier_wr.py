"""Phase 14 audit — per-tier WR breakdown to inform TIER_GATE_BLOCKLIST.

Reads one or more state/decisions/<UTC-date>.jsonl files and stratifies
all settled trades by entry-price tier using the IDENTICAL bucket
definition as `src.polymarket_bot.dashboard.loaders.PRICE_TIER_BUCKETS`:

    <15%, 15-30%, 30-50%, 50-70%, 70-85%, 85-100%

Each bucket reports n_fired / n_filled / n_settled / n_won / WR / PnL,
plus a 95% Wilson CI on WR. Per master plan §4 → Phase 14 gate:
flag any tier with WR <50% on n_settled ≥ 30 for blocklisting.

Note on `fill_price`: a settled record has the actual fill price if it
filled via taker (fired.fill.price) OR maker (fill_at_settle.price_filled).
This script joins fired ↔ settled and considers either path as 'filled'.

Usage:
    python scripts/audit_per_tier_wr.py state/decisions/*.jsonl
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Mirror src/polymarket_bot/dashboard/loaders.py:341 exactly.
PRICE_TIER_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
)


def tier_label(price: float | None) -> str:
    if price is None:
        return "—"
    for lo, hi, label in PRICE_TIER_BUCKETS:
        if lo <= price < hi:
            return label
    return "—"


@dataclass
class TierAgg:
    n_fired: int = 0
    n_filled: int = 0
    n_settled: int = 0
    n_won: int = 0
    pnl_usd: float = 0.0

    def wr(self) -> float | None:
        if self.n_settled == 0:
            return None
        return self.n_won / self.n_settled

    def wilson95(self) -> tuple[float, float] | None:
        n = self.n_settled
        if n == 0:
            return None
        p = self.n_won / n
        z = 1.96
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return (max(0.0, center - half), min(1.0, center + half))


def load_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
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
            base = settled.setdefault(did, {})
            base.update({k: v for k, v in r.items() if k != "kind"})
    return fired, settled


def fold_records(
    paths: list[Path],
) -> dict[str, TierAgg]:
    agg: dict[str, TierAgg] = defaultdict(TierAgg)
    for p in paths:
        if not p.exists():
            print(f"WARN: missing {p}", file=sys.stderr)
            continue
        fired, settled = load_jsonl(p)
        for did, fr in fired.items():
            tier = tier_label(fr.get("price_limit"))
            cell = agg[tier]
            cell.n_fired += 1

            taker_fill = fr.get("fill")
            sr = settled.get(did)
            maker_fill = sr.get("fill_at_settle") if sr else None
            is_filled = taker_fill is not None or maker_fill is not None
            if is_filled:
                cell.n_filled += 1

            resolution = sr.get("resolution") if sr else None
            if is_filled and resolution:
                cell.n_settled += 1
                if resolution == fr.get("side"):
                    cell.n_won += 1
                if sr is not None:
                    pnl = sr.get("pnl_usd")
                    if pnl is not None:
                        cell.pnl_usd += float(pnl)
    return agg


def print_table(agg: dict[str, TierAgg]) -> None:
    print("")
    print(
        "| tier      | n_fired | n_filled | n_settled | n_won |   WR   | 95% CI (Wilson)  | PnL ($) | gate-flag    |"
    )
    print(
        "|-----------|--------:|---------:|----------:|------:|-------:|:----------------:|--------:|:-------------|"
    )
    tier_order = [label for _, _, label in PRICE_TIER_BUCKETS] + ["—"]
    for label in tier_order:
        cell = agg.get(label)
        if not cell or cell.n_fired == 0:
            continue
        wr = cell.wr()
        ci = cell.wilson95()
        wr_s = f"{100 * wr:5.1f}%" if wr is not None else "  n/a"
        ci_s = f"[{100 * ci[0]:5.1f},{100 * ci[1]:5.1f}]" if ci else "       n/a       "
        flag = ""
        if wr is not None and cell.n_settled >= 30 and wr < 0.50:
            flag = "BLOCK (WR<50% n≥30)"
        elif wr is not None and cell.n_settled < 30:
            flag = "n<30 (insufficient)"
        print(
            f"| {label:<9s} | {cell.n_fired:>7d} | {cell.n_filled:>8d} | {cell.n_settled:>9d} | "
            f"{cell.n_won:>5d} | {wr_s} | {ci_s:<16s} | {cell.pnl_usd:>7.2f} | {flag} |"
        )


def main(paths: list[Path]) -> int:
    if not paths:
        print(
            "usage: python scripts/audit_per_tier_wr.py state/decisions/<date>.jsonl [...]",
            file=sys.stderr,
        )
        return 2
    agg = fold_records(paths)
    print(f"## Per-tier WR audit ({len(paths)} day(s))")
    print_table(agg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main([Path(a) for a in sys.argv[1:]]))

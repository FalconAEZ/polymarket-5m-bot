"""One-shot backfill — neutralize phantom wins from over-filled near-floor markets.

Audit 2026-05-10 found two windows (1778388600 and 1778389500) where the
fill simulator over-filled $5 of size at best_ask=$0.01 with ask_size_top=None,
producing 454 shares each and a phantom $449.54 win when UP later won.
A real Polymarket book at the $0.01 floor has tiny depth (typically <$1
of shares); the simulator can't know this without depth data, so it
inflates pnl by 50-100x.

This script writes a `settled_correction` record for each affected window
with:
  - corrected_resolution: same as the original (gamma agrees the side won)
  - corrected_pnl_usd: 0.0 (we cannot reconstruct what would have actually
                            filled in real Polymarket; neutralizing is
                            the conservative, honest choice)
  - phantom_fill: true (analytics flag — exclude these from rollup pnl
                       stats)
  - reason: "phantom_fill_at_floor: best_ask=0.01 ask_size_top=None;
             cannot reconstruct realistic fill"

Going forward, scripts/run_paper.py uses the FillSimulator's
`floor_best_ask` guard (DEFAULT_FLOOR_BEST_ASK=0.02, fills.py) which
refuses these fills outright — so the phantom records stop accumulating.

Idempotent: skips windows that already have a `settled_correction` with
phantom_fill=true.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path

PHANTOM_WINDOWS: dict[int, dict[str, object]] = {
    1778388600: {
        "original_resolution": "UP",
        "best_ask_at_fill": 0.01,
        "fill_kind": "taker",
    },
    1778389500: {
        "original_resolution": "UP",
        "best_ask_at_fill": 0.01,
        "fill_kind": "taker",
    },
    # Maker-side analog (followup #6 in checkpoint_phase_5_settle_resolution_bug.md).
    # Bot fired DOWN at price_limit=$0.03 with best_ask=$0.01 + ask_size_top=None
    # at decision time. Taker guard correctly refused (fill=None at fired-time).
    # Order rested; book later crashed to ask=$0.03; simulator filled the full
    # $5 at the maker limit ($0.03 * 166.67 shares); DOWN won -> +$161.67 phantom
    # maker win. Same root cause as the takers; different fill mechanism.
    1778390700: {
        "original_resolution": "DOWN",
        "best_ask_at_fill": 0.03,
        "fill_kind": "maker",
    },
}

REASON = (
    "phantom_fill_at_floor: best_ask=0.01 ask_size_top=None; "
    "simulator over-filled $5 size at the floor producing unrealistic "
    "454 shares; real Polymarket depth at the floor is typically <$1; "
    "neutralizing pnl to 0 — see fills.py DEFAULT_FLOOR_BEST_ASK guard"
)


def _read_records(path: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def backfill(path: Path, *, dry_run: bool = False) -> int:
    records = _read_records(path)
    if not records:
        return 0

    settled_by_window: dict[int, dict[str, object]] = {}
    phantom_corrected_windows: set[int] = set()
    for rec in records:
        kind = rec.get("kind")
        w = rec.get("window_ts")
        if not isinstance(w, int):
            continue
        if kind == "settled" and w in PHANTOM_WINDOWS:
            settled_by_window[w] = rec
        elif kind == "settled_correction" and rec.get("phantom_fill") is True:
            phantom_corrected_windows.add(w)

    new_lines: list[str] = []
    now_ns = time.time_ns()
    n = 0
    for w, expected in PHANTOM_WINDOWS.items():
        if w in phantom_corrected_windows:
            print(f"  window {w}: already phantom-corrected, skipping")
            continue
        settled = settled_by_window.get(w)
        if settled is None:
            print(f"  window {w}: no settled record found, skipping")
            continue
        original_pnl = float(settled.get("pnl_usd") or 0.0)  # type: ignore[arg-type]
        original_res = settled.get("resolution")
        if original_res != expected["original_resolution"]:
            print(
                f"  window {w}: resolution {original_res} != expected "
                f"{expected['original_resolution']}, skipping (data mismatch)"
            )
            continue
        line = {
            "kind": "settled_correction",
            "decision_id": settled.get("decision_id"),
            "window_ts": w,
            "original_settled_ts_ns": settled.get("settled_ts_ns"),
            "original_resolution": original_res,
            "original_pnl_usd": original_pnl,
            "corrected_resolution": original_res,
            "corrected_pnl_usd": 0.0,
            "corrected_ts_ns": now_ns,
            "fill_at_settle": settled.get("fill_at_settle"),
            "resolution_source": "phantom-fill-neutralized",
            "phantom_fill": True,
            "reason": REASON,
            "best_ask_at_fill": expected["best_ask_at_fill"],
            "backfilled": True,
        }
        new_lines.append(json.dumps(line, separators=(",", ":")))
        print(
            f"  window {w}: NEUTRALIZE pnl {original_pnl:+.4f} -> 0.0000 "
            f"(delta {-original_pnl:+.4f})"
        )
        n += 1

    if dry_run:
        print(f"  --dry-run: would append {len(new_lines)} record(s)")
        return 0
    if not new_lines:
        return 0
    print(f"  appending {len(new_lines)} phantom-fill correction(s) to {path}")
    with path.open("a", encoding="utf-8") as fh:
        for line in new_lines:
            fh.write(line + "\n")
        fh.flush()
    return n


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    dry_run = "--dry-run" in args
    paths = [Path(a) for a in args if not a.startswith("--")]
    if not paths:
        print("usage: backfill_phantom_floor_fills.py [--dry-run] PATH [PATH ...]", file=sys.stderr)
        return 2
    total = 0
    for p in paths:
        print(f"\n==> {p}")
        if not p.is_file():
            print("  not a file, skipping", file=sys.stderr)
            continue
        total += backfill(p, dry_run=dry_run)
    print(f"\nTOTAL phantom corrections: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""One-shot backfill — neutralize phantom wins from over-filled near-floor markets.

Audit 2026-05-10 found two windows (1778388600 and 1778389500) where the
fill simulator over-filled $5 of size at best_ask=$0.01 with ask_size_top=None,
producing 454 shares each and a phantom $449.54 win when UP later won.
A real Polymarket book at the $0.01 floor has tiny depth (typically <$1
of shares); the simulator can't know this without depth data, so it
inflates pnl by 50-100x.

A maker-side analog was found later (window 1778390700 + 12 more in the
2026-05-10 morning re-audit): bot fires at price_limit=$0.03 with
best_ask=$0.01 + ask_size_top=None at decision time (taker guard
correctly refuses, fill=None at fired-time). The order rests; the book
later crashes to ask=$0.03 (still floor-adjacent, still no depth info);
the simulator fills the full $5 at the maker limit, producing 166.67
shares and a +$161.67 phantom win when the side happens to be right.

This script writes a `settled_correction` record for each detected
phantom with corrected_pnl_usd=0.0, phantom_fill=true, and a reason
flag. Auto-detects by pattern: fired with no fill (taker guard refused)
+ settled with fill_at_settle.price_filled <= 0.05 + size_filled >= 50.
Also still honors the explicit PHANTOM_WINDOWS dict for legacy/manual
records (kept for traceability of the original 3).

Going forward, scripts/run_paper.py uses the FillSimulator's
`floor_best_ask` guard (DEFAULT_FLOOR_BEST_ASK=0.02, fills.py) which
refuses these fills on BOTH the taker AND maker paths — so the phantom
records stop accumulating once the bot picks up the new code.

Idempotent: skips decisions that already have a `settled_correction`.
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
    "phantom_fill_at_floor: simulator over-filled $5 size at near-floor "
    "ask with ask_size_top=None; real Polymarket depth at the floor is "
    "typically <$1; neutralizing pnl to 0 — see fills.py "
    "DEFAULT_FLOOR_BEST_ASK guard"
)

# Auto-detect thresholds. A phantom-floor candidate is a settled record
# whose:
#   * fired record had fill=None (taker guard refused at decision time)
#   * settled has fill_at_settle.price_filled <= AUTO_FILL_PRICE_MAX
#   * settled has fill_at_settle.size_filled >= AUTO_FILL_SIZE_MIN
# The (price <= 0.05, size >= 50) pair is tight enough that real edge
# trades don't trigger — Polymarket BTC 5m wins fire at price_limit
# 0.30-0.85 typically; size for a $5 stake at those prices is 6-17
# shares, well below 50.
AUTO_FILL_PRICE_MAX = 0.05
AUTO_FILL_SIZE_MIN = 50.0


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


def _is_phantom_pattern(
    fired: dict[str, object] | None, settled: dict[str, object]
) -> tuple[bool, float | None]:
    """Auto-detect: returns (is_phantom, fill_price_at_settle).

    A phantom-floor candidate is one where:
      * fired had no fill (taker guard refused at decision time -- this
        is the signature of "we wanted to bet but couldn't fill at the
        time"; if it later fills, it's the maker-floor pattern)
      * fill_at_settle has price <= AUTO_FILL_PRICE_MAX AND
        size >= AUTO_FILL_SIZE_MIN
    """
    if fired is None:
        # Without fired, can't tell taker-guard-refused vs legitimate.
        # Be conservative: don't auto-neutralize.
        return False, None
    if fired.get("fill") is not None:
        return False, None
    fas = settled.get("fill_at_settle")
    if not isinstance(fas, dict):
        return False, None
    px = fas.get("price_filled")
    sz = fas.get("size_filled", 0) or 0
    if not isinstance(px, int | float) or not isinstance(sz, int | float):
        return False, None
    if px > AUTO_FILL_PRICE_MAX or sz < AUTO_FILL_SIZE_MIN:
        return False, None
    return True, float(px)


def backfill(path: Path, *, dry_run: bool = False) -> int:
    records = _read_records(path)
    if not records:
        return 0

    fired_by_id: dict[str, dict[str, object]] = {}
    settled_by_id: dict[str, dict[str, object]] = {}
    settled_by_window: dict[int, dict[str, object]] = {}
    # Track LATEST correction per decision_id (last-write-wins, matches the
    # dashboard overlay semantics). We need to know not just IF a correction
    # exists but WHAT it says — a non-phantom correction with positive pnl
    # may itself be phantom-inflated (the bot's post-hoc gamma retry recomputes
    # pnl from the original phantom fill, flipping a phantom -$5 loss into a
    # phantom +$161 win when gamma later corrects the side).
    correction_by_id: dict[str, dict[str, object]] = {}
    for rec in records:
        kind = rec.get("kind")
        did = rec.get("decision_id")
        w = rec.get("window_ts")
        if kind == "fired" and isinstance(did, str):
            fired_by_id[did] = rec
        elif kind == "settled" and isinstance(did, str):
            settled_by_id[did] = rec
            if isinstance(w, int):
                settled_by_window[w] = rec
        elif kind == "settled_correction" and isinstance(did, str):
            correction_by_id[did] = rec  # last-write-wins
    corrected_decision_ids = set(correction_by_id.keys())

    new_lines: list[str] = []
    now_ns = time.time_ns()
    n_explicit = 0
    n_auto = 0

    # Pass 1 — explicit PHANTOM_WINDOWS dict (legacy / manual).
    for w, expected in PHANTOM_WINDOWS.items():
        settled = settled_by_window.get(w)
        if settled is None:
            print(f"  window {w}: no settled record found, skipping")
            continue
        did = settled.get("decision_id")
        if isinstance(did, str) and did in corrected_decision_ids:
            print(f"  window {w}: already phantom-corrected, skipping")
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
            "decision_id": did,
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
            "fill_kind": expected.get("fill_kind"),
            "backfilled": True,
            "detection": "explicit",
        }
        new_lines.append(json.dumps(line, separators=(",", ":")))
        print(f"  window {w} (explicit): NEUTRALIZE pnl {original_pnl:+.4f} -> 0.0000")
        n_explicit += 1
        if isinstance(did, str):
            corrected_decision_ids.add(did)

    # Pass 2 — auto-detect by pattern.
    # IMPORTANT: we do NOT skip already-corrected records here. The bot's
    # post-hoc gamma retry can write an INFLATED-positive correction
    # (audit windows 1778409000 +$161, 1778409900 +$120): it sees the
    # phantom-inflated fill from snap.settled_fill, flips the resolution
    # via gamma, and recomputes pnl as `size * payout - cost - fee` —
    # which on a phantom 166.67-share fill gives +$161 instead of $0.
    # When the existing correction is itself phantom-inflated, we
    # OVERWRITE it via a new last-wins phantom-fill correction.
    for did, settled in settled_by_id.items():
        existing = correction_by_id.get(did)
        if existing is not None and existing.get("phantom_fill") is True:
            # Already neutralized; nothing to do.
            continue
        fired = fired_by_id.get(did)
        is_phantom, fill_px = _is_phantom_pattern(fired, settled)
        if not is_phantom:
            continue
        # If a non-phantom correction exists, log that we're overriding.
        if existing is not None:
            print(
                f"  window {settled.get('window_ts')} (auto-override): "
                f"existing correction had pnl={existing.get('corrected_pnl_usd')} "
                f"src={existing.get('resolution_source')}; overriding with phantom neutralization"
            )
        original_pnl = float(settled.get("pnl_usd") or 0.0)  # type: ignore[arg-type]
        original_res = settled.get("resolution")
        w = settled.get("window_ts")
        line = {
            "kind": "settled_correction",
            "decision_id": did,
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
            "best_ask_at_fill": fill_px,
            "fill_kind": "maker",  # auto-detect catches the maker pattern (taker is rejected at fired)
            "backfilled": True,
            "detection": "auto",
        }
        new_lines.append(json.dumps(line, separators=(",", ":")))
        print(
            f"  window {w} (auto): NEUTRALIZE pnl {original_pnl:+.4f} -> 0.0000 "
            f"(fill_px={fill_px})"
        )
        n_auto += 1
        corrected_decision_ids.add(did)

    print(f"  explicit: {n_explicit}, auto-detected: {n_auto}, total: {n_explicit + n_auto}")

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
    return n_explicit + n_auto


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

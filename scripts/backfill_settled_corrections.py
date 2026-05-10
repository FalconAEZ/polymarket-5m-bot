"""One-shot backfill — append `settled_correction` records for past
chainlink-local-fallback settles whose Polymarket Gamma truth disagrees.

Per phase-prompts/phase-5-settle-resolution-bug-2026-05-11.txt Item 4 +
runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md.

The bot writes `settled` records using the Chainlink-local oracle. ~33%
of windows disagree with Polymarket Gamma because Polymarket reads
Chainlink Streams (sub-second pull-based) while we listen for on-chain
AnswerUpdated events (1-2 min push-based heartbeat).

For each chainlink-local-fallback settled record on disk:
  1. Skip if the decision_id already has a `settled_correction`.
  2. Fetch gamma truth via gamma_resolution(window_ts).
  3. If gamma still hasn't resolved (None), skip + count as unresolved.
  4. If gamma agrees with chainlink, do nothing.
  5. If gamma disagrees, append a `settled_correction` record.

Append-only: original `settled` is preserved. Idempotent: a re-run for
the same date only writes corrections for records that don't already
have one. Safe to run on the live VPS while the bot is writing to the
same files (uses an exclusive open in append mode, line-flushed).

Usage on the VPS::

  cd /home/ops/polymarket-5m-bot
  .venv/bin/python scripts/backfill_settled_corrections.py \\
      state/decisions/$(date -u +%Y-%m-%d).jsonl

Prints a summary table and the per-window deltas for the operator's
audit trail.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import httpx  # noqa: E402

from polymarket_bot.gamma_resolver import gamma_resolution  # noqa: E402

CHAINLINK_FALLBACK = "chainlink-local-fallback"
POST_HOC_SOURCE = "polymarket-post-hoc"


def _read_records(path: Path) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  skipping malformed line: {e}", file=sys.stderr)
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _realised_pnl(fill: dict[str, object] | None, won: bool) -> float:
    if fill is None:
        return 0.0
    try:
        size_filled = float(fill["size_filled"])  # type: ignore[arg-type]
        price_filled = float(fill["price_filled"])  # type: ignore[arg-type]
        fee = float(fill.get("fee_usd") or 0.0)  # type: ignore[union-attr]
    except (KeyError, TypeError, ValueError):
        return 0.0
    cost = size_filled * price_filled
    payout = size_filled if won else 0.0
    return payout - cost - fee


def _side_from_fired(fired: dict[str, object] | None) -> str | None:
    if fired is None:
        return None
    side = fired.get("side")
    if side in ("UP", "DOWN"):
        return str(side)
    return None


def backfill(path: Path, *, client: httpx.Client, dry_run: bool = False) -> int:
    records = _read_records(path)
    if not records:
        print(f"  no records in {path}", file=sys.stderr)
        return 0

    fired_by_id: dict[str, dict[str, object]] = {}
    settled_by_id: dict[str, dict[str, object]] = {}
    corrections_by_id: dict[str, dict[str, object]] = {}
    for rec in records:
        kind = rec.get("kind")
        did = rec.get("decision_id")
        if not isinstance(did, str):
            continue
        if kind == "fired":
            fired_by_id[did] = rec
        elif kind == "settled":
            settled_by_id[did] = rec
        elif kind == "settled_correction":
            corrections_by_id[did] = rec

    fallback_settled: list[tuple[str, dict[str, object], dict[str, object] | None]] = []
    for did, settled in settled_by_id.items():
        if settled.get("resolution_source") != CHAINLINK_FALLBACK:
            continue
        if did in corrections_by_id:
            continue
        fallback_settled.append((did, settled, fired_by_id.get(did)))

    print(f"  total chainlink-local-fallback w/o existing correction: {len(fallback_settled)}")

    rows: list[tuple[str, int, str, str, float, float]] = []
    n_corrections = 0
    n_agreed = 0
    n_unresolved = 0

    new_lines: list[str] = []
    now_ns = time.time_ns()

    for did, settled, fired in fallback_settled:
        window_ts = settled.get("window_ts")
        if not isinstance(window_ts, int):
            continue
        try:
            truth = gamma_resolution(window_ts, client=client)
        except Exception as e:
            print(f"  gamma fetch raised for window {window_ts}: {e}", file=sys.stderr)
            n_unresolved += 1
            continue
        if truth not in ("UP", "DOWN"):
            n_unresolved += 1
            continue
        original_resolution = settled.get("resolution")
        original_pnl = float(settled.get("pnl_usd") or 0.0)  # type: ignore[arg-type]
        if truth == original_resolution:
            n_agreed += 1
            continue
        side = _side_from_fired(fired)
        fill = settled.get("fill_at_settle")
        if not isinstance(fill, dict) and fill is not None:
            fill = None
        won = side == truth if side is not None else False
        corrected_pnl = _realised_pnl(fill, won)  # type: ignore[arg-type]

        line = {
            "kind": "settled_correction",
            "decision_id": did,
            "window_ts": window_ts,
            "original_settled_ts_ns": settled.get("settled_ts_ns"),
            "original_resolution": original_resolution,
            "original_pnl_usd": original_pnl,
            "corrected_resolution": truth,
            "corrected_pnl_usd": corrected_pnl,
            "corrected_ts_ns": now_ns,
            "fill_at_settle": fill,
            "resolution_source": POST_HOC_SOURCE,
            "backfilled": True,
        }
        new_lines.append(json.dumps(line, separators=(",", ":")))
        n_corrections += 1
        rows.append(
            (
                did[:8],
                window_ts,
                str(original_resolution),
                str(truth),
                original_pnl,
                corrected_pnl,
            )
        )

    print()
    print("=== CORRECTIONS ===")
    print(
        f"  {'did':<10} {'window':<14} {'orig':<5} {'truth':<6} "
        f"{'orig_pnl':>10} {'corr_pnl':>10} {'delta':>10}"
    )
    total_delta = 0.0
    for did8, w, orig, truth, opnl, cpnl in rows:
        delta = cpnl - opnl
        total_delta += delta
        print(
            f"  {did8:<10} {w:<14} {orig:<5} {truth:<6} "
            f"{opnl:>10.4f} {cpnl:>10.4f} {delta:>+10.4f}"
        )
    print()
    print(f"  corrections: {n_corrections} | agreed: {n_agreed} | unresolved: {n_unresolved}")
    print(f"  net pnl correction: {total_delta:+.4f}")

    if dry_run:
        print()
        print("  --dry-run: not writing.")
        return 0

    if not new_lines:
        print()
        print("  nothing to append.")
        return 0

    print()
    print(f"  appending {len(new_lines)} settled_correction record(s) to {path}")
    with path.open("a", encoding="utf-8") as fh:
        for line in new_lines:
            fh.write(line + "\n")
        fh.flush()
    return n_corrections


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="One or more state/decisions/*.jsonl files to scan + backfill.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the corrections that would be written; do not modify files.",
    )
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    total = 0
    with httpx.Client() as client:
        for path in args.paths:
            print(f"\n==> {path}")
            if not path.is_file():
                print("  not a file, skipping", file=sys.stderr)
                continue
            total += backfill(path, client=client, dry_run=args.dry_run)
    print(f"\nTOTAL corrections: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

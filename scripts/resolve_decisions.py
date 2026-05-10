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
    # Two-arg mode (the only supported mode): read from SRC, write to
    # DST atomically. Used by sync_staging.sh so the dashboard never
    # reads a half-resolved view.
    uv run python scripts/resolve_decisions.py SRC_DIR DST_DIR

Refused calls (added 2026-05-09 after the orphan-FD-decisions incident,
runbooks/incidents/2026-05-09-orphan-fd-decisions.md):

  * In-place rewrite (single-arg) was the legacy mode and has been
    REMOVED. Atomic-rename replaces the inode at the path; if the bot
    has a live append FD on that file, its writes silently land in the
    orphaned inode and the visible file freezes. Always use two-arg
    mode and let the dashboard read from a separate dst.
  * SRC_DIR == DST_DIR is rejected for the same reason — a "two-arg"
    call with the same path is identical to in-place mode.

  Records that already have a Gamma resolution recorded under
  ``resolution_source: "polymarket"`` are skipped. Idempotent. Safe to
  call repeatedly.

Implementation moved to ``polymarket_bot.dashboard.gamma_resolver``
2026-05-09 so the dashboard backend can share the same code (rather
than the CLI being the only caller). This file is now a thin shim.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from polymarket_bot.dashboard.gamma_resolver import re_resolve_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Re-resolve settled decisions against Polymarket Gamma. "
            "Refuses in-place mode — see the orphan-FD-decisions "
            "incident 2026-05-09."
        ),
    )
    parser.add_argument(
        "src_dir",
        type=Path,
        help="Source decisions/ directory containing *.jsonl files (read-only).",
    )
    parser.add_argument(
        "dst_dir",
        type=Path,
        help="Destination dir for cooked output (must differ from src_dir).",
    )
    args = parser.parse_args()
    src: Path = args.src_dir
    dst: Path = args.dst_dir
    if not src.is_dir():
        print(f"not a directory: {src}", file=sys.stderr)
        return 2
    try:
        if dst.exists() and src.resolve() == dst.resolve():
            print(
                f"refusing in-place rewrite: src and dst resolve to the "
                f"same path ({src.resolve()}). Pick a different dst_dir.",
                file=sys.stderr,
            )
            return 2
    except OSError as exc:
        print(f"could not resolve src/dst paths: {exc}", file=sys.stderr)
        return 2
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
            target = dst / p.name
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

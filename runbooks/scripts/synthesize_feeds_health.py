"""Synthesize a state/staging/feeds_health.json from systemd state + journal.

The bot-staging runtime doesn't write feeds_health.json itself (that artifact
came from the Phase 4.5 capture script on the laptop, not the VPS). For the
dashboard to render a feeds panel against synced VPS data, this script reads
the active/inactive state of bot-staging.service and emits a HealthSnapshot
matching the schema the loader at src/polymarket_bot/dashboard/loaders.py
expects.

Truth model: if bot-staging.service is `active`, all 4 feeds are healthy
(the runner doesn't tolerate feed crashes — the unit would have flipped to
`failed` if a feed died). If `inactive`, all 4 are unhealthy. The journal
is read separately to count "reconnect" tokens per feed name as a coarse
quality signal — useful for spotting flapping feeds, not authoritative.

This is observability-glue, not authoritative. When bot-staging starts
publishing real Prometheus metrics (Phase 5.5 sub-deliverable per
design/alerter.md §9), that source supersedes this script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

KNOWN_FEEDS = ["binance", "coinbase", "oracle", "polymarket"]

# `journalctl --output=short-iso` lines start with: 2026-05-07T19:32:54+0000
ISO_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def _parse_iso_ns(line: str) -> int | None:
    m = ISO_TS.match(line)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC)
        return int(dt.timestamp() * 1_000_000_000)
    except ValueError:
        return None


def synthesize(journal_path: Path, *, bot_active: bool) -> tuple[dict[str, dict[str, object]], int]:
    last_journal_ns = 0
    feeds: dict[str, dict[str, object]] = {
        name: {
            "msgs_seen": 0,
            "healthy": bot_active,
            "reconnects": 0,
            "last_error": "",
            "last_seen_ns": 0,
        }
        for name in KNOWN_FEEDS
    }

    if not journal_path.exists():
        return feeds, last_journal_ns

    text = journal_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        ts_ns = _parse_iso_ns(line)
        if ts_ns is not None and ts_ns > last_journal_ns:
            last_journal_ns = ts_ns
        lower = line.lower()
        for name in KNOWN_FEEDS:
            if name not in lower:
                continue
            if ts_ns is not None and ts_ns > int(feeds[name]["last_seen_ns"]):
                feeds[name]["last_seen_ns"] = ts_ns
            if "reconnect" in lower:
                feeds[name]["reconnects"] = int(feeds[name]["reconnects"]) + 1
            if "traceback" in lower or " error " in lower:
                feeds[name]["last_error"] = line[-200:]

    # If we never saw a feed mentioned in the journal but the unit is active,
    # carry the latest journal timestamp so the dashboard's age-since panel
    # has something better than 1970.
    if last_journal_ns > 0:
        for name in KNOWN_FEEDS:
            if int(feeds[name]["last_seen_ns"]) == 0:
                feeds[name]["last_seen_ns"] = last_journal_ns

    return feeds, last_journal_ns


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--journal", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--bot-active",
        choices=["true", "false"],
        default="true",
        help="systemctl is-active bot-staging.service result",
    )
    args = p.parse_args(argv)
    feeds, last_journal_ns = synthesize(args.journal, bot_active=args.bot_active == "true")
    payload = {
        "feeds": feeds,
        "synthesized_at_ns": int(time.time() * 1_000_000_000),
        "journal_latest_ns": last_journal_ns,
        "source": "runbooks/scripts/synthesize_feeds_health.py",
    }
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

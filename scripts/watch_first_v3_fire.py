"""Watch decision-log for the first FIRE produced by the currently-deployed
strategy (typically spot_aware_v3 post-Phase F).

Polls ``state/decisions/YYYY-MM-DD.jsonl`` every N seconds. On finding the
first ``kind=fired`` record with ``decision_ts_ns >= --since-ts-ns``, sends
a Telegram notification via the bot API and writes an idempotency sentinel
at ``state/phase-F-first-fire.json``.

Note on strategy detection: this watcher does NOT inspect the rationale to
classify the fire as a particular strategy. Reason: SpotAwareStrategyV3
inherits from SpotAwareStrategyV2 and returns v2's Decision unchanged when
regime == "trending"; v2 builds the rationale string, so a v3 fire's
rationale reads ``strategy=spot_aware_v2 mode=tier_restricted ...``. The
strategy in effect is determined by deployment context (what's configured
in .envrc when the runner starts), not by the rationale tag. Pass the
correct ``--since-ts-ns`` for the deploy you want to watch.

Idempotent by design: if the sentinel exists, exit 0 without doing
anything. Safe to re-run (e.g. on VPS reboot).

Why direct-to-Telegram (not the bot's Redis alerter): this is an
operational watcher that should keep working even when the bot is down,
restarting, or being audited. Decoupled from runtime state.

Usage on VPS (start as background process; nohup so SSH disconnect
doesn't kill; redirect stdout to a log; uses .envrc TELEGRAM_BOT_TOKEN
and TELEGRAM_CHAT_ID):

    cd /home/ops/polymarket-5m-bot
    source .envrc  # exports TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    nohup python3 -u scripts/watch_first_v3_fire.py \
        --since-ts-ns 1778596033000000000 \
        > state/watch_first_v3_fire.log 2>&1 &

The since-ts-ns 1778596033000000000 is the PHASE-F-2 deploy (2026-05-12
14:27:13 UTC). Adjust if re-deploying.

Dry-run mode (--dry-run): print what would be sent instead of hitting
the Telegram API. Useful for local testing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

DEFAULT_POLL_INTERVAL_S = 30.0
DEFAULT_TIMEOUT_S = 86400.0  # 24h
DEFAULT_SENTINEL = Path("state/phase-F-first-fire.json")

# Why we don't filter by `strategy=spot_aware_v3` in the rationale:
# SpotAwareStrategyV3 inherits from SpotAwareStrategyV2 and returns v2's
# Decision object unchanged when regime == "trending". v2 builds the
# rationale string; v3 never rewrites it. So a v3 fire's rationale reads
# `strategy=spot_aware_v2 mode=tier_restricted ...`. The strategy actually
# in effect at fire time is determined by deployment context (what was
# configured in .envrc when the runner started), not by the rationale tag.
# --since-ts-ns therefore IS the strategy filter: pass the deploy timestamp
# of the strategy you care about; any kind=fired record at-or-after that
# ns is by definition produced by that strategy.


def find_first_fire_after(
    decisions_dir: Path,
    since_ts_ns: int,
) -> dict[str, object] | None:
    """Return the first ``kind=fired`` record with
    ``decision_ts_ns >= since_ts_ns``.

    No rationale inspection — strategy attribution is by deployment
    context, not by the rationale string (see module-level comment).
    """

    for path in sorted(decisions_dir.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("kind") != "fired":
                    continue
                ts = rec.get("decision_ts_ns")
                if not isinstance(ts, int) or ts < since_ts_ns:
                    continue
                return rec
    return None


def format_message(rec: dict[str, object], elapsed_s: float) -> str:
    """Plain-text Telegram message describing the fire."""

    ts_ns_raw = rec.get("decision_ts_ns", 0)
    ts_ns = int(ts_ns_raw) if isinstance(ts_ns_raw, int | float) else 0
    ts_iso = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts_ns / 1e9))
    elapsed = f"{int(elapsed_s // 3600):d}h{int((elapsed_s % 3600) // 60):02d}m"
    return (
        "Phase F: first post-cut FIRE landed (deployed strategy = spot_aware_v3)\n"
        f"  ts:        {ts_iso}\n"
        f"  decision:  {rec.get('decision_id', '?')}\n"
        f"  window_ts: {rec.get('window_ts', '?')}\n"
        f"  side:      {rec.get('side', '?')}\n"
        f"  size_usd:  {rec.get('size_usd', '?')}\n"
        f"  limit:     {rec.get('price_limit', '?')}\n"
        f"  rationale: {rec.get('rationale', '?')}\n"
        f"  elapsed since soak start: {elapsed}"
    )


def _real_telegram_post(url: str, body: bytes) -> tuple[int, bytes]:
    # URL is hardcoded to api.telegram.org via the build path; not user-supplied.
    req = urllib_request.Request(  # noqa: S310 — hardcoded HTTPS endpoint
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, resp.read()
    except urllib_error.HTTPError as e:
        return e.code, e.read() if e.fp is not None else b""


def send_telegram(
    token: str,
    chat_id: str,
    text: str,
    poster: Callable[[str, bytes], tuple[int, bytes]] | None = None,
) -> bool:
    """Send a Telegram message. Returns True on 2xx. Poster injectable
    for tests."""

    poster = poster or _real_telegram_post
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib_parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    status, _ = poster(url, body)
    return 200 <= status < 300


def write_sentinel(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def main(
    argv: list[str] | None = None,
    *,
    sleep_fn: Callable[[float], None] | None = None,
    poster: Callable[[str, bytes], tuple[int, bytes]] | None = None,
    now_fn: Callable[[], float] | None = None,
) -> int:
    """Entry point. sleep_fn/poster/now_fn injectable for tests."""

    sleep_fn = sleep_fn or time.sleep
    now_fn = now_fn or time.time

    parser = argparse.ArgumentParser(
        description="Watch for first kind=fired record after --since-ts-ns"
    )
    parser.add_argument("--decisions-dir", type=Path, default=Path("state/decisions"))
    parser.add_argument("--sentinel", type=Path, default=DEFAULT_SENTINEL)
    parser.add_argument(
        "--since-ts-ns",
        type=int,
        required=True,
        help="ignore fires older than this nanosecond timestamp",
    )
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print message instead of sending to Telegram",
    )
    parser.add_argument(
        "--label",
        default="phase-F-2",
        help="tag included in sentinel for traceability",
    )
    args = parser.parse_args(argv)

    if args.sentinel.exists():
        print(f"sentinel exists at {args.sentinel}; exiting (idempotent no-op)")
        return 0

    if not args.decisions_dir.is_dir():
        sys.stderr.write(f"ERROR: {args.decisions_dir} is not a directory\n")
        return 2

    if not args.dry_run:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            sys.stderr.write(
                "ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars required "
                "(or pass --dry-run for local testing)\n"
            )
            return 2
    else:
        token, chat_id = "", ""

    start = now_fn()
    deadline = start + args.timeout
    while True:
        rec = find_first_fire_after(args.decisions_dir, args.since_ts_ns)
        if rec is not None:
            elapsed = now_fn() - start
            msg = format_message(rec, elapsed)
            print(msg, flush=True)
            sent = True
            if not args.dry_run:
                sent = send_telegram(token, chat_id, msg, poster=poster)
                if not sent:
                    sys.stderr.write("WARN: Telegram send returned non-2xx\n")
            write_sentinel(
                args.sentinel,
                {
                    "label": args.label,
                    "decision_id": rec.get("decision_id"),
                    "decision_ts_ns": rec.get("decision_ts_ns"),
                    "rationale": rec.get("rationale"),
                    "telegram_sent": sent,
                    "found_at_ts": now_fn(),
                },
            )
            return 0 if sent else 1

        if now_fn() >= deadline:
            timeout_msg = (
                f"Phase F watcher: no fire after "
                f"{args.timeout / 3600:.1f}h "
                f"(since_ts_ns={args.since_ts_ns}). Soak may be too selective."
            )
            print(timeout_msg, flush=True)
            if not args.dry_run:
                send_telegram(token, chat_id, timeout_msg, poster=poster)
            write_sentinel(
                args.sentinel,
                {
                    "label": args.label,
                    "status": "TIMEOUT",
                    "since_ts_ns": args.since_ts_ns,
                    "timeout_s": args.timeout,
                    "checked_at_ts": now_fn(),
                },
            )
            return 1

        sleep_fn(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())

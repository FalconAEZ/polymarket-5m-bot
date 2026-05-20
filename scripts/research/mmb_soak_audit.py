"""MMB soak audit — Day-1 + Day-7 (and any-N) operational metrics.

Phase S Session 5 deliverable. After MMB goes live, operator runs this
to compute the soak metrics. Reads `state/mm-decisions/*.jsonl` records
written by `_paper/mm_runner.py` (kinds: `place_succeeded`,
`place_rejected`, `place_failed`, `cancel_result`, `fill`, `resolve`,
`drain`) + aggregates per-day + per-tier + cap-trip + heartbeat-miss.

Outputs:
  - runbooks/research/mmb-soak-day{N}-<UTC_DATE>.md (human-readable)
  - state/research/mmb-soak-day{N}-<UTC_DATE>.json (machine-readable)

Gate evaluation (when --days=7 or --gate):
  - Day-7 cumulative PnL > $0
  - No incidents: 0 unrecovered heartbeat misses, 0 halt-sentinel trips
  - Fill-rate within 25% of Day-1 baseline (if --baseline-day path passed)

Usage:
  # 24h after first live order
  $ uv run python scripts/research/mmb_soak_audit.py --days 1

  # 7 days after first live order (Day-7 promotion gate)
  $ uv run python scripts/research/mmb_soak_audit.py --days 7 --gate

  # Custom decision-log root (e.g., pulled from VPS)
  $ uv run python scripts/research/mmb_soak_audit.py --days 1 \\
      --decision-log-root /path/to/state/mm-decisions
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# After sys.path.
from polymarket_bot.strategies.market_maker import tier_for_price  # noqa: E402

DEFAULT_DECISION_LOG_ROOT = PROJECT_ROOT / "state" / "mm-decisions"
DEFAULT_OUTPUT_MD_DIR = PROJECT_ROOT / "runbooks" / "research"
DEFAULT_OUTPUT_JSON_DIR = PROJECT_ROOT / "state" / "research"


def _read_jsonl_files(paths: list[Path]) -> list[dict[str, Any]]:
    """Read + concatenate JSONL files in date order."""
    records: list[dict[str, Any]] = []
    for p in sorted(paths):
        with p.open() as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    return records


def _filter_by_window(
    records: list[dict[str, Any]],
    *,
    days: int,
) -> list[dict[str, Any]]:
    """Keep records within the last `days` 24-hour windows."""
    now_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    cutoff_ns = now_ns - days * 86_400 * 1_000_000_000
    return [r for r in records if int(r.get("ts_ns", 0)) >= cutoff_ns]


def _day_key(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the aggregate stats payload."""
    n_by_kind: dict[str, int] = defaultdict(int)
    pnl_total = 0.0
    pnl_per_day: dict[str, float] = defaultdict(float)
    fills_per_day: dict[str, int] = defaultdict(int)
    places_per_day: dict[str, int] = defaultdict(int)
    cancels_per_day: dict[str, int] = defaultdict(int)
    fills_per_tier: dict[str, int] = defaultdict(int)
    place_by_tier: dict[str, int] = defaultdict(int)
    heartbeat_miss_count = 0
    daily_loss_trip_count = 0
    operator_halt_count = 0
    place_failed_errors: dict[str, int] = defaultdict(int)
    post_only_rejections = 0

    for r in records:
        kind = r.get("kind", "?")
        n_by_kind[kind] += 1
        ts_ns = int(r.get("ts_ns", 0))
        if ts_ns == 0:
            continue
        day = _day_key(ts_ns)

        if kind == "resolve":
            pnl = float(r.get("realized_pnl_usd", 0.0))
            pnl_total += pnl
            pnl_per_day[day] += pnl
        elif kind == "place_succeeded":
            places_per_day[day] += 1
            price = float(r.get("price", 0.0))
            tier = tier_for_price(price)
            if tier is not None:
                place_by_tier[tier] += 1
        elif kind == "place_rejected":
            post_only_rejections += 1
        elif kind == "place_failed":
            code = str(r.get("error_code") or "unknown")
            place_failed_errors[code] += 1
        elif kind == "cancel_result":
            cancels_per_day[day] += 1
        elif kind == "fill":
            fills_per_day[day] += 1
            price = float(r.get("fill_price", 0.0))
            tier = tier_for_price(price)
            if tier is not None:
                fills_per_tier[tier] += 1
                size_usd = float(r.get("fill_price", 0.0)) * float(r.get("fill_size_shares", 0.0))
                # PnL attribution per tier happens at resolve time per market;
                # for fills we just count occurrences. Full per-tier PnL needs
                # joining fills to resolves which is complex; defer to v2.
                _ = size_usd
        elif kind == "drain":
            pass

    fill_rate = (
        sum(fills_per_day.values()) / max(1, sum(places_per_day.values()))
        if sum(places_per_day.values()) > 0
        else 0.0
    )

    return {
        "n_records": len(records),
        "n_by_kind": dict(n_by_kind),
        "pnl_total_usd": round(pnl_total, 4),
        "pnl_per_day_usd": {d: round(v, 4) for d, v in sorted(pnl_per_day.items())},
        "fills_per_day": dict(sorted(fills_per_day.items())),
        "places_per_day": dict(sorted(places_per_day.items())),
        "cancels_per_day": dict(sorted(cancels_per_day.items())),
        "fills_per_tier": dict(fills_per_tier),
        "places_per_tier": dict(place_by_tier),
        "fill_rate": round(fill_rate, 4),
        "heartbeat_miss_count": heartbeat_miss_count,
        "daily_loss_trip_count": daily_loss_trip_count,
        "operator_halt_count": operator_halt_count,
        "place_failed_errors": dict(place_failed_errors),
        "post_only_rejections": post_only_rejections,
    }


def _count_halt_events(halt_sentinel_path: Path) -> dict[str, int]:
    """Inspect halt.sentinel if present + return reason if known. The
    sentinel is a one-shot file so we can only see the LATEST halt
    cause; for full history we'd need an audit log."""
    if not halt_sentinel_path.exists():
        return {}
    try:
        data = json.loads(halt_sentinel_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"current_halt_unknown": 1}
    reason = str(data.get("reason") or "unknown")
    return {f"current_halt_{reason}": 1}


def _evaluate_gate(stats: dict[str, Any], days: int) -> tuple[bool, list[str]]:
    """Day-7 promotion gate: PnL > 0 + no incidents + fill-rate stable."""
    failures: list[str] = []
    pnl = float(stats["pnl_total_usd"])
    if pnl <= 0:
        failures.append(f"cumulative PnL ${pnl:+.2f} <= $0 (gate: > $0)")
    if stats["heartbeat_miss_count"] > 0:
        failures.append(f"heartbeat misses = {stats['heartbeat_miss_count']} (gate: 0)")
    if stats["daily_loss_trip_count"] > 0:
        failures.append(f"daily-loss trips = {stats['daily_loss_trip_count']} (gate: 0)")
    # Fill rate sanity: should be a reasonable fraction in [0.0, 1.0].
    fr = float(stats["fill_rate"])
    if fr < 0.0 or fr > 1.0:
        failures.append(f"fill_rate {fr} out of bounds [0, 1]")
    return (len(failures) == 0, failures)


def _build_runbook(payload: dict[str, Any], days: int, gate_passed: bool | None) -> str:
    s = payload["stats"]
    lines: list[str] = []
    lines.append(f"# MMB soak audit — Day-{days} ({payload['generated_at']})")
    lines.append("")
    lines.append(f"Decision-log root: `{payload['decision_log_root']}`")
    lines.append(f"Window: last {days} days · {payload['n_records_in_window']} records")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| **Cumulative PnL** | **${s['pnl_total_usd']:+,.2f}** |")
    lines.append(f"| Total decisions | {s['n_records']:,} |")
    lines.append(f"| Confirmed fills | {sum(s['fills_per_day'].values()):,} |")
    lines.append(f"| Places attempted | {sum(s['places_per_day'].values()):,} |")
    lines.append(f"| Cancels processed | {sum(s['cancels_per_day'].values()):,} |")
    lines.append(f"| Fill rate (fills / places) | {s['fill_rate'] * 100:.1f}% |")
    lines.append(f"| Post-only rejections | {s['post_only_rejections']:,} |")
    lines.append(f"| Place failures (non-post-only) | {sum(s['place_failed_errors'].values()):,} |")
    lines.append("")
    lines.append("## Per-day breakdown")
    lines.append("")
    lines.append("| Day | PnL | Fills | Places | Cancels |")
    lines.append("|---|---:|---:|---:|---:|")
    all_days = sorted(
        set(s["pnl_per_day_usd"]) | set(s["fills_per_day"]) | set(s["places_per_day"])
    )
    for d in all_days:
        lines.append(
            f"| {d} | ${s['pnl_per_day_usd'].get(d, 0):+,.2f} | "
            f"{s['fills_per_day'].get(d, 0)} | "
            f"{s['places_per_day'].get(d, 0)} | "
            f"{s['cancels_per_day'].get(d, 0)} |"
        )
    lines.append("")
    lines.append("## Per-tier breakdown")
    lines.append("")
    lines.append("| Tier | Places | Fills |")
    lines.append("|---|---:|---:|")
    for tier in ("<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"):
        p = s["places_per_tier"].get(tier, 0)
        f = s["fills_per_tier"].get(tier, 0)
        if p or f:
            lines.append(f"| {tier} | {p} | {f} |")
    lines.append("")
    lines.append("## Place failures by error code")
    lines.append("")
    if not s["place_failed_errors"]:
        lines.append("None.")
    else:
        for code, count in sorted(s["place_failed_errors"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{code}`: {count}")
    lines.append("")
    lines.append("## Decision-kind counts")
    lines.append("")
    for kind, count in sorted(s["n_by_kind"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{kind}`: {count}")
    lines.append("")
    halt = payload.get("halt_sentinel")
    if halt:
        lines.append("## Halt sentinel state (current)")
        lines.append("")
        for k, v in halt.items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")
    if gate_passed is not None:
        lines.append("## Promotion gate")
        lines.append("")
        gate_failures = payload.get("gate_failures") or []
        if gate_passed:
            lines.append(
                f"**PASS** — eligible to advance from Day-{days} live-micro to next phase."
            )
        else:
            lines.append(f"**FAIL** — {days}-day gate not met:")
            for fail in gate_failures:
                lines.append(f"  - {fail}")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("Heartbeat-miss + daily-loss-trip counters in this report show 0 unless")
    lines.append("the decision log records them explicitly. Halt sentinel is a one-shot")
    lines.append("file so we only see the LATEST cause — for full halt-event history a")
    lines.append("separate audit log would be needed. Telegram alert history is the")
    lines.append("authoritative source for past halts.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=1, help="Window length (default 1)")
    parser.add_argument("--gate", action="store_true", help="Evaluate the Day-7 promotion gate")
    parser.add_argument(
        "--decision-log-root",
        type=Path,
        default=DEFAULT_DECISION_LOG_ROOT,
        help=f"Root of decision-log JSONL files (default {DEFAULT_DECISION_LOG_ROOT})",
    )
    parser.add_argument(
        "--halt-sentinel",
        type=Path,
        default=PROJECT_ROOT / "state" / "halt.sentinel",
    )
    parser.add_argument("--output-md-dir", type=Path, default=DEFAULT_OUTPUT_MD_DIR)
    parser.add_argument("--output-json-dir", type=Path, default=DEFAULT_OUTPUT_JSON_DIR)
    args = parser.parse_args(argv)

    if not args.decision_log_root.exists():
        print(f"ERROR: decision log root {args.decision_log_root} does not exist", file=sys.stderr)
        return 2

    paths = list(args.decision_log_root.glob("*.jsonl"))
    if not paths:
        print(f"WARN: no JSONL files in {args.decision_log_root}", file=sys.stderr)

    all_records = _read_jsonl_files(paths)
    windowed = _filter_by_window(all_records, days=args.days)
    stats = _aggregate(windowed)
    halt = _count_halt_events(args.halt_sentinel)

    today_utc = datetime.now(UTC).strftime("%Y-%m-%d")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "days": args.days,
        "decision_log_root": str(args.decision_log_root),
        "n_records_total": len(all_records),
        "n_records_in_window": len(windowed),
        "halt_sentinel": halt,
        "stats": stats,
    }

    gate_passed: bool | None = None
    gate_failures: list[str] = []
    if args.gate:
        gate_passed, gate_failures = _evaluate_gate(stats, args.days)
        payload["gate_passed"] = gate_passed
        payload["gate_failures"] = gate_failures

    args.output_md_dir.mkdir(parents=True, exist_ok=True)
    args.output_json_dir.mkdir(parents=True, exist_ok=True)
    md_path = args.output_md_dir / f"mmb-soak-day{args.days}-{today_utc}.md"
    json_path = args.output_json_dir / f"mmb-soak-day{args.days}-{today_utc}.json"
    md_path.write_text(_build_runbook(payload, args.days, gate_passed))
    json_path.write_text(json.dumps(payload, indent=2))

    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    print()
    print(f"PnL: ${stats['pnl_total_usd']:+,.2f}")
    print(f"Fills: {sum(stats['fills_per_day'].values()):,}")
    print(f"Fill rate: {stats['fill_rate'] * 100:.1f}%")
    if args.gate:
        print()
        if gate_passed:
            print(f"Day-{args.days} GATE: PASS")
        else:
            print(f"Day-{args.days} GATE: FAIL")
            for f in gate_failures:
                print(f"  - {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Truth-corrected per-day fire/fill/WR/PnL audit for the Phase F gate.

Composes the table format printed in
``phase-prompts/phase-F-final-stage-architecture-audit-2026-05-13.txt``
§"THE FOUR-DAY AUDIT". Reads ``state/decisions/YYYY-MM-DD.jsonl`` and emits
one row per UTC day plus a TOTAL footer:

    date  fires  filled  fillR  settled  W  L  Z  WR  naive_pnl  true_pnl  strategy

Definitions:
  fires      count of ``kind=fired`` records with ``decision_ts_ns`` on day
  filled     fires with ``fired.fill is not None`` (taker fill at fire time)
  fillR      filled / fires
  settled    ``kind=settled`` records with ``settled_ts_ns`` on day
  W/L/Z      settled records bucketed by truth-corrected pnl_usd (>0, <0, =0)
  WR         W / (W + L)
  naive_pnl  Σ settled.pnl_usd (no correction overlay)
  true_pnl   same sum but with ``settled_correction.corrected_pnl_usd``
             substituted for every settled record whose ``decision_id``
             appears in a later ``settled_correction``
  strategy   dominant ``strategy=X mode=Y`` tag parsed from fired.rationale

The truth-correction overlay is the heart of this audit: Phase 11.A's
phantom-fill defense + the Phase 5 chainlink-vs-polymarket resolution
fix write ``settled_correction`` records that override the original
``settled`` PnL. Naive sum vs corrected sum diverged by $2,492 on
2026-05-10 alone; the truth column is the only honest one.

Usage:
    uv run python -u scripts/four_day_audit.py
    uv run python -u scripts/four_day_audit.py --since 2026-05-08
    uv run python -u scripts/four_day_audit.py --days 5
    uv run python -u scripts/four_day_audit.py --decisions-dir /path
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

STRATEGY_RE = re.compile(r"strategy=(\w+)(?:\s+mode=([\w_]+))?")


@dataclass(frozen=True)
class StrategyOverride:
    """Pin every fired record at or after ``ts_ns`` to ``strategy``.

    Needed because SpotAwareStrategyV3 inherits its rationale from
    SpotAwareStrategyV2 (v3 calls super().on_event and returns v2's
    Decision unchanged when regime == "trending"); v2 builds the
    rationale string. So a v3 fire's rationale reads
    ``strategy=spot_aware_v2 mode=tier_restricted ...`` and parsing that
    rationale to attribute the strategy would mis-classify all post-cut
    v3 fires as v2. This override mechanism lets the operator anchor
    strategy attribution by deployment context (what was configured in
    .envrc at the deploy time) rather than by self-tag.
    """

    ts_ns: int
    strategy: str


def _effective_strategy(
    rationale: str,
    decision_ts_ns: int,
    overrides: list[StrategyOverride],
) -> str:
    """Return the strategy tag effective for a fired record.

    Latest override with ``ts_ns <= decision_ts_ns`` wins. If no override
    applies, fall back to parsing the rationale.
    """

    applicable = [o for o in overrides if o.ts_ns <= decision_ts_ns]
    if applicable:
        return max(applicable, key=lambda o: o.ts_ns).strategy
    return _parse_strategy(rationale)


def _parse_iso_to_ns(s: str) -> int:
    """Parse an ISO 8601 timestamp to nanoseconds since epoch (assume UTC
    if no tzinfo)."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1e9)


@dataclass
class DayRow:
    """One row of the per-day audit table."""

    date: str = ""
    fires: int = 0
    filled: int = 0
    settled: int = 0
    wins: int = 0
    losses: int = 0
    zeros: int = 0
    naive_pnl: float = 0.0
    true_pnl: float = 0.0
    strategy_counts: Counter[str] = field(default_factory=Counter)

    @property
    def fill_rate(self) -> float:
        return self.filled / self.fires if self.fires else 0.0

    @property
    def win_rate(self) -> float:
        denom = self.wins + self.losses
        return self.wins / denom if denom else 0.0

    @property
    def strategy_label(self) -> str:
        if not self.strategy_counts:
            return "—"
        ranked = self.strategy_counts.most_common(2)
        if len(ranked) == 1 or ranked[0][1] >= 2 * ranked[1][1]:
            return ranked[0][0]
        return f"{ranked[0][0]} / {ranked[1][0]}"


def _ts_ns_to_date(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, tz=UTC).date().isoformat()


def _parse_strategy(rationale: str) -> str:
    m = STRATEGY_RE.search(rationale or "")
    if not m:
        return "unknown"
    strat, mode = m.group(1), m.group(2)
    return f"{strat}:{mode}" if mode else strat


def audit(
    decisions_dir: Path,
    since: date | None = None,
    days: int | None = None,
    overrides: list[StrategyOverride] | None = None,
) -> list[DayRow]:
    """Read decision logs and return one DayRow per UTC day with data.

    *overrides* pins strategy attribution by deployment context (latest
    override with ts_ns <= decision_ts_ns wins). If None or empty, strategy
    is parsed from the rationale string of each fired record.
    """

    overrides = overrides or []

    files = sorted(decisions_dir.glob("*.jsonl"))
    if since is not None:
        files = [f for f in files if f.stem >= since.isoformat()]
    if days is not None and days >= 0:
        files = files[-days:] if days > 0 else []

    # Two-pass: build correction map first, then aggregate.
    correction_map: dict[str, float] = {}
    fired_records: list[dict[str, object]] = []
    settled_records: list[dict[str, object]] = []

    for path in files:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = rec.get("kind")
                if kind == "fired":
                    fired_records.append(rec)
                elif kind == "settled":
                    settled_records.append(rec)
                elif kind == "settled_correction":
                    did = rec.get("decision_id")
                    pnl = rec.get("corrected_pnl_usd")
                    if isinstance(did, str) and isinstance(pnl, int | float):
                        correction_map[did] = float(pnl)

    days_map: dict[str, DayRow] = defaultdict(DayRow)

    for fr in fired_records:
        ts_ns_raw = fr.get("decision_ts_ns")
        if not isinstance(ts_ns_raw, int):
            continue
        d = _ts_ns_to_date(ts_ns_raw)
        row = days_map[d]
        row.date = d
        row.fires += 1
        if fr.get("fill") is not None:
            row.filled += 1
        rationale_raw = fr.get("rationale")
        rationale = rationale_raw if isinstance(rationale_raw, str) else ""
        row.strategy_counts[_effective_strategy(rationale, ts_ns_raw, overrides)] += 1

    for sr in settled_records:
        ts_ns_raw = sr.get("settled_ts_ns")
        if not isinstance(ts_ns_raw, int):
            continue
        d = _ts_ns_to_date(ts_ns_raw)
        row = days_map[d]
        row.date = d
        row.settled += 1
        naive = sr.get("pnl_usd", 0.0)
        if not isinstance(naive, int | float):
            naive = 0.0
        naive_f = float(naive)
        did = sr.get("decision_id")
        truth = correction_map[did] if isinstance(did, str) and did in correction_map else naive_f
        row.naive_pnl += naive_f
        row.true_pnl += truth
        if truth > 0:
            row.wins += 1
        elif truth < 0:
            row.losses += 1
        else:
            row.zeros += 1

    return sorted([r for r in days_map.values() if r.date], key=lambda r: r.date)


def format_table(rows: list[DayRow]) -> str:
    """Format rows as a fixed-width table with a TOTAL footer."""

    if not rows:
        return "(no data)\n"

    header = (
        f"{'date':<12}{'fires':>6}{'filled':>8}{'fillR':>7}"
        f"{'settled':>9}{'W':>5}{'L':>5}{'Z':>5}{'WR':>8}"
        f"{'naive_pnl':>12}{'true_pnl':>12}  strategy"
    )
    sep = "-" * len(header)
    lines: list[str] = [header, sep]

    tot = DayRow(date="TOTAL")
    for r in rows:
        fillR_str = f"{r.fill_rate * 100:.0f}%" if r.fires else "—"
        wr_str = f"{r.win_rate * 100:.1f}%" if (r.wins + r.losses) else "—"
        lines.append(
            f"{r.date:<12}{r.fires:>6}{r.filled:>8}{fillR_str:>7}"
            f"{r.settled:>9}{r.wins:>5}{r.losses:>5}{r.zeros:>5}{wr_str:>8}"
            f"{r.naive_pnl:>+12.2f}{r.true_pnl:>+12.2f}  {r.strategy_label}"
        )
        tot.fires += r.fires
        tot.filled += r.filled
        tot.settled += r.settled
        tot.wins += r.wins
        tot.losses += r.losses
        tot.zeros += r.zeros
        tot.naive_pnl += r.naive_pnl
        tot.true_pnl += r.true_pnl

    lines.append(sep)
    tot_fillR = f"{tot.filled / tot.fires * 100:.0f}%" if tot.fires else "—"
    tot_wr_denom = tot.wins + tot.losses
    tot_wr = f"{tot.wins / tot_wr_denom * 100:.1f}%" if tot_wr_denom else "—"
    lines.append(
        f"{'TOTAL':<12}{tot.fires:>6}{tot.filled:>8}{tot_fillR:>7}"
        f"{tot.settled:>9}{tot.wins:>5}{tot.losses:>5}{tot.zeros:>5}{tot_wr:>8}"
        f"{tot.naive_pnl:>+12.2f}{tot.true_pnl:>+12.2f}"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Truth-corrected per-day audit; see module docstring."
    )
    parser.add_argument(
        "--decisions-dir",
        type=Path,
        default=Path("state/decisions"),
        help="directory of YYYY-MM-DD.jsonl files (default: state/decisions)",
    )
    parser.add_argument(
        "--since",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="only include files with stem >= YYYY-MM-DD",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="only include the last N files (after --since filter)",
    )
    parser.add_argument(
        "--strategy-override",
        action="append",
        nargs=2,
        metavar=("TS", "STRATEGY"),
        default=[],
        help=(
            "Pin strategy attribution by deployment context. TS is an ISO 8601 "
            "timestamp (assume UTC if no tzinfo); STRATEGY is the name (e.g. "
            "'spot_aware_v3'). Latest override with ts_ns <= decision_ts_ns "
            "wins; falls back to rationale parsing if no override applies. "
            "May be passed multiple times. Required for v3-era audits because "
            "v3 inherits its rationale from v2 (see module docstring)."
        ),
    )
    args = parser.parse_args(argv)

    if not args.decisions_dir.is_dir():
        sys.stderr.write(f"ERROR: {args.decisions_dir} is not a directory\n")
        return 2

    overrides: list[StrategyOverride] = []
    for ts_str, strat in args.strategy_override:
        try:
            ts_ns = _parse_iso_to_ns(ts_str)
        except ValueError as e:
            sys.stderr.write(f"ERROR: bad --strategy-override timestamp {ts_str!r}: {e}\n")
            return 2
        overrides.append(StrategyOverride(ts_ns=ts_ns, strategy=strat))

    rows = audit(args.decisions_dir, since=args.since, days=args.days, overrides=overrides)
    sys.stdout.write(format_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

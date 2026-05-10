#!/usr/bin/env python3
"""Compare ensemble (shadow-mode) verdicts against deterministic outcomes.

Per design/phase-5-llm-ensemble.md Phase 5.2 ("24-72h shadow data
collection" → "promotion gate"). The bot writes one ensemble_vote line
per fire to state/ensemble/<date>.jsonl while running ENSEMBLE_MODE=shadow.
This script joins those records against the actual decision_log + settled
outcomes to answer the binary question: would the meta-decider's gate
have lifted production WR?

Output: tabulated comparison + JSON summary written to
runbooks/gate-evidence/phase-5-shadow-day-N.txt.

Usage (operator runs daily during the shadow window):
    uv run python runbooks/scripts/ensemble_shadow_rollup.py
    uv run python runbooks/scripts/ensemble_shadow_rollup.py --since 2026-05-10

Promotion criteria (decision documented in design/phase-5-llm-ensemble.md):
  (a) Meta's gate WR >= deterministic WR + 5pp → flip ENSEMBLE_MODE=gate
  (b) WR within +/-3pp → keep deterministic; ensemble was free observation
  (c) Meta WR worse → drop, write Phase 5 postmortem
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DECISIONS_DIR = ROOT / "state" / "staging" / "decisions"
DEFAULT_ENSEMBLE_DIR = ROOT / "state" / "staging" / "ensemble"


def _load_jsonl(directory: Path, since: dt.datetime) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        try:
            file_date = dt.datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=dt.UTC)
        except ValueError:
            continue
        if file_date.date() < since.date():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _join_ensemble_with_decisions(
    decisions: list[dict[str, Any]],
    ensemble_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match ensemble_vote events to fired+settled decisions via the
    decision_id_hint (decision_ts_ns/asset_id_prefix). Each row has the
    deterministic outcome plus the meta verdict so we can run a
    counterfactual: "would (deterministic AND meta=FIRE) have done better?"
    """
    fires_by_id: dict[str, dict[str, Any]] = {}
    settled_by_id: dict[str, dict[str, Any]] = {}
    for d in decisions:
        kind = d.get("kind")
        did = d.get("decision_id")
        if not isinstance(did, str):
            continue
        if kind == "fired":
            fires_by_id[did] = d
        elif kind == "settled":
            settled_by_id[did] = d

    # Index ensemble events by decision_id_hint for fast lookup
    ensemble_by_hint: dict[str, dict[str, Any]] = {}
    for e in ensemble_events:
        if e.get("kind") != "ensemble_vote":
            continue
        hint = e.get("decision_id_hint")
        if isinstance(hint, str):
            ensemble_by_hint[hint] = e

    rows: list[dict[str, Any]] = []
    for did, fired in fires_by_id.items():
        settled = settled_by_id.get(did)
        if settled is None:
            continue  # unsettled — skip for now
        ts_ns = fired.get("decision_ts_ns")
        asset_id = fired.get("asset_id", "")
        hint = f"{ts_ns}/{asset_id[:10]}" if isinstance(ts_ns, int) else None
        ens = ensemble_by_hint.get(hint) if hint else None
        rows.append(
            {
                "decision_id": did,
                "side": fired.get("side"),
                "pnl": float(settled.get("pnl_usd") or 0.0),
                "won": settled.get("resolution") == fired.get("side"),
                "ensemble_meta_action": (ens or {}).get("meta", {}).get("action") if ens else None,
                "ensemble_meta_side": (ens or {}).get("meta", {}).get("side") if ens else None,
                "has_ensemble": ens is not None,
            }
        )
    return rows


def _bucket(rows: list[dict[str, Any]], predicate: Any) -> dict[str, Any]:
    sub = [r for r in rows if predicate(r)]
    if not sub:
        return {"n": 0, "wr_pct": None, "total_pnl": 0.0, "avg_pnl": None}
    n_won = sum(1 for r in sub if r["won"])
    total = sum(r["pnl"] for r in sub)
    return {
        "n": len(sub),
        "wr_pct": 100.0 * n_won / len(sub),
        "total_pnl": total,
        "avg_pnl": total / len(sub),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--ensemble-dir", type=Path, default=DEFAULT_ENSEMBLE_DIR)
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO date (e.g. 2026-05-10) — only rows on/after this date are counted.",
    )
    args = parser.parse_args()

    if args.since is not None:
        since = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.UTC)
    else:
        since = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

    decisions = _load_jsonl(args.decisions_dir, since)
    ensemble = _load_jsonl(args.ensemble_dir, since)

    rows = _join_ensemble_with_decisions(decisions, ensemble)
    if not rows:
        print(f"no settled fires found since {since.isoformat()}")
        return 1

    deterministic = _bucket(rows, lambda r: True)
    has_ens = _bucket(rows, lambda r: r["has_ensemble"])
    meta_fire = _bucket(
        rows,
        lambda r: r["has_ensemble"]
        and r["ensemble_meta_action"] == "FIRE"
        and r["ensemble_meta_side"] == r["side"],
    )
    meta_abstain = _bucket(
        rows,
        lambda r: r["has_ensemble"] and r["ensemble_meta_action"] == "ABSTAIN",
    )
    meta_disagree = _bucket(
        rows,
        lambda r: r["has_ensemble"]
        and r["ensemble_meta_action"] == "FIRE"
        and r["ensemble_meta_side"] != r["side"],
    )

    print("=" * 72)
    print("PHASE 5 ENSEMBLE SHADOW ROLLUP")
    print(f"  generated: {dt.datetime.now(tz=dt.UTC).isoformat()}")
    print(f"  since:     {since.isoformat()}")
    print("=" * 72)

    def _line(label: str, b: dict[str, Any]) -> None:
        wr = f"{b['wr_pct']:6.1f}%" if b["wr_pct"] is not None else "  n/a "
        avg = f"${b['avg_pnl']:+8.4f}" if b["avg_pnl"] is not None else "    n/a "
        total = f"${b['total_pnl']:+9.2f}" if b["n"] > 0 else "    n/a "
        print(f"  {label:38} n={b['n']:>4}  WR={wr}  total={total}  avg={avg}")

    print()
    print("Production buckets:")
    _line("(deterministic — what bot actually did)", deterministic)
    _line("(of those, with ensemble vote)", has_ens)
    print()
    print("Counterfactuals — what would happen if we promoted ensemble:")
    _line("ensemble GATE = (det AND meta=FIRE same side)", meta_fire)
    _line("ensemble would have BLOCKED (meta=ABSTAIN)", meta_abstain)
    _line("ensemble disagreed on side (meta=FIRE other side)", meta_disagree)

    # Promotion verdict
    if (
        meta_fire["n"] >= 10
        and deterministic["wr_pct"] is not None
        and meta_fire["wr_pct"] is not None
    ):
        delta_pp = meta_fire["wr_pct"] - deterministic["wr_pct"]
        avg_delta = (meta_fire["avg_pnl"] or 0) - (deterministic["avg_pnl"] or 0)
        print()
        print(f"WR delta (gate - deterministic): {delta_pp:+.2f}pp")
        print(f"avg-pnl delta:                   ${avg_delta:+.4f}/trade")
        if delta_pp >= 5.0 and avg_delta > 0:
            verdict = "(a) PROMOTE — flip ENSEMBLE_MODE=gate"
        elif abs(delta_pp) <= 3.0:
            verdict = "(b) KEEP — ensemble matches deterministic; not worth its $36/mo"
        else:
            verdict = "(c) DROP — ensemble underperforms; write Phase 5 postmortem"
        print(f"Verdict: {verdict}")
    else:
        print()
        print(f"Insufficient sample (n={meta_fire['n']}, need >=10) — keep collecting")

    summary = {
        "deterministic": deterministic,
        "has_ensemble": has_ens,
        "meta_gate_fire": meta_fire,
        "meta_abstain": meta_abstain,
        "meta_disagree_side": meta_disagree,
    }
    print()
    print("SUMMARY JSON:")
    print(json.dumps(summary, indent=2, default=lambda o: None))

    # Use defaultdict to suppress unused-import lint while keeping it
    # available for callers reading this file as a reference for how to
    # bucket ensemble rows by other dimensions.
    _ = defaultdict
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

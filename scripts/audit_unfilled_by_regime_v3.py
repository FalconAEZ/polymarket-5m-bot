"""Phase 13 revisit (2026-05-12) — slice unfilled fires by REGIME x GATE-MODE.

Builds on `audit_unfilled_v2.py` (gap-bucketing) and `audit_regime_wr.py`
(regime classification) to test the hypothesis that the 2026-05-10
fill-rate drop (68.8%) vs 2026-05-09 (100.0%) was a gate-mode latency
artifact AND that regime correlates with fill outcome.

For each fired record:
  1. Classify outcome (filled_at_fire / filled_at_settle / never_filled
     / no_settle) via the Phase 13 classifier
  2. If never_filled: gap-bucket (0-1c / 1-2c / 2-5c / >5c / floor_guard
     / OTHER)
  3. Classify gate_mode: pre/post 2026-05-10 16:31:15 UTC (= gate-mode
     promotion timestamp)
  4. Classify regime via the LIVE RegimeDetector against binance 1m
     klines (raw VPS ticks not retained on disk)

Output: regime x gate_mode x outcome counts, plus counterfactual W for
the never_filled subsets at each slice. We're hunting for a tractable
subset where forcing fills (via a small price-limit lift) would NOT
dilute the bot's edge.

Decision rule (master plan §4 Phase 13 spec, applied per-slice):
  - W ≥ 50% on n ≥ 20 → SHIPPABLE conditional lift candidate
  - W < 50% OR n < 20 → null for that slice
  - Slices found shippable get listed at the end with the conditional
    env-var design.

Usage:
    python scripts/audit_unfilled_by_regime_v3.py state/staging/decisions/*.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_bot.strategies.regime_detector import RegimeDetector

# Master plan §4 — gate-mode promotion was 2026-05-10 16:31:15 UTC.
# Decisions with decision_ts_ns >= this are "post-gate"; before it are
# "pre-gate" (shadow-mode or off-mode).
GATE_FLIP_NS: int = int(dt.datetime(2026, 5, 10, 16, 31, 15, tzinfo=dt.UTC).timestamp() * 1e9)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEFAULT_KLINES_DIR = Path("state/research/binance_historical")

# Gap buckets in dollars (lower-exclusive, upper-inclusive).
GAP_BUCKETS: list[tuple[str, float, float]] = [
    ("0-1c", 0.0, 0.01),
    ("1-2c", 0.01, 0.02),
    ("2-5c", 0.02, 0.05),
    (">5c", 0.05, math.inf),
]


@dataclass
class SliceStat:
    name: str
    n: int = 0
    n_resolved: int = 0
    n_would_win: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)

    def w(self) -> float | None:
        if self.n_resolved == 0:
            return None
        return self.n_would_win / self.n_resolved

    def wilson95(self) -> tuple[float, float] | None:
        n = self.n_resolved
        if n == 0:
            return None
        p = self.n_would_win / n
        z = 1.96
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return (max(0.0, center - half), min(1.0, center + half))


def _classify_outcome(
    fired: dict[str, Any], settled: dict[str, Any] | None
) -> tuple[str, str | None]:
    """(outcome, gap_bucket_or_None_when_filled)."""
    if fired.get("fill") is not None:
        return ("filled_at_fire", None)
    if settled is None:
        return ("no_settle", None)
    if settled.get("fill_at_settle") is not None:
        return ("filled_at_settle", None)
    # never_filled
    snap = fired.get("snapshot") or {}
    pl = fired.get("price_limit")
    ba = snap.get("best_ask")
    if pl is None or ba is None:
        return ("never_filled", "missing_book")
    gap = ba - pl
    if gap <= 0:
        ask_size = snap.get("ask_size_top")
        if ba <= 0.05 and ask_size is None:
            return ("never_filled", "floor_guard")
        return ("never_filled", "OTHER")
    for name, lo, hi in GAP_BUCKETS:
        if lo < gap <= hi:
            return ("never_filled", name)
    return ("never_filled", "OTHER")


def _would_have_won(fired: dict[str, Any], settled: dict[str, Any] | None) -> bool | None:
    if settled is None:
        return None
    resolution = settled.get("resolution")
    side = fired.get("side")
    if not resolution or not side:
        return None
    return bool(resolution == side)


def _gate_mode(fired_ts_ns: int) -> str:
    return "post-gate" if fired_ts_ns >= GATE_FLIP_NS else "pre-gate"


def _load_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    fired: dict[str, dict[str, Any]] = {}
    settled: dict[str, dict[str, Any]] = {}
    for raw in path.open():
        raw = raw.strip()
        if not raw:
            continue
        try:
            r = json.loads(raw)
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


def _fetch_klines_for_date(date_utc: str, *, cache_dir: Path) -> dict[int, float]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"btcusdt_1m_{date_utc}.parquet"
    if cache_path.exists():
        table = pq.read_table(cache_path)
        return {
            int(ts): float(p)
            for ts, p in zip(
                table["close_ts_ms"].to_pylist(),
                table["close"].to_pylist(),
                strict=True,
            )
        }
    start = dt.datetime.strptime(date_utc, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    end = start + dt.timedelta(days=1)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    print(f"  fetching klines for {date_utc}…", file=sys.stderr)
    out: dict[int, float] = {}
    cursor = start_ms
    while cursor < end_ms:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for bar in data:
            out[int(bar[6])] = float(bar[4])
        cursor = int(data[-1][6]) + 1
        time.sleep(0.05)
    sorted_ts = sorted(out)
    table = pa.table(
        {
            "close_ts_ms": pa.array(sorted_ts, type=pa.int64()),
            "close": pa.array([out[t] for t in sorted_ts], type=pa.float64()),
        }
    )
    pq.write_table(table, cache_path)
    return out


def _classify_regime(fired_ts_ns: int, klines: dict[int, float]) -> str:
    detector = RegimeDetector(min_samples=3)
    fire_ms = fired_ts_ns // 1_000_000
    cutoff_10m_ms = fire_ms - 10 * 60 * 1000
    relevant = sorted((ts, p) for ts, p in klines.items() if cutoff_10m_ms <= ts <= fire_ms)
    for ts_ms, price in relevant:
        detector.observe_spot(ts_ms * 1_000_000, price)
    return detector.classify(fired_ts_ns)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--klines-dir", type=Path, default=DEFAULT_KLINES_DIR)
    args = parser.parse_args()

    # 1. Load all fires + settles across all paths.
    all_fired: dict[str, dict[str, Any]] = {}
    all_settled: dict[str, dict[str, Any]] = {}
    for p in args.paths:
        if not p.exists():
            print(f"WARN: missing {p}", file=sys.stderr)
            continue
        fired, settled = _load_jsonl(p)
        all_fired.update(fired)
        all_settled.update(settled)
    print(f"loaded {len(all_fired)} fires, {len(all_settled)} settles", file=sys.stderr)

    # 2. Fetch klines for relevant dates.
    needed_dates: set[str] = set()
    for fr in all_fired.values():
        d = dt.datetime.fromtimestamp(fr["decision_ts_ns"] / 1e9, dt.UTC).date()
        needed_dates.add(d.isoformat())
        needed_dates.add((d - dt.timedelta(days=1)).isoformat())
    klines: dict[int, float] = {}
    for date_utc in sorted(needed_dates):
        try:
            klines.update(_fetch_klines_for_date(date_utc, cache_dir=args.klines_dir))
        except Exception as exc:
            print(f"  WARN klines {date_utc}: {exc}", file=sys.stderr)
    print(f"loaded {len(klines)} kline closes", file=sys.stderr)

    # 3. Slice: outcome x gate_mode x regime
    # Key shape: (gate_mode, regime, gap_bucket) → SliceStat (for never_filled
    # only). Also count fill rate by (gate_mode, regime).
    never_slices: dict[tuple[str, str, str], SliceStat] = defaultdict(lambda: SliceStat(name=""))
    fill_by_mode_regime: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    for did, fr in all_fired.items():
        sr = all_settled.get(did)
        outcome, bucket = _classify_outcome(fr, sr)
        gate = _gate_mode(int(fr["decision_ts_ns"]))
        regime = _classify_regime(int(fr["decision_ts_ns"]), klines)
        fill_by_mode_regime[(gate, regime)][outcome] += 1
        if outcome != "never_filled" or bucket is None:
            continue
        key = (gate, regime, bucket)
        st = never_slices[key]
        if st.name == "":
            st.name = f"{gate}/{regime}/{bucket}"
        st.n += 1
        won = _would_have_won(fr, sr)
        if won is not None:
            st.n_resolved += 1
            if won:
                st.n_would_win += 1
        if len(st.examples) < 3:
            st.examples.append(
                {
                    "did": did[:8],
                    "win_ts": fr.get("window_ts"),
                    "side": fr.get("side"),
                    "pl": fr.get("price_limit"),
                    "ba": (fr.get("snapshot") or {}).get("best_ask"),
                    "res": sr.get("resolution") if sr else None,
                    "won": won,
                }
            )

    # 4. Output: fill-rate matrix (gate_mode x regime)
    print("\n## FILL RATE by gate_mode x regime\n")
    print(
        "| gate    | regime    |  fired | filled@fire | filled@settle | never_filled | no_settle | fill_rate |"
    )
    print(
        "|---------|-----------|-------:|------------:|--------------:|-------------:|----------:|----------:|"
    )
    for gate in ("pre-gate", "post-gate"):
        for regime in ("trending", "mixed", "chop", "unknown"):
            cnt = fill_by_mode_regime.get((gate, regime))
            if not cnt:
                continue
            n = sum(cnt.values())
            f1 = cnt.get("filled_at_fire", 0)
            f2 = cnt.get("filled_at_settle", 0)
            nv = cnt.get("never_filled", 0)
            ns = cnt.get("no_settle", 0)
            fill_rate = 100 * (f1 + f2) / n if n else 0
            print(
                f"| {gate:<7s} | {regime:<9s} | {n:>6d} | {f1:>11d} | {f2:>13d} | {nv:>12d} | {ns:>9d} | {fill_rate:>8.1f}% |"
            )

    # 5. Output: never_filled buckets sliced by (gate, regime) — looking for
    # tractable subsets where W ≥ 50% AND n ≥ 20.
    print("\n## NEVER_FILLED counterfactual W by gate x regime x gap-bucket\n")
    print(
        "| gate      | regime    | bucket       |   n | n_res | W      | 95% CI         | SHIPPABLE? |"
    )
    print(
        "|-----------|-----------|--------------|----:|------:|-------:|:--------------:|:-----------|"
    )
    shippable: list[SliceStat] = []
    for key in sorted(never_slices, key=lambda k: (k[0], k[1], k[2])):
        st = never_slices[key]
        gate, regime, bucket = key
        w = st.w()
        ci = st.wilson95()
        w_s = f"{100 * w:5.1f}%" if w is not None else "  n/a"
        ci_s = f"[{100 * ci[0]:5.1f},{100 * ci[1]:5.1f}]" if ci else "       n/a       "
        flag = ""
        if bucket in ("0-1c", "1-2c", "2-5c") and st.n_resolved >= 20 and (w or 0) >= 0.50:
            flag = "SHIPPABLE (W≥50% n≥20)"
            shippable.append(st)
        elif bucket in ("0-1c", "1-2c", "2-5c") and st.n_resolved >= 5:
            flag = f"n={st.n_resolved} (need {max(0, 20 - st.n_resolved)} more)"
        elif bucket == "floor_guard":
            flag = "phantom-fill defense (do not chase)"
        print(
            f"| {gate:<9s} | {regime:<9s} | {bucket:<12s} | {st.n:>3d} | {st.n_resolved:>5d} | {w_s} | {ci_s:<14s} | {flag} |"
        )

    # 6. Verdict + design hint
    print("\n## VERDICT\n")
    if shippable:
        print(f"  {len(shippable)} SHIPPABLE slice(s) found (W≥50% on n≥20):")
        for st in shippable:
            print(f"    - {st.name}: n_res={st.n_resolved} W={100 * (st.w() or 0):.1f}%")
        print(
            "\n  → Design a conditional price-limit lift env scoped to "
            "(gate_mode, regime, gap_bucket) matching the shippable slice(s)."
        )
    else:
        # Look for the highest W among insufficient-n slices to flag for waiting.
        flagged = [
            st
            for key, st in never_slices.items()
            if key[2] in ("0-1c", "1-2c", "2-5c") and st.n_resolved >= 5 and (st.w() or 0) >= 0.50
        ]
        if flagged:
            print("  NO SHIPPABLE slices yet, but HIGH-W subsets found below n=20 threshold:")
            for st in flagged:
                print(f"    - {st.name}: n_res={st.n_resolved} W={100 * (st.w() or 0):.1f}%")
            print("\n  → Wait for more data (suggest 5-7 more days), then re-run.")
        else:
            print("  NO SHIPPABLE slices, no high-W insufficient-n slices either.")
            print("  → Phase 13 NULL stands even after regime + gate-mode slicing.")
    # Quiet unused-import safeguard.
    _ = statistics
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

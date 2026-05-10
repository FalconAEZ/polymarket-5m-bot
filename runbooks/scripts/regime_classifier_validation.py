#!/usr/bin/env python3
"""Validates the 5m/10m vol-ratio regime classifier against the existing
fired-decisions dataset BEFORE any production code lands.

Per design/regime_detector.md §"Validation BEFORE implementation" and
phase-prompts/phase-11.a.2-post-incident-2026-05-10.txt Item 5. The
gate is binary:

  (a) Trending bucket WR ≥ chop bucket WR + 8pp AND counterfactual
      (fire only in trending) ≥ +$0.50/trade improvement → IMPLEMENT
  (b) Trending vs chop WR < 8pp → try alternative classifier
  (c) All classifiers fail → revisit signal entirely

DATA NOTE: the design doc references state/ticks/binance/*.parquet
(raw ~1Hz spot ticks). Those captures aren't currently retained on the
VPS — only the live in-memory ring is used by the runner. To make the
validation runnable today, this script fetches binance public 1-minute
klines via the REST API (no auth required) for the fire date range and
computes std over the kline closes within 5m/10m windows. With 5/10
data points per window the std estimate is noisier than from raw ticks,
but the trending-vs-chop separation should still surface IF the
hypothesis is real. If results are inconclusive, re-run with raw tick
data once a capture pipeline is in place.

Output: JSON to stdout with per-bucket stats + verdict; full table
written to runbooks/gate-evidence/regime-classifier-validation.txt.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pyarrow.parquet as pq

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEFAULT_DECISIONS_GLOB = "state/staging/decisions/*.jsonl"
DEFAULT_KLINES_DIR = Path("state/research/binance_historical")
TRENDING_THRESHOLD = 1.20
CHOP_THRESHOLD = 0.80


@dataclass(frozen=True, slots=True)
class Fire:
    decision_id: str
    decision_ts_ns: int
    window_ts: int
    side: str
    settled: bool
    won: bool
    pnl_usd: float


@dataclass(slots=True)
class BucketStats:
    name: str
    fires: list[Fire] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.fires)

    @property
    def n_settled(self) -> int:
        return sum(1 for f in self.fires if f.settled)

    @property
    def n_won(self) -> int:
        return sum(1 for f in self.fires if f.settled and f.won)

    @property
    def win_rate_pct(self) -> float | None:
        if self.n_settled == 0:
            return None
        return 100.0 * self.n_won / self.n_settled

    @property
    def total_pnl(self) -> float:
        return sum(f.pnl_usd for f in self.fires if f.settled)

    @property
    def avg_pnl_per_trade(self) -> float | None:
        if self.n_settled == 0:
            return None
        return self.total_pnl / self.n_settled


def _load_fires(decisions_glob: str) -> list[Fire]:
    fires_by_id: dict[str, dict[str, Any]] = {}
    settled_by_id: dict[str, dict[str, Any]] = {}
    paths = sorted(Path().glob(decisions_glob))
    if not paths:
        raise FileNotFoundError(
            f"no decision-log files match {decisions_glob!r} (run sync_staging.sh first?)"
        )
    for path in paths:
        with path.open() as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                rec = json.loads(raw)
                kind = rec.get("kind")
                did = rec.get("decision_id")
                if not isinstance(did, str):
                    continue
                if kind == "fired":
                    fires_by_id[did] = rec
                elif kind == "settled":
                    settled_by_id[did] = rec

    out: list[Fire] = []
    for did, fired in fires_by_id.items():
        settled = settled_by_id.get(did)
        is_settled = settled is not None
        won = False
        pnl = 0.0
        if settled is not None:
            resolution = settled.get("resolution")
            won = resolution == fired.get("side")
            pnl = float(settled.get("pnl_usd") or 0.0)
        out.append(
            Fire(
                decision_id=did,
                decision_ts_ns=int(fired["decision_ts_ns"]),
                window_ts=int(fired["window_ts"]),
                side=str(fired["side"]),
                settled=is_settled,
                won=won,
                pnl_usd=pnl,
            )
        )
    out.sort(key=lambda f: f.decision_ts_ns)
    return out


def _utc_date(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")


def _fetch_klines_for_date(
    date_utc: str,
    *,
    cache_dir: Path,
    symbol: str = "BTCUSDT",
) -> dict[int, float]:
    """Returns mapping { close_ts_ms: close_price } for one full UTC day
    of 1-minute klines. Cached to parquet on disk; re-fetched on cache
    miss."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol.lower()}_1m_{date_utc}.parquet"
    if cache_path.exists():
        table = pq.read_table(cache_path)
        rows = zip(
            table["close_ts_ms"].to_pylist(),
            table["close"].to_pylist(),
            strict=True,
        )
        return {int(ts): float(p) for ts, p in rows}

    start = datetime.strptime(date_utc, "%Y-%m-%d").replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    print(f"  fetching binance klines for {date_utc} ({symbol})…", file=sys.stderr)
    out: dict[int, float] = {}
    cursor = start_ms
    while cursor < end_ms:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": symbol,
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
            close_ts_ms = int(bar[6])  # binance kline close time
            close = float(bar[4])
            out[close_ts_ms] = close
        last_close_ms = int(data[-1][6])
        cursor = last_close_ms + 1
        time.sleep(0.05)  # courtesy throttle

    # Cache as parquet
    import pyarrow as pa

    sorted_ts = sorted(out)
    table = pa.table(
        {
            "close_ts_ms": pa.array(sorted_ts, type=pa.int64()),
            "close": pa.array([out[t] for t in sorted_ts], type=pa.float64()),
        }
    )
    pq.write_table(table, cache_path)
    print(f"  wrote {len(out)} klines → {cache_path}", file=sys.stderr)
    return out


def _vol_ratio(
    fire_ts_ns: int,
    klines: dict[int, float],
) -> float | None:
    """Compute std(closes_5m) / std(closes_10m) using all klines whose
    close_ts_ms falls within the relevant window ending at fire_ts_ns.
    Returns None if either window has < 3 samples (std unreliable)."""
    fire_ms = fire_ts_ns // 1_000_000
    cutoff_5m_ms = fire_ms - 5 * 60 * 1000
    cutoff_10m_ms = fire_ms - 10 * 60 * 1000
    closes_5m: list[float] = []
    closes_10m: list[float] = []
    for ts_ms, price in klines.items():
        if cutoff_10m_ms <= ts_ms <= fire_ms:
            closes_10m.append(price)
            if ts_ms >= cutoff_5m_ms:
                closes_5m.append(price)
    if len(closes_5m) < 3 or len(closes_10m) < 3:
        return None
    std_5m = statistics.pstdev(closes_5m)
    std_10m = statistics.pstdev(closes_10m)
    if std_10m == 0:
        return None
    return std_5m / std_10m


def _classify(ratio: float | None) -> str:
    if ratio is None:
        return "no-data"
    if ratio > TRENDING_THRESHOLD:
        return "trending"
    if ratio < CHOP_THRESHOLD:
        return "chop"
    return "mixed"


def _format_pct(v: float | None) -> str:
    return f"{v:6.2f}%" if v is not None else "  n/a "


def _format_usd(v: float | None) -> str:
    return f"${v:+8.4f}" if v is not None else "    n/a "


def _build_report(
    fires: list[Fire],
    buckets: dict[str, BucketStats],
    counterfactual: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("REGIME CLASSIFIER VALIDATION (5m/10m vol ratio)")
    lines.append(f"  generated:        {datetime.now(tz=UTC).isoformat()}")
    lines.append(f"  fires examined:   {len(fires)}")
    lines.append(f"  thresholds:       trending > {TRENDING_THRESHOLD} · chop < {CHOP_THRESHOLD}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(
        f"{'BUCKET':12}  {'N':>4} {'SETTLED':>8} {'WIN-RATE':>10} {'TOTAL-PNL':>11} {'AVG/TRADE':>11}"
    )
    for name in ("trending", "mixed", "chop", "no-data"):
        s = buckets[name]
        lines.append(
            f"{name:12}  {s.n:>4} {s.n_settled:>8} "
            f"{_format_pct(s.win_rate_pct):>10} "
            f"{_format_usd(s.total_pnl):>11} "
            f"{_format_usd(s.avg_pnl_per_trade):>11}"
        )
    lines.append("")

    trending = buckets["trending"]
    chop = buckets["chop"]
    if trending.win_rate_pct is not None and chop.win_rate_pct is not None:
        delta = trending.win_rate_pct - chop.win_rate_pct
        lines.append(f"WR delta (trending - chop): {delta:+.2f}pp")
    else:
        lines.append("WR delta: insufficient data for trending or chop bucket")
    lines.append("")
    lines.append("COUNTERFACTUAL: 'fire only in trending' vs current (all-fires)")
    lines.append(
        f"  current   n={counterfactual['current_n']}  total=${counterfactual['current_pnl']:+.4f}  avg=${counterfactual['current_avg']:+.4f}"
    )
    lines.append(
        f"  trending  n={counterfactual['trending_n']}  total=${counterfactual['trending_pnl']:+.4f}  avg=${counterfactual['trending_avg']:+.4f}"
    )
    lines.append(f"  per-trade improvement: ${counterfactual['avg_delta']:+.4f}")
    lines.append("")
    lines.append("VERDICT")
    lines.append(f"  {counterfactual['verdict_letter']}: {counterfactual['verdict']}")
    lines.append("=" * 78)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decisions-glob",
        default=DEFAULT_DECISIONS_GLOB,
        help=f"glob for decision-log JSONLs (default: {DEFAULT_DECISIONS_GLOB!r})",
    )
    parser.add_argument(
        "--klines-dir",
        type=Path,
        default=DEFAULT_KLINES_DIR,
        help=f"binance kline cache dir (default: {DEFAULT_KLINES_DIR})",
    )
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=Path("runbooks/gate-evidence/regime-classifier-validation.txt"),
    )
    args = parser.parse_args()

    fires = _load_fires(args.decisions_glob)
    if not fires:
        print("no fires found", file=sys.stderr)
        return 2
    print(f"loaded {len(fires)} fires", file=sys.stderr)

    # Fetch + cache klines for every UTC date we have a fire on, plus
    # the day before (so the 10-min window can reach back across a
    # midnight boundary).
    needed_dates: set[str] = set()
    for f in fires:
        d = datetime.fromtimestamp(f.decision_ts_ns / 1_000_000_000, tz=UTC).date()
        needed_dates.add(d.isoformat())
        needed_dates.add((d - timedelta(days=1)).isoformat())

    klines_all: dict[int, float] = {}
    for date_utc in sorted(needed_dates):
        try:
            day = _fetch_klines_for_date(date_utc, cache_dir=args.klines_dir)
        except Exception as exc:
            print(f"  WARN: failed to fetch klines for {date_utc}: {exc}", file=sys.stderr)
            continue
        klines_all.update(day)
    print(f"loaded {len(klines_all)} kline closes", file=sys.stderr)

    buckets = {name: BucketStats(name=name) for name in ("trending", "mixed", "chop", "no-data")}
    for fire in fires:
        ratio = _vol_ratio(fire.decision_ts_ns, klines_all)
        regime = _classify(ratio)
        buckets[regime].fires.append(fire)

    # Counterfactual: current = all fires; trending = only trending bucket.
    current_settled = [f for f in fires if f.settled]
    trending_settled = [f for f in buckets["trending"].fires if f.settled]
    current_pnl = sum(f.pnl_usd for f in current_settled)
    trending_pnl = sum(f.pnl_usd for f in trending_settled)
    current_avg = current_pnl / len(current_settled) if current_settled else 0.0
    trending_avg = trending_pnl / len(trending_settled) if trending_settled else 0.0
    avg_delta = trending_avg - current_avg

    trending_wr = buckets["trending"].win_rate_pct
    chop_wr = buckets["chop"].win_rate_pct
    wr_delta = trending_wr - chop_wr if (trending_wr is not None and chop_wr is not None) else None

    if wr_delta is not None and wr_delta >= 8.0 and avg_delta >= 0.50:
        verdict_letter = "(a)"
        verdict = (
            "HYPOTHESIS CONFIRMED — trending bucket beats chop by "
            f"{wr_delta:.2f}pp WR and counterfactual improves per-trade pnl by "
            f"${avg_delta:+.4f}. Implement the regime detector."
        )
    elif wr_delta is None or wr_delta < 8.0:
        verdict_letter = "(b)"
        verdict = (
            "HYPOTHESIS NOT CONFIRMED at the 5m/10m vol-ratio classifier — "
            "WR delta below the 8pp threshold. Try an alternative classifier "
            "(Hurst, ADX, spot-persistence) before abandoning."
        )
    else:
        verdict_letter = "(c)"
        verdict = (
            "WR separates but counterfactual improvement is below $0.50/trade — "
            "regime detection may not provide enough lift; revisit signal."
        )

    counterfactual = {
        "current_n": len(current_settled),
        "current_pnl": current_pnl,
        "current_avg": current_avg,
        "trending_n": len(trending_settled),
        "trending_pnl": trending_pnl,
        "trending_avg": trending_avg,
        "avg_delta": avg_delta,
        "verdict_letter": verdict_letter,
        "verdict": verdict,
    }

    report = _build_report(fires, buckets, counterfactual)
    print(report)

    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_out.write_text(report + "\n")
    print(f"\nfull report → {args.evidence_out}", file=sys.stderr)

    summary = {
        "n_fires": len(fires),
        "buckets": {
            name: {
                "n": s.n,
                "n_settled": s.n_settled,
                "win_rate_pct": s.win_rate_pct,
                "total_pnl": s.total_pnl,
                "avg_pnl_per_trade": s.avg_pnl_per_trade,
            }
            for name, s in buckets.items()
        },
        "wr_delta_trending_minus_chop_pp": wr_delta,
        "counterfactual": counterfactual,
    }
    print("\nSUMMARY JSON:", file=sys.stderr)
    print(json.dumps(summary, indent=2, default=lambda o: None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

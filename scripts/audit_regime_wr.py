"""Phase 15 audit — per-regime WR breakdown to inform REGIME_GATE_ABSTAIN_REGIMES.

Re-runs the regime-classifier hypothesis on bot-staging's ACTUAL fire
distribution (not the historical research data the original validation
in `runbooks/scripts/regime_classifier_validation.py` used) so the
gate's expected lift is grounded in current behavior.

For each fired decision in the supplied JSONL files:
  1. Build a fresh `RegimeDetector` instance and feed it the 1-minute
     BTCUSDT klines covering the 10-minute window ending at fire-time.
     This uses the EXACT live classifier so the audit's verdict applies
     to production behavior without translation.
  2. Classify the regime at the fire's `decision_ts_ns`.
  3. Bucket the (settled) outcome into trending / chop / mixed / unknown.
  4. Aggregate WR + PnL per bucket, plus a per-day breakdown.

Per master plan §4 → Phase 15 gate criterion:
  - chop WR < 50% on n ≥ 30   → strong support → implement abstain={chop}
  - chop WR 50-55%             → marginal → consider trending-only gate
  - chop WR ≥ 55%              → STOP → write null result, advance to Phase 16

Klines are fetched via Binance public API (no auth) and cached as parquet
under `state/research/binance_historical/`. The validation script's cache
is reused, so a rerun is fast.

Usage:
    python scripts/audit_regime_wr.py state/staging/decisions/*.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from polymarket_bot.strategies.regime_detector import RegimeDetector

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
DEFAULT_KLINES_DIR = Path("state/research/binance_historical")
REGIME_ORDER = ("trending", "mixed", "chop", "unknown")


@dataclass(frozen=True, slots=True)
class Fire:
    decision_id: str
    decision_ts_ns: int
    window_ts: int
    side: str
    price_limit: float | None
    settled: bool
    filled: bool
    won: bool
    pnl_usd: float


@dataclass(slots=True)
class RegimeAgg:
    name: str
    n_fired: int = 0
    n_settled: int = 0
    n_won: int = 0
    pnl_usd: float = 0.0

    def wr(self) -> float | None:
        if self.n_settled == 0:
            return None
        return self.n_won / self.n_settled

    def avg_pnl(self) -> float | None:
        if self.n_settled == 0:
            return None
        return self.pnl_usd / self.n_settled

    def wilson95(self) -> tuple[float, float] | None:
        n = self.n_settled
        if n == 0:
            return None
        p = self.n_won / n
        z = 1.96
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
        return (max(0.0, center - half), min(1.0, center + half))


def _load_fires(paths: list[Path]) -> list[Fire]:
    fires: dict[str, dict[str, Any]] = {}
    settled: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            print(f"WARN: missing {path}", file=sys.stderr)
            continue
        with path.open() as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                did = rec.get("decision_id")
                if not isinstance(did, str):
                    continue
                kind = rec.get("kind")
                if kind == "fired":
                    fires[did] = rec
                elif kind == "settled":
                    settled[did] = rec
                elif kind == "settled_correction":
                    base = settled.setdefault(did, {})
                    base.update({k: v for k, v in rec.items() if k != "kind"})

    out: list[Fire] = []
    for did, fr in fires.items():
        sr = settled.get(did)
        taker_fill = fr.get("fill")
        maker_fill = sr.get("fill_at_settle") if sr else None
        is_filled = taker_fill is not None or maker_fill is not None
        is_settled = sr is not None and sr.get("resolution") is not None and is_filled
        won = bool(is_settled and sr is not None and sr.get("resolution") == fr.get("side"))
        pnl = float(sr.get("pnl_usd") or 0.0) if is_settled and sr is not None else 0.0
        out.append(
            Fire(
                decision_id=did,
                decision_ts_ns=int(fr["decision_ts_ns"]),
                window_ts=int(fr["window_ts"]),
                side=str(fr.get("side", "")),
                price_limit=fr.get("price_limit"),
                settled=is_settled,
                filled=is_filled,
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
    """Returns {close_ts_ms: close_price} for one full UTC day of 1-min
    klines. Cached to parquet on disk; re-fetched on cache miss."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{symbol.lower()}_1m_{date_utc}.parquet"
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
            close_ts_ms = int(bar[6])
            close = float(bar[4])
            out[close_ts_ms] = close
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
    print(f"  wrote {len(out)} klines → {cache_path}", file=sys.stderr)
    return out


def _classify_fire(fire: Fire, klines: dict[int, float]) -> str:
    """Builds a fresh RegimeDetector, feeds it the klines that fall within
    the detector's 10-min lookback window ending at fire-time, then calls
    classify(). Uses the production class verbatim so the audit verdict
    applies to live behavior without translation.

    A 1-min kline cadence yields ~5 ticks in the 5-min window and ~10 in
    the 10-min window. `min_samples=3` keeps the cold-start check meaningful
    on this proxy data (raw ticks would give ~300 / ~600). Using the
    classifier's default min_samples (10) would return "unknown" on every
    fire because we only have 10 1-min klines in a 10-min window.
    """
    detector = RegimeDetector(min_samples=3)
    fire_ms = fire.decision_ts_ns // 1_000_000
    cutoff_10m_ms = fire_ms - 10 * 60 * 1000
    relevant = sorted(
        (ts_ms, price) for ts_ms, price in klines.items() if cutoff_10m_ms <= ts_ms <= fire_ms
    )
    for ts_ms, price in relevant:
        detector.observe_spot(ts_ms * 1_000_000, price)
    return detector.classify(fire.decision_ts_ns)


def _bucket_fires(
    fires: list[Fire], klines: dict[int, float]
) -> tuple[dict[str, RegimeAgg], dict[str, str]]:
    """Returns (aggregates, fire_id → regime label)."""
    agg = {name: RegimeAgg(name=name) for name in REGIME_ORDER}
    label_by_id: dict[str, str] = {}
    for fire in fires:
        regime = _classify_fire(fire, klines)
        label_by_id[fire.decision_id] = regime
        cell = agg[regime]
        cell.n_fired += 1
        if fire.settled:
            cell.n_settled += 1
            cell.pnl_usd += fire.pnl_usd
            if fire.won:
                cell.n_won += 1
    return agg, label_by_id


def _print_table(agg: dict[str, RegimeAgg], heading: str) -> None:
    print(f"\n## {heading}\n")
    print(
        "| regime    | n_fired | n_settled | n_won |   WR   | 95% CI (Wilson)  | PnL ($) | avg/trade | gate-criterion       |"
    )
    print(
        "|-----------|--------:|----------:|------:|-------:|:----------------:|--------:|----------:|:---------------------|"
    )
    for name in REGIME_ORDER:
        cell = agg[name]
        if cell.n_fired == 0:
            continue
        wr = cell.wr()
        ci = cell.wilson95()
        avg = cell.avg_pnl()
        wr_s = f"{100 * wr:5.1f}%" if wr is not None else "  n/a"
        ci_s = f"[{100 * ci[0]:5.1f},{100 * ci[1]:5.1f}]" if ci else "       n/a       "
        avg_s = f"${avg:+6.3f}" if avg is not None else "  n/a"
        flag = ""
        if name == "chop" and wr is not None:
            if cell.n_settled < 30:
                flag = "n<30 (insufficient)"
            elif wr < 0.50:
                flag = "STRONG SUPPORT (WR<50%, n≥30)"
            elif wr < 0.55:
                flag = "MARGINAL (consider trending-only)"
            else:
                flag = "STOP — null result"
        print(
            f"| {name:<9s} | {cell.n_fired:>7d} | {cell.n_settled:>9d} | {cell.n_won:>5d} | "
            f"{wr_s} | {ci_s:<16s} | {cell.pnl_usd:>+7.2f} | {avg_s:>9s} | {flag:<20s} |"
        )


def _counterfactual_block(
    fires: list[Fire], label_by_id: dict[str, str], abstain_regimes: set[str]
) -> dict[str, float | int | None]:
    """How would things look if we abstained from `abstain_regimes`?"""
    current_settled = [f for f in fires if f.settled]
    kept_settled = [
        f for f in current_settled if label_by_id.get(f.decision_id) not in abstain_regimes
    ]
    cur_pnl = sum(f.pnl_usd for f in current_settled)
    kept_pnl = sum(f.pnl_usd for f in kept_settled)
    cur_wr = (
        (sum(1 for f in current_settled if f.won) / len(current_settled))
        if current_settled
        else None
    )
    kept_wr = (sum(1 for f in kept_settled if f.won) / len(kept_settled)) if kept_settled else None
    return {
        "current_n_settled": len(current_settled),
        "current_pnl": cur_pnl,
        "current_avg": cur_pnl / len(current_settled) if current_settled else None,
        "current_wr": cur_wr,
        "kept_n_settled": len(kept_settled),
        "kept_pnl": kept_pnl,
        "kept_avg": kept_pnl / len(kept_settled) if kept_settled else None,
        "kept_wr": kept_wr,
        "wr_delta_pp": (
            (kept_wr - cur_wr) * 100 if (kept_wr is not None and cur_wr is not None) else None
        ),
        "pnl_delta": kept_pnl - cur_pnl,
        "avg_delta": (
            (kept_pnl / len(kept_settled) if kept_settled else 0.0)
            - (cur_pnl / len(current_settled) if current_settled else 0.0)
        ),
        "fires_dropped": len(current_settled) - len(kept_settled),
    }


def _print_counterfactual(name: str, cf: dict[str, float | int | None]) -> None:
    print(f"\n### Counterfactual: abstain on {{{name}}}")
    cur_wr = cf["current_wr"]
    kept_wr = cf["kept_wr"]
    cur_avg = cf["current_avg"]
    kept_avg = cf["kept_avg"]
    pp = cf["wr_delta_pp"]
    print(
        f"  current   n_settled={cf['current_n_settled']}  "
        f"WR={100 * cur_wr:5.1f}%  total=${cf['current_pnl']:+.2f}  avg=${cur_avg:+.3f}"
        if cur_wr is not None and cur_avg is not None
        else "  current: n=0"
    )
    print(
        f"  kept      n_settled={cf['kept_n_settled']}  "
        f"WR={100 * kept_wr:5.1f}%  total=${cf['kept_pnl']:+.2f}  avg=${kept_avg:+.3f}"
        if kept_wr is not None and kept_avg is not None
        else "  kept: n=0"
    )
    pp_s = f"{pp:+.2f}pp" if pp is not None else "n/a"
    print(
        f"  delta     WR {pp_s}  total ${cf['pnl_delta']:+.2f}  "
        f"avg ${cf['avg_delta']:+.3f}  dropped {cf['fires_dropped']} fires"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", nargs="+", type=Path)
    parser.add_argument("--klines-dir", type=Path, default=DEFAULT_KLINES_DIR)
    args = parser.parse_args()

    fires = _load_fires(args.decisions)
    if not fires:
        print("no fires found", file=sys.stderr)
        return 2
    print(f"loaded {len(fires)} fires from {len(args.decisions)} file(s)", file=sys.stderr)

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

    agg, label_by_id = _bucket_fires(fires, klines_all)
    _print_table(agg, heading=f"Per-regime WR audit ({len(args.decisions)} day(s), n={len(fires)})")

    fires_by_day: dict[str, list[Fire]] = defaultdict(list)
    for fire in fires:
        fires_by_day[_utc_date(fire.decision_ts_ns)].append(fire)
    for day in sorted(fires_by_day):
        day_fires = fires_by_day[day]
        day_agg, _ = _bucket_fires(day_fires, klines_all)
        _print_table(day_agg, heading=f"  {day} (n={len(day_fires)})")

    cf_chop = _counterfactual_block(fires, label_by_id, {"chop"})
    cf_chop_mixed = _counterfactual_block(fires, label_by_id, {"chop", "mixed"})
    _print_counterfactual("chop", cf_chop)
    _print_counterfactual("chop, mixed", cf_chop_mixed)

    print("\nSUMMARY JSON:")
    summary = {
        "n_fires": len(fires),
        "regimes": {
            name: {
                "n_fired": cell.n_fired,
                "n_settled": cell.n_settled,
                "n_won": cell.n_won,
                "wr": cell.wr(),
                "pnl_usd": cell.pnl_usd,
                "avg_pnl_per_trade": cell.avg_pnl(),
                "wilson_95": cell.wilson95(),
            }
            for name, cell in agg.items()
        },
        "counterfactual_chop": cf_chop,
        "counterfactual_chop_mixed": cf_chop_mixed,
    }
    print(json.dumps(summary, indent=2, default=lambda o: None))

    # Stdout verdict — operator-facing.
    chop = agg["chop"]
    chop_wr = chop.wr()
    print("\nVERDICT (chop-bucket primary gate criterion)")
    if chop_wr is None or chop.n_settled < 30:
        print(
            f"  INSUFFICIENT DATA: chop n_settled={chop.n_settled} (<30). "
            "Defer Phase 15 or extend sample window."
        )
    elif chop_wr < 0.50:
        print(f"  STRONG SUPPORT: chop WR={100 * chop_wr:.2f}% < 50% on n={chop.n_settled} ≥ 30.")
        print("  Recommendation: implement abstain={chop}.")
    elif chop_wr < 0.55:
        print(f"  MARGINAL: chop WR={100 * chop_wr:.2f}% in [50, 55).")
        print("  Recommendation: consider trending-ONLY gate instead.")
    else:
        print(f"  STOP: chop WR={100 * chop_wr:.2f}% ≥ 55%. NULL RESULT.")
        print("  Recommendation: defer Phase 15, advance to Phase 16.")
    # Quiet unused-import safeguard so the import doesn't drift if stats moves.
    _ = statistics
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

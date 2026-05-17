"""Path A rolling-WR + mean-price metrics for the M.5 regime-aware wrapper.

Reads state/decisions/<UTC-date>.jsonl across the last few days to find the
most recent Path A fires (tier 70-85% x side=DOWN), joins them against
settled + settled_correction records (correction-priority for truth), and
computes:

    rolling_wr  = wins / n_settled  over the last `lookback_n` Path A fires
    mean_price  = mean(price_limit) over the same fires

If `n_settled < min_samples`, both fields are None and the M.5 gate
passes-through (cold-start defense). The function is synchronous, never
raises, and runs in the bot's main process (cached by the caller — see
scripts/run_paper.py for the 60s TTL cache).

Design lock: design/M.5-path-a-regime-wrapper.md §4.1.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_bot.tiers import tier_label_for_price

LOG = logging.getLogger("polymarket_bot.strategies.path_a_wr_metrics")

DEFAULT_LOOKBACK_DAYS = 5
DEFAULT_LOOKBACK_N = 30
DEFAULT_MIN_SAMPLES = 20
PATH_A_TIER = "70-85%"
PATH_A_SIDE = "DOWN"


@dataclass(frozen=True)
class PathAMetrics:
    """Snapshot of Path A's rolling WR + mean price at a point in time."""

    rolling_wr: float | None
    mean_price: float | None
    n_settled: int
    n_total_in_buffer: int


def compute_path_a_metrics(
    decisions_root: Path,
    *,
    lookback_n: int = DEFAULT_LOOKBACK_N,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    now_ns: int,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> PathAMetrics:
    """Read decisions logs and compute Path A rolling metrics.

    Args:
        decisions_root: Path to state/decisions/ (contains YYYY-MM-DD.jsonl).
        lookback_n: keep the last N Path A fires.
        min_samples: return None metrics if n_settled is below this floor.
        now_ns: current UTC time in nanoseconds (for lookback-days window).
        lookback_days: search this many days of decision logs.

    Returns:
        PathAMetrics. On any I/O error or no qualifying records, returns
        an empty PathAMetrics (rolling_wr=None, mean_price=None, n=0).
    """
    fires: dict[str, dict[str, object]] = {}
    settled_pnl: dict[str, float] = {}
    settled_outcome: dict[str, str] = {}
    corrections: dict[str, tuple[str, float]] = {}

    # Build the day list we read.
    now_utc = datetime.fromtimestamp(now_ns / 1e9, UTC)
    days = [(now_utc - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(lookback_days + 1)]

    for day in days:
        path = decisions_root / f"{day}.jsonl"
        if not path.exists():
            continue
        try:
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
                    did = rec.get("decision_id")
                    if not isinstance(did, str):
                        continue
                    if kind == "fired":
                        # Filter to Path A at parse time so we don't accumulate non-Path-A.
                        side = rec.get("side")
                        price_limit_raw = rec.get("price_limit")
                        if side != PATH_A_SIDE:
                            continue
                        if not isinstance(price_limit_raw, int | float):
                            continue
                        price_limit = float(price_limit_raw)
                        tier = tier_label_for_price(price_limit)
                        if tier != PATH_A_TIER:
                            continue
                        fires[did] = {
                            "ts_ns": rec.get("decision_ts_ns", 0),
                            "price_limit": price_limit,
                            "side": side,
                        }
                    elif kind == "settled":
                        # Only store if we already saw the fire (else it's a non-Path-A settled).
                        if did in fires:
                            pnl_raw = rec.get("pnl_usd")
                            settled_pnl[did] = (
                                float(pnl_raw) if isinstance(pnl_raw, int | float) else 0.0
                            )
                            res = rec.get("resolution")
                            settled_outcome[did] = res if isinstance(res, str) else ""
                    elif kind == "settled_correction":
                        if did in fires:
                            pnl_raw = rec.get("corrected_pnl_usd")
                            res = rec.get("corrected_resolution")
                            corrections[did] = (
                                res if isinstance(res, str) else "",
                                float(pnl_raw) if isinstance(pnl_raw, int | float) else 0.0,
                            )
        except OSError:
            LOG.warning("path_a_metrics: OSError reading %s", path)
            continue

    # Sort fires by ts_ns descending, keep last lookback_n.
    def _ts_ns_of(d: str) -> int:
        v = fires[d].get("ts_ns") or 0
        return int(v) if isinstance(v, int | float) else 0

    sorted_dids = sorted(fires.keys(), key=_ts_ns_of, reverse=True)
    keep = deque(sorted_dids[:lookback_n])
    keep_set = set(keep)

    n_total = len(keep_set)
    wins = 0
    n_settled = 0
    price_sum = 0.0
    for did in keep_set:
        f = fires[did]
        price_sum += float(f["price_limit"])  # type: ignore[arg-type]
        # Outcome: correction priority.
        if did in corrections:
            outcome = corrections[did][0]
        elif did in settled_outcome:
            outcome = settled_outcome[did]
        else:
            outcome = None
        if outcome is not None:
            n_settled += 1
            if outcome == PATH_A_SIDE:
                wins += 1

    if n_total == 0:
        return PathAMetrics(rolling_wr=None, mean_price=None, n_settled=0, n_total_in_buffer=0)

    mean_price = price_sum / n_total if n_total else None

    if n_settled < min_samples:
        return PathAMetrics(
            rolling_wr=None,
            mean_price=mean_price,
            n_settled=n_settled,
            n_total_in_buffer=n_total,
        )

    rolling_wr = wins / n_settled
    return PathAMetrics(
        rolling_wr=rolling_wr,
        mean_price=mean_price,
        n_settled=n_settled,
        n_total_in_buffer=n_total,
    )

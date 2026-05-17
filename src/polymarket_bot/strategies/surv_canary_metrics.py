"""SURV-cell shift canary — rolling WR + mean-price metrics.

Mirrors path_a_wr_metrics.py but for the SURV slice (tier 30-50% x |Δbps|≥5).
Phase N forensic identified the SURV cell as the dominant peak-to-floor
bleeder (post-peak WR collapsed 60.7% → 46.5% on n=228 fires). Phase J.1.5
folded CH3 (tier 30-50% x |Δ|<5) — so all current live tier-30-50% fires
are SURV-slice; |Δbps| filtering is only needed on the historical
rolling-WR computation, not at fire time.

Reads state/decisions/<UTC-date>.jsonl across the last few days, filters
to SURV (tier=30-50% & |Δbps|≥5 parsed from rationale), joins fires with
settled / settled_correction (correction-priority), and returns:

    rolling_wr  = wins / n_settled  over the last `lookback_n` SURV fires
    mean_price  = mean(price_limit) over the same fires

If `n_settled < min_samples`, rolling_wr is None and the canary gate
passes-through (cold-start defense).

Design lock: design/O.1-surv-cell-shift-canary.md.
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_bot.tiers import tier_label_for_price

LOG = logging.getLogger("polymarket_bot.strategies.surv_canary_metrics")

DEFAULT_LOOKBACK_DAYS = 5
# Parameter sweep on the n=755 forensic data (2026-05-17) chose
# lookback_n=15 + min_samples=10 to react fast to a regime flip.
# Larger windows (45-60) lagged the post-peak collapse by hours and
# captured less of the bleed. design/O.1-surv-cell-shift-canary.md §
# "Backtest gate".
DEFAULT_LOOKBACK_N = 15
DEFAULT_MIN_SAMPLES = 10
DEFAULT_MIN_ABS_DELTA_BPS = 5.0
SURV_TIER = "30-50%"

# Match "delta_bps=+5.03" or "delta_bps=-7.24" in a rationale string.
_DELTA_BPS_RE = re.compile(r"delta_bps=([+-]?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class SurvCanaryMetrics:
    """Snapshot of SURV's rolling WR + mean price at a point in time."""

    rolling_wr: float | None
    mean_price: float | None
    n_settled: int
    n_total_in_buffer: int


def _parse_abs_delta_bps(rationale: str | None) -> float | None:
    if not rationale:
        return None
    m = _DELTA_BPS_RE.search(rationale)
    if not m:
        return None
    try:
        return abs(float(m.group(1)))
    except ValueError:
        return None


def compute_surv_canary_metrics(
    decisions_root: Path,
    *,
    lookback_n: int = DEFAULT_LOOKBACK_N,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    min_abs_delta_bps: float = DEFAULT_MIN_ABS_DELTA_BPS,
    now_ns: int,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> SurvCanaryMetrics:
    """Read decisions logs and compute SURV-slice rolling metrics.

    Args:
        decisions_root: Path to state/decisions/ (contains YYYY-MM-DD.jsonl).
        lookback_n: keep the last N SURV fires.
        min_samples: return None rolling_wr if n_settled is below this floor.
        min_abs_delta_bps: |Δbps| threshold for SURV-slice membership.
        now_ns: current UTC time in nanoseconds (for lookback-days window).
        lookback_days: search this many days of decision logs.

    Returns:
        SurvCanaryMetrics. On any I/O error or no qualifying records,
        returns an empty SurvCanaryMetrics.
    """
    fires: dict[str, dict[str, object]] = {}
    settled_pnl: dict[str, float] = {}
    settled_outcome: dict[str, str] = {}
    corrections: dict[str, tuple[str, float]] = {}

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
                        price_limit_raw = rec.get("price_limit")
                        if not isinstance(price_limit_raw, int | float):
                            continue
                        price_limit = float(price_limit_raw)
                        tier = tier_label_for_price(price_limit)
                        if tier != SURV_TIER:
                            continue
                        # |Δbps| filter on the SURV slice.
                        rationale = rec.get("rationale")
                        abs_db = _parse_abs_delta_bps(
                            rationale if isinstance(rationale, str) else None
                        )
                        if abs_db is None or abs_db < min_abs_delta_bps:
                            continue
                        side_raw = rec.get("side")
                        side = side_raw if isinstance(side_raw, str) else ""
                        fires[did] = {
                            "ts_ns": rec.get("decision_ts_ns", 0),
                            "price_limit": price_limit,
                            "side": side,
                        }
                    elif kind == "settled":
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
            LOG.warning("surv_canary_metrics: OSError reading %s", path)
            continue

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
        if did in corrections:
            outcome = corrections[did][0]
        elif did in settled_outcome:
            outcome = settled_outcome[did]
        else:
            outcome = None
        fire_side = f.get("side")
        fire_side_s = fire_side if isinstance(fire_side, str) else ""
        if outcome is not None and fire_side_s:
            n_settled += 1
            if outcome == fire_side_s:
                wins += 1

    if n_total == 0:
        return SurvCanaryMetrics(rolling_wr=None, mean_price=None, n_settled=0, n_total_in_buffer=0)

    mean_price = price_sum / n_total if n_total else None

    if n_settled < min_samples:
        return SurvCanaryMetrics(
            rolling_wr=None,
            mean_price=mean_price,
            n_settled=n_settled,
            n_total_in_buffer=n_total,
        )

    rolling_wr = wins / n_settled
    return SurvCanaryMetrics(
        rolling_wr=rolling_wr,
        mean_price=mean_price,
        n_settled=n_settled,
        n_total_in_buffer=n_total,
    )

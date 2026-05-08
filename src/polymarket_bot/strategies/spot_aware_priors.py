"""Priors loader for `SpotAwareStrategy` — reads `data/spot_aware_priors.json`.

design/spot_aware_strategy.md §6 locks the shape: a (price-tier, Δ_bps
bucket) → p_win lookup table derived from the 30-day Bonereaper
spot-vs-book join. The strategy refuses to fire on (tier, bucket) pairs
not in the table — conservative-by-default.

The table is versioned in git via a `version` field. A weekly job (out of
scope here) will re-derive the table from accumulated paper-soak data and
emit a candidate JSON for operator review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PRIORS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "spot_aware_priors.json"
)


@dataclass(frozen=True, slots=True)
class _Bucket:
    lo: float
    hi: float

    def contains(self, x: float) -> bool:
        return self.lo <= x < self.hi


@dataclass(frozen=True, slots=True)
class SpotAwarePriors:
    """In-memory immutable view of the priors JSON."""

    version: str
    delta_min_bps: float
    delta_max_bps: float
    fee_estimate_pct: float
    ev_min_dollars_per_share: float
    _table: dict[str, float]
    _tier_buckets: tuple[_Bucket, ...]
    _delta_buckets: tuple[_Bucket, ...]

    def lookup(self, *, price: float, abs_delta_bps: float) -> float | None:
        """Return p_win for (price tier, |Δ_bps| bucket); None if unmodelled.

        `price` is the entry price in [0, 1]; `abs_delta_bps` is the
        absolute Δ_bps from window-open spot.
        """
        if abs_delta_bps < self.delta_min_bps or abs_delta_bps > self.delta_max_bps:
            return None
        tier = self._tier_for(price)
        if tier is None:
            return None
        bucket = self._delta_bucket_for(abs_delta_bps)
        if bucket is None:
            return None
        key = f"{tier.lo:.2f}-{tier.hi:.2f}:{int(bucket.lo)}-{int(bucket.hi)}"
        return self._table.get(key)

    def _tier_for(self, price: float) -> _Bucket | None:
        for b in self._tier_buckets:
            if b.contains(price):
                return b
        return None

    def _delta_bucket_for(self, abs_delta_bps: float) -> _Bucket | None:
        for b in self._delta_buckets:
            if b.contains(abs_delta_bps):
                return b
        return None


def load_priors(path: Path | None = None) -> SpotAwarePriors:
    """Load priors from disk. Defaults to repo-root ``data/spot_aware_priors.json``."""
    p = path if path is not None else DEFAULT_PRIORS_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    table: dict[str, float] = {}
    for k, v in raw["priors"].items():
        if not isinstance(v, dict):
            raise ValueError(f"prior entry {k!r} is not an object: {v!r}")
        p_win = v.get("p_win")
        if not isinstance(p_win, int | float):
            raise ValueError(f"prior entry {k!r} missing numeric p_win: {v!r}")
        table[k] = float(p_win)
    tier_buckets = tuple(_Bucket(lo=float(lo), hi=float(hi)) for lo, hi in raw["tier_buckets_pct"])
    delta_buckets = tuple(
        _Bucket(lo=float(lo), hi=float(hi)) for lo, hi in raw["delta_buckets_bps"]
    )
    return SpotAwarePriors(
        version=str(raw["version"]),
        delta_min_bps=float(raw["delta_min_bps"]),
        delta_max_bps=float(raw["delta_max_bps"]),
        fee_estimate_pct=float(raw["fee_estimate_pct"]),
        ev_min_dollars_per_share=float(raw["ev_min_dollars_per_share"]),
        _table=table,
        _tier_buckets=tier_buckets,
        _delta_buckets=delta_buckets,
    )

"""Entry-price tier definitions — single source of truth for tier labels.

A trade's "tier" is the bucket its entry price (best_ask at fire time,
i.e. `Decision.price_limit`) falls into. Tiers are observational
shorthand for "what does the market think the win probability is?" —
e.g. a 30-50% tier means we're paying $0.30-0.50 to win $1.00 if our
side resolves.

Both the dashboard's per-tier WR panel (`dashboard.loaders`) and the
EnsembleWrapper's `TIER_GATE_BLOCKLIST` consume these constants. Keep
them here so a future bucket boundary change updates both call sites
atomically.
"""

from __future__ import annotations

# (lower-inclusive, upper-exclusive, label). 1.01 upper on the top bucket
# captures the degenerate price=1.00 edge case (rare but possible at the
# saturated-market frontier).
PRICE_TIER_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
)

TIER_LABELS: frozenset[str] = frozenset(label for _, _, label in PRICE_TIER_BUCKETS)
UNKNOWN_TIER_LABEL: str = "—"


def tier_label_for_price(price: float | None) -> str:
    """Return the tier label for `price`, or `UNKNOWN_TIER_LABEL` if None / out of range."""
    if price is None:
        return UNKNOWN_TIER_LABEL
    for lo, hi, label in PRICE_TIER_BUCKETS:
        if lo <= price < hi:
            return label
    return UNKNOWN_TIER_LABEL

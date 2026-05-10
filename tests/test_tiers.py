"""Boundary tests for polymarket_bot.strategies.tiers.

Locks the bucket edges so a future refactor of either the dashboard
per-tier panel or the EnsembleWrapper tier-gate cannot silently drift.
"""

from __future__ import annotations

import pytest

from polymarket_bot.tiers import (
    PRICE_TIER_BUCKETS,
    TIER_LABELS,
    UNKNOWN_TIER_LABEL,
    tier_label_for_price,
)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.00, "<15%"),
        (0.14999, "<15%"),
        (0.15, "15-30%"),
        (0.29999, "15-30%"),
        (0.30, "30-50%"),
        (0.49999, "30-50%"),
        (0.50, "50-70%"),
        (0.55, "50-70%"),
        (0.69999, "50-70%"),
        (0.70, "70-85%"),
        (0.84999, "70-85%"),
        (0.85, "85-100%"),
        (1.00, "85-100%"),
        (1.005, "85-100%"),
    ],
)
def test_tier_label_for_price_boundaries(price: float, expected: str) -> None:
    assert tier_label_for_price(price) == expected


def test_tier_label_for_price_none_is_unknown() -> None:
    assert tier_label_for_price(None) == UNKNOWN_TIER_LABEL


def test_tier_label_for_price_out_of_range_is_unknown() -> None:
    # Beyond the top bucket's upper bound — should fall through to unknown.
    assert tier_label_for_price(1.5) == UNKNOWN_TIER_LABEL
    assert tier_label_for_price(-0.1) == UNKNOWN_TIER_LABEL


def test_tier_labels_set_matches_buckets() -> None:
    expected = {label for _, _, label in PRICE_TIER_BUCKETS}
    assert TIER_LABELS == frozenset(expected)


def test_bucket_count_is_stable() -> None:
    # Sanity guard: if a future change adds/removes buckets, the gate-mode
    # operator playbook + dashboard column-set may need updating.
    assert len(PRICE_TIER_BUCKETS) == 6

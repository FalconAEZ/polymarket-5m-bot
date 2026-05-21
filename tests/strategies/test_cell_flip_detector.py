"""Tests for polymarket_bot.strategies.cell_flip_detector.

Phase T Improvement #2. Detector logic + history + cell-key formula.
Strategy-integration tests live in test_spot_aware_v2_1.py (the SURV-flip
reproduction lands there since it needs the full fire-path)."""

from __future__ import annotations

from collections import deque

import pytest

from polymarket_bot.strategies.cell_flip_detector import (
    CellFireHistory,
    CellFlipDetector,
)

# ---------- CellFlipDetector — pure logic ----------


def test_below_min_samples_never_abstains() -> None:
    """Detector requires at least min_samples observations before it will
    ever abstain. With n=5 and min_samples=10, even all losses (rolling_wr=0)
    must NOT abstain — the bot is still in the early-data noise band."""
    d = CellFlipDetector(window_size=20, abstain_threshold_pp=5.0, min_samples=10)
    abstain, reason = d.should_abstain(fill_price=0.50, recent_wins=[False] * 5)
    assert abstain is False
    assert reason == ""


def test_above_break_even_no_abstain() -> None:
    """n=20, WR=70%, fill_price=0.50 → break_even=0.50, threshold=0.45.
    rolling_wr (0.70) >= threshold (0.45). MUST NOT abstain."""
    d = CellFlipDetector(window_size=20, abstain_threshold_pp=5.0, min_samples=10)
    wins = [True] * 14 + [False] * 6
    abstain, _ = d.should_abstain(fill_price=0.50, recent_wins=wins)
    assert abstain is False


def test_within_threshold_no_abstain() -> None:
    """n=20, WR=46%, fill_price=0.50, threshold_pp=5 → threshold=0.45.
    rolling_wr (0.46) > threshold (0.45) by 1pp. Inside the noise band;
    MUST NOT abstain. The 5pp tolerance exists exactly for this case."""
    d = CellFlipDetector(window_size=20, abstain_threshold_pp=5.0, min_samples=10)
    wins = [True] * 9 + [False] * 11
    abstain, _ = d.should_abstain(fill_price=0.50, recent_wins=wins)
    assert abstain is False


def test_beyond_threshold_abstains() -> None:
    """n=20, WR=40%, fill_price=0.50, threshold_pp=5 → threshold=0.45.
    rolling_wr (0.40) < threshold (0.45) by 5pp. MUST abstain with a
    machine-parseable reason string."""
    d = CellFlipDetector(window_size=20, abstain_threshold_pp=5.0, min_samples=10)
    wins = [True] * 8 + [False] * 12
    abstain, reason = d.should_abstain(fill_price=0.50, recent_wins=wins)
    assert abstain is True
    assert "cell_flip:" in reason
    assert "rolling_wr=0.400" in reason
    assert "be=0.500" in reason


def test_rolling_window_drops_old_data() -> None:
    """n=30: first 10 are losses, last 20 are wins. window_size=20 → only
    the last 20 count → rolling_wr = 1.0 → never abstain. This is the
    'recovered cell' case — old losses must not perpetually block."""
    d = CellFlipDetector(window_size=20, abstain_threshold_pp=5.0, min_samples=10)
    wins = [False] * 10 + [True] * 20
    abstain, _ = d.should_abstain(fill_price=0.80, recent_wins=wins)
    assert abstain is False


def test_invalid_init_rejected() -> None:
    """Init must validate window_size, abstain_threshold_pp, min_samples."""
    with pytest.raises(ValueError, match="window_size must be >= 1"):
        CellFlipDetector(window_size=0)
    with pytest.raises(ValueError, match="abstain_threshold_pp must be in"):
        CellFlipDetector(abstain_threshold_pp=-1.0)
    with pytest.raises(ValueError, match="abstain_threshold_pp must be in"):
        CellFlipDetector(abstain_threshold_pp=101.0)
    with pytest.raises(ValueError, match="min_samples must be >= 1"):
        CellFlipDetector(min_samples=0)
    with pytest.raises(ValueError, match=r"min_samples .* > window_size"):
        CellFlipDetector(window_size=5, min_samples=10)


# ---------- CellFireHistory ----------


def test_history_apply_and_read() -> None:
    """apply_settle appends to the cell's deque; recent_wins reads it back."""
    h = CellFireHistory(max_history_size=10)
    h.apply_settle(cell_key="30-50%|hi", won=True)
    h.apply_settle(cell_key="30-50%|hi", won=False)
    h.apply_settle(cell_key="30-50%|hi", won=True)
    h.apply_settle(cell_key="70-85%|hi", won=False)  # different cell
    assert list(h.recent_wins("30-50%|hi")) == [True, False, True]
    assert list(h.recent_wins("70-85%|hi")) == [False]
    assert h.recent_wins("absent|cell") == ()


def test_history_pending_register_and_pop() -> None:
    """register_pending stores; pop_pending returns + removes the entry."""
    h = CellFireHistory()
    h.register_pending(window_ts=1000, asset_id="tokA", cell_key="30-50%|hi")
    h.register_pending(window_ts=1000, asset_id="tokB", cell_key="70-85%|lo")
    # First pop returns the matching entry
    assert h.pop_pending(window_ts=1000, asset_id="tokA") == "30-50%|hi"
    # Second pop on the same key returns None (already removed)
    assert h.pop_pending(window_ts=1000, asset_id="tokA") is None
    # Other pending still there
    assert h.pop_pending(window_ts=1000, asset_id="tokB") == "70-85%|lo"


def test_history_max_size_bounds_growth() -> None:
    """max_history_size caps each cell's deque. Older entries fall off."""
    h = CellFireHistory(max_history_size=5)
    for _ in range(10):
        h.apply_settle(cell_key="30-50%|hi", won=True)
    assert len(h.recent_wins("30-50%|hi")) == 5


def test_cell_key_for_formula() -> None:
    """Centralized cell-key formula: f'{tier}|{lo|hi}'. hi iff |Δ| >= 5."""
    assert CellFireHistory.cell_key_for(tier="30-50%", abs_d_bps=5.0) == "30-50%|hi"
    assert CellFireHistory.cell_key_for(tier="30-50%", abs_d_bps=4.99) == "30-50%|lo"
    assert CellFireHistory.cell_key_for(tier="70-85%", abs_d_bps=12.3) == "70-85%|hi"
    # Custom threshold
    assert (
        CellFireHistory.cell_key_for(tier="15-30%", abs_d_bps=3.0, hi_threshold=2.0) == "15-30%|hi"
    )


def test_recent_wins_returns_underlying_deque() -> None:
    """recent_wins exposes the deque (read-only contract). Caller can
    iterate but must not mutate. This test only verifies the type +
    identity for the iteration use-case."""
    h = CellFireHistory()
    h.apply_settle(cell_key="30-50%|hi", won=True)
    out = h.recent_wins("30-50%|hi")
    # Either a deque (when cell exists) or a tuple (when absent).
    assert isinstance(out, deque | tuple)
    assert all(isinstance(w, bool) for w in out)

"""Tests for polymarket_bot.strategies.j7_priors.J7Priors.

Covers (a) the loader's path-resolution + schema validation, and (b)
the bet_size pipeline's clamp-and-abstain behavior per design/S.1-market-
maker-bot.md §2.3. Tests are pure (no MarketEvent / no IO outside tmp paths).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polymarket_bot.strategies.j7_priors import (
    DEFAULT_KELLY_MULT_MMB,
    DEFAULT_MAX_BET_USD_MMB,
    DEFAULT_MIN_BET_USD_MMB,
    J7Priors,
    TierStats,
)

# Fixture data matches the schema in design/j7_priors.json with a
# minimal 3-tier slice so tests don't depend on the full prod table.
SAMPLE_DATA = {
    "schema_version": 1,
    "name": "j7_priors_test_fixture",
    "source": {"n_trades_joined": 306966},
    "tiers": {
        "<15%": {
            "aligned": {"n": 722, "wr": 0.137, "per_trade_pnl": 8.83},
        },
        "30-50%": {
            "aligned": {"n": 14802, "wr": 0.454, "per_trade_pnl": 1.17},
        },
        "85-100%": {
            "aligned": {"n": 14916, "wr": 0.917, "per_trade_pnl": 0.65},
        },
    },
}


def _write_priors(tmp_path: Path, name: str = "j7_priors.json") -> Path:
    """Write SAMPLE_DATA to tmp_path/name and return the path."""
    path = tmp_path / name
    path.write_text(json.dumps(SAMPLE_DATA))
    return path


# ---------- loader ----------


def test_load_from_bootstrap_when_refresh_missing(tmp_path: Path) -> None:
    """Refresh path missing → loader falls back to bootstrap path."""
    refresh = tmp_path / "refresh.json"  # does not exist
    bootstrap = _write_priors(tmp_path, "bootstrap.json")
    priors = J7Priors.load(refresh_path=refresh, bootstrap_path=bootstrap)
    assert priors.source_path == bootstrap
    assert priors.n_trades_source == 306966
    assert set(priors.tiers.keys()) == {"<15%", "30-50%", "85-100%"}


def test_load_prefers_refresh_when_present(tmp_path: Path) -> None:
    """Refresh path takes precedence over bootstrap when both exist."""
    refresh = _write_priors(tmp_path, "refresh.json")
    bootstrap = _write_priors(tmp_path, "bootstrap.json")
    priors = J7Priors.load(refresh_path=refresh, bootstrap_path=bootstrap)
    assert priors.source_path == refresh


def test_load_raises_when_both_paths_missing(tmp_path: Path) -> None:
    """Both paths missing → FileNotFoundError so we never silently degrade."""
    with pytest.raises(FileNotFoundError, match="neither refresh"):
        J7Priors.load(
            refresh_path=tmp_path / "nope1.json",
            bootstrap_path=tmp_path / "nope2.json",
        )


def test_load_raises_on_missing_tiers_key(tmp_path: Path) -> None:
    """Schema validation: missing top-level 'tiers' key is rejected."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(ValueError, match="missing required 'tiers' key"):
        J7Priors.load(refresh_path=bad, bootstrap_path=bad)


def test_load_raises_on_missing_aligned_row(tmp_path: Path) -> None:
    """Schema validation: per-tier 'aligned' row is required."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"tiers": {"<15%": {"contrarian": {"n": 1, "wr": 0.5, "per_trade_pnl": 0.0}}}})
    )
    with pytest.raises(ValueError, match="missing 'aligned' row"):
        J7Priors.load(refresh_path=bad, bootstrap_path=bad)


# ---------- aligned_wr ----------


def test_aligned_wr_returns_value_for_known_tier(tmp_path: Path) -> None:
    """Headline production figures must come through the loader unchanged."""
    path = _write_priors(tmp_path)
    priors = J7Priors.load(refresh_path=path, bootstrap_path=path)
    assert priors.aligned_wr("85-100%") == 0.917
    assert priors.aligned_wr("<15%") == 0.137


def test_aligned_wr_returns_none_for_unknown_tier(tmp_path: Path) -> None:
    """Unknown tier → None (NOT 0). Callers must distinguish missing from zero-edge."""
    path = _write_priors(tmp_path)
    priors = J7Priors.load(refresh_path=path, bootstrap_path=path)
    assert priors.aligned_wr("999%") is None
    assert priors.aligned_wr("") is None


# ---------- bet_size ----------


def _priors(tmp_path: Path, **kwargs: object) -> J7Priors:
    """Helper: load priors from SAMPLE_DATA with optional overrides."""
    path = _write_priors(tmp_path)
    return J7Priors.load(refresh_path=path, bootstrap_path=path, **kwargs)  # type: ignore[arg-type]


def test_bet_size_zero_when_no_edge(tmp_path: Path) -> None:
    """fill_price >= p_win → -EV → abstain (return 0)."""
    priors = _priors(tmp_path)
    # 85-100% tier p_win = 0.917; if fill_price = 0.95 there's no edge.
    assert priors.bet_size(tier="85-100%", fill_price=0.95, bankroll=1000.0) == 0.0


def test_bet_size_zero_when_unknown_tier(tmp_path: Path) -> None:
    """Unknown tier → abstain (return 0). No silent default tier."""
    priors = _priors(tmp_path)
    assert priors.bet_size(tier="50-70%", fill_price=0.50, bankroll=1000.0) == 0.0


def test_bet_size_zero_when_zero_bankroll(tmp_path: Path) -> None:
    """Bankroll <= 0 → abstain even if edge exists."""
    priors = _priors(tmp_path)
    assert priors.bet_size(tier="85-100%", fill_price=0.85, bankroll=0.0) == 0.0


def test_bet_size_zero_on_degenerate_price(tmp_path: Path) -> None:
    """fill_price not in (0, 1) → abstain (avoids division blow-up)."""
    priors = _priors(tmp_path)
    assert priors.bet_size(tier="85-100%", fill_price=0.0, bankroll=1000.0) == 0.0
    assert priors.bet_size(tier="85-100%", fill_price=1.0, bankroll=1000.0) == 0.0
    assert priors.bet_size(tier="85-100%", fill_price=-0.1, bankroll=1000.0) == 0.0


def test_bet_size_clamps_to_max(tmp_path: Path) -> None:
    """Huge edge + big bankroll → clamped to max_bet_usd ($10 live-micro)."""
    priors = _priors(tmp_path)
    # 85-100% tier p_win=0.917; at fill_price=0.50 the edge is enormous.
    # raw_bet = 0.10 x ((0.917-0.50)/(1-0.50)) x 1000 = 0.10 x 0.834 x 1000 = $83.4
    # max_bet_usd default = $10 live-micro.
    bet = priors.bet_size(tier="85-100%", fill_price=0.50, bankroll=1000.0)
    assert bet == DEFAULT_MAX_BET_USD_MMB


def test_bet_size_floors_below_min(tmp_path: Path) -> None:
    """When raw Kelly bet is below MIN_BET, abstain entirely (return 0)."""
    priors = _priors(tmp_path)
    # 85-100% tier p_win=0.917; fill_price=0.915 gives edge of 0.002/0.085 ≈ 0.024.
    # raw_bet = 0.10 x 0.024 x 1000 = $2.4, below the $5 min → abstain.
    bet = priors.bet_size(tier="85-100%", fill_price=0.915, bankroll=1000.0)
    assert bet == 0.0


def test_bet_size_returns_min_when_edge_marginal(tmp_path: Path) -> None:
    """When raw Kelly bet falls between min and the natural raw value,
    the clamp returns min. Verifies the [min, max] band is honored."""
    priors = _priors(tmp_path)
    # Synthesize an edge where raw_bet ≈ $5.5 — just above the $5 min,
    # well below the $10 max. 85-100% p_win=0.917; need raw_bet ≈ $5.5
    # at bankroll=$1000, kelly_mult=0.10 → kelly_f ≈ 0.055 → solve:
    #   (0.917 - p) / (1 - p) = 0.055  →  p = (0.917 - 0.055) / 0.945 ≈ 0.912
    bet = priors.bet_size(tier="85-100%", fill_price=0.912, bankroll=1000.0)
    assert DEFAULT_MIN_BET_USD_MMB <= bet <= DEFAULT_MAX_BET_USD_MMB


# ---------- constructor validation ----------


def test_rejects_bad_kelly_mult() -> None:
    with pytest.raises(ValueError, match="kelly_mult"):
        J7Priors(tiers={}, source_path=Path("x"), kelly_mult=0.0)
    with pytest.raises(ValueError, match="kelly_mult"):
        J7Priors(tiers={}, source_path=Path("x"), kelly_mult=1.5)


def test_rejects_max_below_min() -> None:
    with pytest.raises(ValueError, match="max_bet_usd"):
        J7Priors(tiers={}, source_path=Path("x"), min_bet_usd=10.0, max_bet_usd=5.0)


def test_tier_stats_immutable() -> None:
    """TierStats is frozen so a typo can't mutate the underlying priors."""
    s = TierStats(n=100, wr=0.5, per_trade_pnl=0.3)
    with pytest.raises(AttributeError):
        s.n = 200  # type: ignore[misc]


def test_default_kelly_mult_matches_design() -> None:
    """Hard-coded check: design §2.3 locks live-micro KELLY_MULT at 0.10."""
    assert DEFAULT_KELLY_MULT_MMB == 0.10
    assert DEFAULT_MIN_BET_USD_MMB == 5.0
    assert DEFAULT_MAX_BET_USD_MMB == 10.0

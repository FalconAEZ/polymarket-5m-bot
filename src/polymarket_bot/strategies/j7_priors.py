"""Bonereaper-derived per-tier aligned-WR priors for MarketMakerStrategy.

Locked spec: design/j7_priors.md + design/j7_priors.json (Phase S Session 1).
Source data: runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md
(n=306,966 BTC 5-min trades; aligned-WR sub-population n=101,962 with WR
67.4%; alignment WR gap vs contrarian = +30.9pp). Freshness re-checked
2026-05-19 (`runbooks/study/weekly-audit.md`): direct WR 50.93% on n=21,630
confirms 30d baseline stable, so the priors table is current.

The J.7 priors table is consumed by two distinct strategy classes:

  1. MarketMakerStrategy (Phase S) — per-ladder-level p_win prior for
     Kelly sizing of maker-limit BUY orders. Tier inferred from each
     level's fill_price; alignment is incidental to MMB's mechanic
     because the ladder lives in a tier and inherits that tier's
     aligned-WR as the anchor.

  2. SpotAwareStrategyV2_1 + AdaptivePriors (J.7 sketch, sleep) —
     Bayesian-blended prior with `w_bonereaper=100` per
     design/bonereaper_blended_priors.md §3.2.

This module owns the loader + sizing math only. The Bayesian blend
formula lives in design/adaptive_priors.md and is implemented in J.3
when J.7 ships. Sizing here is standalone Kelly per design/S.1-market-
maker-bot.md §2.3 (KELLY_MULT=0.10 — directional Kelly assumption breaks
at cross-side fills, so MMB is more conservative than v2.1's 0.15x).

Decision #22 carves J7Priors out from decision #19: this module uses
the bonereaper wallet's HISTORICAL AGGREGATE statistics as a prior
anchor in our own strategy. It does not mirror his orders, observe him
in real-time, or react to his behavior. The wallet itself is opaque to
this module; only the digitised per-tier table at design/j7_priors.json
is read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# Per design/S.1-market-maker-bot.md §2.4 (live-micro defaults).
DEFAULT_KELLY_MULT_MMB: Final[float] = 0.10
DEFAULT_MIN_BET_USD_MMB: Final[float] = 5.0
DEFAULT_MAX_BET_USD_MMB: Final[float] = 10.0  # scale-up target: 25.0

# Path-resolution order:
#   1. Daily-refreshed table at state/research/bonereaper/aligned_priors_30d.json
#      (Session 2 builds this refresh script; until then this path is empty)
#   2. Bootstrap table at design/j7_priors.json
# The runtime loader prefers (1) when present so the bot picks up daily
# refreshes without a redeploy. (2) is the committed-to-git snapshot
# locked at Session 1 close so design reviewers can see the priors data.
DEFAULT_REFRESH_PATH: Final[Path] = Path("state/research/bonereaper/aligned_priors_30d.json")
DEFAULT_BOOTSTRAP_PATH: Final[Path] = Path("design/j7_priors.json")


@dataclass(slots=True, frozen=True)
class TierStats:
    """Per-tier aligned-row statistics (n, wr, $/trade)."""

    n: int
    wr: float
    per_trade_pnl: float


@dataclass(slots=True)
class J7Priors:
    """Reader for the per-tier bonereaper aligned-WR priors table.

    Constructed via `J7Priors.load()` which honors the refresh-path → bootstrap-path
    resolution order. Direct construction with `tiers=...` is for tests.
    """

    tiers: dict[str, TierStats]
    source_path: Path
    n_trades_source: int = field(default=0)
    kelly_mult: float = DEFAULT_KELLY_MULT_MMB
    min_bet_usd: float = DEFAULT_MIN_BET_USD_MMB
    max_bet_usd: float = DEFAULT_MAX_BET_USD_MMB

    def __post_init__(self) -> None:
        if not 0 < self.kelly_mult <= 1.0:
            raise ValueError(f"kelly_mult must be in (0, 1]; got {self.kelly_mult}")
        if self.min_bet_usd < 0:
            raise ValueError(f"min_bet_usd must be >= 0; got {self.min_bet_usd}")
        if self.max_bet_usd < self.min_bet_usd:
            raise ValueError(
                f"max_bet_usd ({self.max_bet_usd}) must be >= min_bet_usd ({self.min_bet_usd})"
            )

    @classmethod
    def load(
        cls,
        *,
        refresh_path: Path = DEFAULT_REFRESH_PATH,
        bootstrap_path: Path = DEFAULT_BOOTSTRAP_PATH,
        kelly_mult: float = DEFAULT_KELLY_MULT_MMB,
        min_bet_usd: float = DEFAULT_MIN_BET_USD_MMB,
        max_bet_usd: float = DEFAULT_MAX_BET_USD_MMB,
    ) -> J7Priors:
        """Load priors from the refresh path if present, else the bootstrap path.

        Raises FileNotFoundError if neither path exists. Raises ValueError
        on schema mismatch (any required field missing or non-numeric).
        """
        path = refresh_path if refresh_path.exists() else bootstrap_path
        if not path.exists():
            raise FileNotFoundError(
                f"neither refresh path {refresh_path} nor bootstrap path {bootstrap_path} exists"
            )
        with path.open() as f:
            data = json.load(f)
        if "tiers" not in data:
            raise ValueError(f"{path}: missing required 'tiers' key")
        tiers: dict[str, TierStats] = {}
        for tier_label, tier_data in data["tiers"].items():
            aligned = tier_data.get("aligned")
            if aligned is None:
                raise ValueError(f"{path}: tier {tier_label} missing 'aligned' row")
            for required in ("n", "wr", "per_trade_pnl"):
                if required not in aligned:
                    raise ValueError(f"{path}: tier {tier_label}.aligned missing '{required}'")
            tiers[tier_label] = TierStats(
                n=int(aligned["n"]),
                wr=float(aligned["wr"]),
                per_trade_pnl=float(aligned["per_trade_pnl"]),
            )
        n_source = int(data.get("source", {}).get("n_trades_joined", 0))
        return cls(
            tiers=tiers,
            source_path=path,
            n_trades_source=n_source,
            kelly_mult=kelly_mult,
            min_bet_usd=min_bet_usd,
            max_bet_usd=max_bet_usd,
        )

    def aligned_wr(self, tier: str) -> float | None:
        """Return aligned-row WR for `tier`, or None if tier unknown.

        Tier labels follow design/j7_priors.json schema: '<15%',
        '15-30%', '30-50%', '50-70%', '70-85%', '85-100%'. None is
        returned (not 0) so callers can distinguish 'no data' from
        'zero edge' — MMB treats None as 'skip this level'.
        """
        stats = self.tiers.get(tier)
        return stats.wr if stats is not None else None

    def bet_size(
        self,
        *,
        tier: str,
        fill_price: float,
        bankroll: float,
    ) -> float:
        """Return clamped Kelly bet size in USD for a ladder level.

        Pipeline:
          1. Look up p_win from the aligned-row of `tier`.
          2. Compute Kelly fraction f* = (p_win - fill_price) / (1 - fill_price).
          3. Multiply by `kelly_mult x bankroll`.
          4. Clamp into [min_bet_usd, max_bet_usd].
          5. Return 0.0 if any abstain condition fires:
               - tier unknown
               - bankroll <= 0
               - fill_price out of (0, 1)
               - p_win <= fill_price (no edge, -EV skip per design §2.3)
               - clamped bet < min_bet_usd (below noise floor)
        """
        p_win = self.aligned_wr(tier)
        if p_win is None:
            return 0.0
        if bankroll <= 0:
            return 0.0
        if fill_price <= 0.0 or fill_price >= 1.0:
            return 0.0
        if p_win <= fill_price:
            return 0.0
        kelly_f = (p_win - fill_price) / (1.0 - fill_price)
        raw_bet = self.kelly_mult * kelly_f * bankroll
        clamped = min(self.max_bet_usd, max(self.min_bet_usd, raw_bet))
        # Final abstain: if even the raw_bet was below min, treat as no-fire.
        if raw_bet < self.min_bet_usd:
            return 0.0
        return clamped

"""Kelly fractional sizing configuration for SpotAwareStrategyV2_1.

Per design/spot_aware_v2_1.md CH5-CH6 and pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf §4.

Standard fractional Kelly for a binary payout bet at a given entry
price. `kelly_f` is the unclamped fraction; `bet_size` applies the
operator-chosen multiplier (Q4 default 0.10x), a per-bet absolute cap
(Polymarket retail liquidity ceiling), a per-bet percent-of-bankroll
cap, and a minimum dollar floor below which the strategy abstains
entirely (CH4). The last computed Kelly fraction is cached on the
dataclass for the rationale builder to read; it is *not* thread-shared
state (the bot runs a single asyncio event loop).

Why a separate file rather than inlined in the strategy: tests for
the Kelly math are pure (no MarketEvent setup) and the dataclass is
useful to other future strategies if they adopt sizing too. Decision
#9 already authorized Kelly across the bot.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class KellyConfig:
    """Configuration + math for fractional Kelly sizing.

    Field defaults match Phase H operator sign-off (Q4 = 0.10x Kelly).
    `max_bet_abs` of $500 reflects empirical Polymarket retail liquidity
    at 30-50% tier prices; below that band liquidity tapers. `min_bet_abs`
    of $1 is the abstain floor — bets below this are dropped and the
    strategy returns None so the window can re-evaluate.
    """

    kelly_mult: float = 0.10
    max_bet_pct: float = 0.10
    max_bet_abs: float = 500.0
    min_bet_abs: float = 1.00
    last_kelly_f: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if not 0 < self.kelly_mult <= 1.0:
            raise ValueError(f"kelly_mult must be in (0, 1]; got {self.kelly_mult}")
        if not 0 < self.max_bet_pct <= 0.5:
            raise ValueError(f"max_bet_pct must be in (0, 0.5]; got {self.max_bet_pct}")
        if self.max_bet_abs <= 0:
            raise ValueError(f"max_bet_abs must be > 0; got {self.max_bet_abs}")
        if self.min_bet_abs < 0:
            raise ValueError(f"min_bet_abs must be >= 0; got {self.min_bet_abs}")

    def kelly_f(self, p_win: float, price: float) -> float:
        """Unclamped Kelly fraction for a binary bet paying 1.0 on win.

        Standard formula `f* = (p_win - price) / (1 - price)`. Returns 0
        when there is no edge (`p_win <= price`) or the price is at the
        degenerate boundary (`price <= 0 or price >= 1`).
        """
        if price >= 1.0 or price <= 0.0 or p_win <= price:
            return 0.0
        return (p_win - price) / (1.0 - price)

    def bet_size(self, *, bankroll: float, p_win: float, price: float) -> float:
        """Return the clamped bet size in USD.

        Pipeline: compute `f*`, multiply by `kelly_mult x bankroll`,
        clamp to `max_bet_pct x bankroll`, clamp to `max_bet_abs`, then
        floor: if the clamped bet is below `min_bet_abs` return 0.0
        (the strategy treats 0.0 as abstain — CH4 in v2.1's design).
        Side effect: writes `last_kelly_f` for the rationale builder.
        """
        f = self.kelly_f(p_win, price)
        self.last_kelly_f = f
        if f == 0.0 or bankroll <= 0:
            return 0.0
        bet = bankroll * self.kelly_mult * f
        bet = min(bet, bankroll * self.max_bet_pct, self.max_bet_abs)
        if bet < self.min_bet_abs:
            return 0.0
        return bet

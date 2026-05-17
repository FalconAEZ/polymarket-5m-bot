"""Half-Kelly position sizing — feeds the every-window router's confidence score.

Phase 16.B subsumes the original Phase 18 (Kelly sizing) work. The Kelly
suggestion is one of 5 inputs to the unified confidence score (see
``design/phase-16b-every-window-mode.md`` §3.3, ``W_KELLY=0.15``). The
router applies the final ``$5-$30`` lerp on top; Kelly is a SIGNAL not
the size.

Locked decision #9 revisit: $5 floor preserved as a hard minimum; the
3% bankroll cap below caps the upper end via half-Kelly math (so at
$1000 bankroll the Kelly suggestion never exceeds $30, matching the
router's hard cap).

Pure functions; deterministic; no IO. Used by router.py only.
"""

from __future__ import annotations

# Locked at 3% bankroll per design/phase-16b-every-window-mode.md §3.3.
# At $1000 paper bankroll (decision #10) this caps at $30, matching the
# router's hard cap. Tuned downward via env if a future bankroll change
# warrants tighter sizing.
KELLY_MAX_BANKROLL_PCT: float = 0.03


def kelly_suggested_size_usd(
    p_win: float | None,
    fill_price: float | None,
    bankroll_usd: float,
    fraction: float = 0.5,
    max_bankroll_pct: float = KELLY_MAX_BANKROLL_PCT,
) -> float:
    """Half-Kelly suggested stake in dollars.

    Standard Kelly formula on a binary outcome:

        f* = (p*b - q) / b

    where:
      p = probability of win
      q = 1 - p
      b = payoff odds = (1 - fill_price) / fill_price

    Returns ``f* x fraction x bankroll``, clipped to ``[0, max_pct x
    bankroll]``. Returns ``0.0`` (no suggestion) when:
      - Either input is None
      - p_win <= fill_price (no edge)
      - p_win >= 1.0 (degenerate)
      - fill_price <= 0 (invalid)

    The caller (router.py) normalises this $ amount to ``[0, 1]`` and
    feeds it as the ``W_KELLY`` confidence-score input.
    """
    if p_win is None or fill_price is None:
        return 0.0
    if p_win <= fill_price or p_win >= 1.0 or fill_price <= 0:
        return 0.0
    b = (1.0 - fill_price) / fill_price
    f_star = (p_win * b - (1.0 - p_win)) / b
    f = max(0.0, min(max_bankroll_pct, f_star * fraction))
    return round(f * bankroll_usd, 2)

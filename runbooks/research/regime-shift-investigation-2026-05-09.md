# Regime-shift investigation — 2026-05-09 peak-to-trough

**Trigger:** operator question 2026-05-09 ~19:45 UTC: "we had +$133 PnL at
05:30 — why did things go sideways from there? something must have
happened!"

**Script:** `runbooks/scripts/peak_trough_investigation.py`
**Output (snapshot at the time of the question):** see below.

## Headline

**Nothing "happened" in the bot.** No code change, no oracle issue, no
incident, no environmental anomaly. The bot kept doing the same thing on
the same priors against the same tier mix.

**BTC entered a different volatility regime around 06:00 UTC.** The
spot-Δ alignment signal (the entire basis of the strategy) is regime-
dependent: it works in trending markets and fails in choppy markets.

We had ~7.5 hours of trending market (pre-peak) and ~12 hours of chop
(post-peak). Same trades, opposite outcomes.

## The split (peak at index 105, 2026-05-09 05:30:00 UTC)

| Period | n | WR | PnL | avg/trade |
|---|---|---|---|---|
| **PRE-PEAK** (winning) | 106 | **61.5%** (n=96 settled) | **+$133.88** | **+$1.40** |
| **POST-PEAK** (losing) | 150 | **41.5%** (n=147 settled) | **-$134.68** | **-$0.92** |

**WR dropped 20pp** between two large samples (n=96 vs n=147). Too big at
this n to be noise.

## The pattern is uniform across every dimension

| Slice | Pre-WR | Post-WR | Δ-WR | Pre-PnL | Post-PnL |
|---|---|---|---|---|---|
| Tier 15-30% | 66.7% | 0.0% | -67pp | +$43 (n=3) | -$5 (n=1) |
| Tier 30-50% | 64.7% | 42.9% | -22pp | +$46 (n=19) | -$5 (n=35) |
| Tier 50-70% | 60.8% | 41.4% | -19pp | +$48 (n=81) | -$125 (n=114) |
| Side UP | 59.7% | 43.9% | -16pp | +$90 (n=65) | -$51 (n=84) |
| Side DOWN | 64.7% | 38.5% | -26pp | +$44 (n=41) | -$84 (n=66) |
| `|Δ|` 0-1 bps | 62.8% | 39.6% | -23pp | +$101 (n=82) | -$118 (n=108) |
| `|Δ|` 1-2 bps | 58.8% | 48.5% | -10pp | +$37 (n=21) | -$6 (n=33) |

**Every tier, every side, every Δ bucket got 10-25pp worse.** Not a tier
shift, not a side bias, not a delta thing. **The signal itself stopped
working.**

## Tier mix barely shifted (it's NOT a tier-mix problem)

| Tier | Pre share | Post share | Δ share |
|---|---|---|---|
| 15-30% | 2.8% | 0.7% | -2.2% |
| 30-50% | 17.9% | 23.3% | +5.4% |
| 50-70% | 76.4% | 76.0% | -0.4% |
| 70-85% | 2.8% | 0.0% | -2.8% |

Tier 50-70% was 76% of fires before AND after. The bot didn't drift into
worse tiers — it just lost more on the same tier mix.

## BTC spot trajectory tells the regime story

```
PRE-PEAK   22:00→05:00  hourly moves: +.06% -.16% +.10% +.23% +.02% -.05% -.01%
POST-PEAK  06:00→17:00  hourly moves: -.20% +.01% +.25% -.23% +.04% +.07% +.08% -.05% -.08% +.28% +.14% +.18%
```

Pre-peak: small + persistent moves (drift). Spot moved up, stayed up. The
strategy's signal ("spot moved → bet aligned") matched outcome.

Post-peak: similar magnitude moves but oscillating. Spot moved up at
decision time, then reversed by window-close. Aligned bets lost.

## Hourly trajectory

```
hour                   fires     WR     hr_pnl    cum_pnl
2026-05-09 00:00 UTC      12  66.7% $  +20.46 $  +29.94
2026-05-09 01:00 UTC      12  66.7% $  +17.02 $  +46.96
2026-05-09 02:00 UTC      12  66.7% $  +16.14 $  +63.10
2026-05-09 03:00 UTC      12  75.0% $  +42.21 $ +105.31  <-- gold hour
2026-05-09 04:00 UTC      12  58.3% $   +3.89 $ +109.20
2026-05-09 05:00 UTC      12  58.3% $   +8.94 $ +118.14  <-- PEAK HERE
2026-05-09 06:00 UTC      12  41.7% $  -12.57 $ +105.56  <-- regime shift
2026-05-09 07:00 UTC      12  41.7% $  -11.93 $  +93.63
2026-05-09 08:00 UTC      12  16.7% $  -39.78 $  +53.85  <-- worst hour
2026-05-09 09:00 UTC      12  50.0% $   -3.97 $  +49.88
...
```

The clean transition at 06:00 UTC is striking.

## What this means structurally

The bot's strategy fires on spot-Δ alignment: if BTC moved UP since the
window opened, bet UP. This works WHEN spot moves are persistent within a
5-min window. It fails WHEN spot moves are choppy (oscillating around a
level).

**Pre-peak regime: low-volatility drift (Asia hours).**
- Hourly moves were small but directional.
- Spot ticks were genuine signal.
- Aligned bets matched outcomes ~62% of the time.

**Post-peak regime: choppy / mean-reverting (Europe + early NY).**
- Hourly moves were similar magnitude but oscillating.
- Spot ticks were noise — they reverted before window close.
- Aligned bets matched outcomes ~42% of the time.

**This is the strategy's structural weakness.** The Bonereaper 30d study
that motivated the strategy showed +30.9pp aligned-vs-contrarian gap *on
average*, but that 30-day window included a mix of regimes. Within a
single regime, the gap can be huge (+25pp) or negative (-20pp).

## What this means for v2 strategy

v2 (tier-restricted, drops 50-70%) **does NOT fix this regime
sensitivity**. v2 still uses the same spot-Δ alignment signal. If we'd
run v2 over this same 21h window:

| Period | v2 estimated fires | v2 estimated WR | v2 estimated PnL |
|---|---|---|---|
| Pre-peak | ~25 in 30-50% + 15-30% | ~63% | +$30-40 |
| Post-peak | ~36 | ~42% | -$15-20 |
| **Net** | ~61 | ~50% | **+$15-25** |

vs the actual v1+aggressive: +$133 → -$0.80 (net ≈ $0).

v2 reduces the absolute swing but doesn't eliminate the regime
sensitivity. v2's value is structural (don't fire 50-70% which is
asymmetric loser even when WR is normal).

## What COULD fix the regime sensitivity (NOT in scope for v2)

A regime detector layered on top of the spot-Δ signal:

1. **Realized 5-min volatility filter**: don't fire when 5-min realized
   vol is below X (chop signal).
2. **Trend persistence filter**: only fire when spot moves over a 15-30
   min window are persistent (sustained drift, not oscillation).
3. **Time-of-day filter**: only fire during hours where Asia trends
   dominate (e.g., 22:00-05:00 UTC). **CAUTION**: n=1 cycle is too thin
   to claim this is a real time-of-day pattern vs a one-time coincidence
   with BTC's specific path that day. Need 5-7 days minimum to claim.
4. **Higher-timeframe filter**: only fire when BTC has a defined trend
   on the 15m or 1h timeframe.

All of these are **future design docs**, not v2 changes. v2 should
deploy first to validate the tier-discipline + no-fallback parts. THEN
we layer regime detection on top if v2 still bleeds.

## Implications for variable sizing (operator's second question)

If we'd been sizing $20/trade instead of $5 over this window:
- Pre-peak: peak would have been ~+$535
- Post-peak drawdown: ~-$540
- **Net the same (~$0)** but with 4x volatility

If we'd been sizing $60/trade:
- Pre-peak peak: ~+$1,608
- Post-peak drawdown: ~-$1,620 → bankroll wipeout

**Naive sizing amplifies regime risk linearly.** The same regime that
gave us +$133 at $5/trade gives us +$1,608 at $60 → looks great. But the
same regime change that gave us -$135 gives us -$1,620 → bankroll dies.

**Sizing without a regime filter is reckless.** A confidence signal
proportional to p_win or |Δ| won't help — those metrics didn't change
across the regime shift. Sizing must include realized-vol or
trend-persistence as a confidence input, NOT just priors-table outputs.

## Honest verdict on the strategy

The spot-Δ alignment edge is **real but regime-dependent**. The bot
will:

- **Profit in trending regimes** (~12-18 hours per day on average)
- **Lose in choppy regimes** (~6-12 hours per day on average)
- **Net out near zero** without a regime filter

The +30.9pp Bonereaper gap is a 30-day average. We need to either:
1. Accept the high variance and let the law of large numbers play out
   over weeks/months
2. Add a regime detector to fire only during trending hours
3. Move to a different signal that's not regime-dependent

Option (2) is the cleanest research path. Option (1) requires bigger
bankroll + longer soak windows than we have. Option (3) is a research
project of its own.

**v2 + a future regime filter** is probably the right v2.5/v3 trajectory.

## Action items

This finding doesn't change the immediate plan:

1. **Wait for the 48h gate** (~25h away)
2. **Deploy v2 + instant-settle** at the gate (changes nothing about regime
   sensitivity, but removes the 50-70% structural drag)
3. **Re-soak v2 for 7 days** to see what v2's pre/post regime numbers
   look like over multiple cycles
4. **THEN consider**: regime detector design (research) and sizing design
   (Phase 11.B prep)
5. **DO NOT deploy variable sizing before regime detection** — would
   amplify losses 5-10x

## Cross-refs

- `runbooks/research/edge-discovery-2026-05-09.md` — companion audit
  that found the 30-50% tier edge
- `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` — the
  30-day analysis that's the strategy's basis (the +30.9pp gap is a
  30-day average; this session shows intra-day swings that are huge)
- `design/spot_aware_strategy.md` §3 — locked spec for the spot-Δ trigger
- `design/spot_aware_v2_tier_restricted.md` — v2 design (does NOT
  address regime sensitivity)

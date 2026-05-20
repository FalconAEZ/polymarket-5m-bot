# J.7 priors — bonereaper per-tier aligned-WR table

**Companion to:** [design/j7_priors.json](design/j7_priors.json) (machine-readable form).
**Status:** Phase S Session 1 deliverable · 2026-05-19. Bootstrap table; Session 2 refresh.
**Source data:** [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md) (n=306,966 trades, 30d, +$234,864 gross on $12.13M notional).
**Freshness check:** [runbooks/study/weekly-audit.md](runbooks/study/weekly-audit.md) 2026-05-19 confirms direct WR stable (50.93% on n=21,630 vs 51.7% on the 30d baseline).

## What this file is

The bonereaper wallet `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` produced 306,966 BTC 5-min trades over a 30-day window with measurable structure: aligned-WR (spot-Δ matches bet side) 67.4% vs contrarian-WR 36.4% — a 31pp gap that is the cleanest empirical edge signal we have on this market class. This file digitises the per-tier aligned-WR + $/trade table into:

- **`j7_priors.json`** — machine-readable, loaded by `src/polymarket_bot/strategies/j7_priors.py` (Session 2).
- **`j7_priors.md`** — this file. Human companion + change log.

The table is used by **two distinct strategy classes** for two distinct purposes:

| Consumer | Use |
|---|---|
| **MarketMakerStrategy** (Phase S) | Per-tier `p_win` prior at each ladder level for Kelly sizing of maker-limit BUY orders. Alignment-incidental — the ladder lives in a tier and inherits that tier's aligned-WR as the priors anchor. |
| **SpotAwareStrategyV2_1 + AdaptivePriors** (J.7 sketch, sleep) | Bayesian-blended prior with weight `w_bonereaper=100`. Conditions on alignment at fire time per [design/bonereaper_blended_priors.md](design/bonereaper_blended_priors.md). |

## Headline numbers (cite-ready)

| Sub-population | n | WR | $/trade | gross PnL |
|---|---:|---:|---:|---:|
| All trades (30d) | 306,997 | 51.7% | +$0.77 | +$234,906 |
| Aligned | 101,962 | **67.4%** | +$0.81 | +$83,054 |
| Contrarian | 117,040 | 36.4% | +$0.58 | +$67,310 |
| Flat (\|Δ\|<5 bps) | 87,964 | 53.9% | +$0.96 | +$84,499 |

**Alignment WR gap: +30.9 percentage points.** This is the canonical bench number for "bonereaper has an edge". The 30d audit is the source.

## Per-tier table (the priors)

### Aligned (the row MMB sizes off)

| Tier | n | WR | $/trade | notional |
|---|---:|---:|---:|---:|
| `<15%` | 722 | 13.7% | **+$8.83** | $6,794 |
| `15-30%` | 3,167 | 25.0% | +$0.11 | $37,718 |
| `30-50%` | 14,802 | 45.4% | +$1.17 | $262,680 |
| `50-70%` | 39,681 | 63.1% | +$0.95 | $1,068,239 |
| `70-85%` | 28,674 | 78.0% | +$0.40 | $1,302,481 |
| `85-100%` | 14,916 | 91.7% | +$0.65 | $5,285,199 |

### Contrarian (informational; MMB does not pre-commit to this row)

| Tier | n | WR | $/trade | notional |
|---|---:|---:|---:|---:|
| `<15%` | 16,622 | 9.9% | +$0.50 | $164,751 |
| `15-30%` | 32,174 | 24.4% | +$0.71 | $383,906 |
| `30-50%` | 44,300 | 41.0% | +$0.61 | $736,611 |
| `50-70%` | 19,319 | 58.2% | +$0.17 | $482,580 |
| `70-85%` | 3,740 | 77.9% | +$0.38 | $165,992 |
| `85-100%` | 885 | 92.4% | +$4.99 | $150,150 |

### Flat (informational)

| Tier | n | WR | $/trade | notional |
|---|---:|---:|---:|---:|
| `<15%` | 143 | 10.5% | −$2.75 | $1,558 |
| `15-30%` | 3,523 | 25.6% | +$0.29 | $44,582 |
| `30-50%` | 30,737 | 46.2% | +$1.56 | $569,289 |
| `50-70%` | 47,471 | 58.3% | +$0.68 | $1,197,259 |
| `70-85%` | 5,755 | 75.0% | +$0.39 | $244,621 |
| `85-100%` | 335 | 91.3% | +$4.59 | $28,991 |

## How MMB consumes the table

```python
# pseudocode for MarketMakerStrategy.size_ladder_level
def size_ladder_level(
    tier: str,
    fill_price: float,
    bankroll: float,
    *,
    kelly_mult: float = 0.10,
    min_bet: float = 5.0,
    max_bet: float = 50.0,
) -> float:
    p_win = J7Priors.aligned_wr(tier)   # e.g., 0.917 for "85-100%"
    if p_win is None or p_win <= fill_price:
        return 0.0                       # skip -EV level
    edge = p_win - fill_price            # e.g., 0.917 - 0.85 = 0.067
    kelly_fraction = kelly_mult * edge / (1.0 - fill_price)
    raw_bet = kelly_fraction * bankroll
    return max(min_bet, min(max_bet, raw_bet))
```

`p_win` is the aligned-row WR for the level's tier. The mismatch between MMB's actual cross-population fills (≈51.7% effective WR) and the priors' aligned-WR is acknowledged in [design/S.1-market-maker-bot.md](design/S.1-market-maker-bot.md) §R1 (edge non-transferability). The Session 2 backtest validates whether the priors-as-anchor approach holds in simulation.

## Caveats (from source-audit §)

1. **Spot lookup is forward-fill within 30s.** Edge cases (sparse-tick periods + sub-1-bp moves) can flip an alignment label.
2. **Binance ticks only.** No Coinbase / oracle cross-check.
3. **Captured spot covers a fraction of bonereaper's full activity.** Suggestive, not conclusive.
4. **Δ_bps is computed entry-vs-window-open, not entry-vs-immediate-prior.** Round-trip windows are bucketed as "flat" even when path was volatile.
5. **Fees not subtracted from gross PnL.** Bonereaper's net is lower than the gross numbers above.
6. **Recent-week volume (7d, 2026-05-19) is 21k trades vs 30d run rate of ~70k trades/wk.** Bonereaper's activity may be cycling down — Session 2 should re-derive on the 2026-05-19 trades data for sizing decisions on current regime.

## Operator-correction notes (from this Session 1 review)

The Phase S prompt frames several derived numbers that differ from the source data; capturing here so the design doc stays accurate:

| Prompt claim | Source-of-truth |
|---|---|
| "$760k cumulative bankroll" | $766k is the WEEKLY NOTIONAL TRADED (2026-05-19 audit). Bonereaper's cumulative wallet PnL per the J.7 sketch is "~$700k as of 2026-05-13" — different figure. |
| "$11.6k/wk gross PnL on 1.84% PnL/notional" | The 2026-05-19 audit measures $11k/wk on $766k notional = 1.44% (gross, fees not subtracted). Close to operator's figure; the 1.84% likely comes from a different week's snapshot. |
| "aligned WR 67.4% on n=101,962 (above our 60% gate)" | True for the aligned sub-population. But MMB will fill across all 3 sub-populations; effective MMB WR will be ≈51.7% (the population-weighted figure). |
| "killer cell +$5.15/tr backtest" | Phase Q commit `599b5ff` says **+$3.16/tr on n=226** for the killer cell (MMD=MIXED × DOWN). The +$5.15/tr figure may be a different audit slice — operator confirmation needed. |
| "30.7 trades/window (median 29, p99 71, max 76)" | Not directly verifiable from on-disk data in this Session 1; logged as Session 2 backtest cross-validation item. |

## Refresh schedule

Per [design/bonereaper_blended_priors.md](design/bonereaper_blended_priors.md) §3.4:

- Refresh trigger: daily at 04:00 UTC (cron / systemd timer; not yet wired).
- Refresh script: `scripts/research/refresh_bonereaper_30d.py` (NOT yet written; Session 2 deliverable).
- Output: `state/research/bonereaper/aligned_priors_30d.json` (the file `J7Priors` actually loads at runtime).

This file (`design/j7_priors.json`) is the STATIC BOOTSTRAP version derived from the 2026-05-07 audit. The runtime loader (Session 2) will prefer the daily-refresh JSON if present and fall back to this bootstrap. Bootstrap kept under `design/` so the priors data is reviewable in PRs.

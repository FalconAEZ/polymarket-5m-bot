---
title: Phase 16.B.1 — router counterfactual audit
date: 2026-05-11
tags: [audit, phase-16b, counterfactual]
---

# Phase 16.B.1 — router counterfactual audit

> Synthetic backtest: for each historical fired record, recompute what the
> v2 router (confidence-weighted $5-$30 sizing, hybrid-Kelly) WOULD HAVE
> done and project the PnL delta. **No replay of orderbook depth, no**
> **regime-by-window lookup, no LLM re-run.** This is a first-cut
> projection from the existing fired+settled+correction data.

## Top-line numbers

| Metric | Value |
|---|---:|
| Settled rows audited | **517** |
| Today's actual PnL (corrected) | **+$60.26** |
| Router's projected PnL (same fires + size shaping) | **+$404.18** |
| **Net delta from router** | **+$343.92** |
| Avg router size (vs $5 today) | **$13.67** |
| New fills via taker fallback | **0** |

## Per-tier breakdown

| Tier | n | Actual PnL | Router PnL | Δ | Avg router size |
|---|---:|---:|---:|---:|---:|
| `<15%` | 61 | $-30.01 | +$0.00 | +$30.01 | $9.67 |
| `15-30%` | 8 | +$121.57 | +$485.98 | +$364.42 | $19.57 |
| `30-50%` | 79 | +$43.96 | +$103.51 | +$59.56 | $18.25 |
| `50-70%` | 306 | $-61.54 | $-131.50 | $-69.96 | $12.90 |
| `70-85%` | 19 | $-14.46 | $-55.68 | $-41.22 | $18.08 |
| `85-100%` | 44 | +$0.74 | +$1.86 | +$1.12 | $13.39 |

## Per-`|delta_bps|` breakdown

| Bucket | n | Actual PnL | Router PnL | Δ | Avg router size |
|---|---:|---:|---:|---:|---:|
| `0-1bps` | 315 | $-20.10 | +$61.52 | +$81.62 | $12.83 |
| `1-2bps` | 120 | +$55.87 | +$226.54 | +$170.67 | $14.63 |
| `2-5bps` | 63 | +$16.33 | +$61.24 | +$44.91 | $14.46 |
| `5-10bps` | 19 | +$8.16 | +$54.87 | +$46.71 | $18.94 |

## Confidence-bucket breakdown

| Confidence | n | Avg size | Actual PnL | Router PnL | Δ |
|---|---:|---:|---:|---:|---:|
| `0.0-0.2` | 28 | $0.00 | $-18.34 | +$0.00 | +$18.34 |
| `0.2-0.4` | 314 | $12.64 | $-91.41 | $-223.62 | $-132.21 |
| `0.4-0.6` | 163 | $17.46 | +$150.87 | +$532.42 | +$381.55 |
| `0.6-0.8` | 12 | $20.96 | +$19.13 | +$95.37 | +$76.24 |

## Caveats

- **Regime not per-window:** projection uses `regime=unknown` for all rows. Real router would weight trending stronger and chop weaker. **Expected effect:** router projection is CONSERVATIVE for the trending subset (would have been larger sizes); LIBERAL for the chop subset (smaller).
- **LLM not re-run:** projection uses `llm=0.50` (neutral) for all rows. Real router would size up on high-confidence LLM agreement.
- **p_win not learned:** projection uses tier-derived prior. Real router will use `spot_aware_priors.SpotAwarePriors.lookup`.
- **Taker slippage assumed 1¢ flat.** Real cost is 1-2¢ depending on book depth.
- **Win/loss outcomes are HISTORICAL** (frozen). Size shaping doesn't change whether a window resolved UP or DOWN; it only scales the dollar PnL.

## How to interpret

- **If net delta is POSITIVE** → the size shaping captures more on winners than it loses on losers, even before LLM and regime sharpening. The 7-day soak should improve this.
- **If net delta is NEGATIVE** → first-cut confidence weights are mis-calibrated. Tune `W_DET / W_TIER / W_REG / W_LLM / W_KELLY` and re-run the audit before any code ships.
- **The avg router size** tells us if the confidence math is doing anything: $5 means everything got the floor; $30 means everything got the cap; healthy is ~$12-$18.

## Sub-phase status

- ✅ 16.B.1 — counterfactual audit (this doc)
- ⏳ 16.B.2 — design doc lock at `design/phase-16b-every-window-mode.md`
- ⏳ 16.B.3 — router primitives + `sizing.py` + tests
- ⏳ 16.B.4 — wire into EnsembleWrapper behind `EVERY_WINDOW_MODE=false`
- ⏳ 16.B.5 — dark deploy + 24h shadow mode
- ⏳ 16.B.6 — 7-day soak gate → PROMOTE or ROLLBACK

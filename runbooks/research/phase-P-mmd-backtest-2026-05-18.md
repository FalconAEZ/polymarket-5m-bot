# Phase P Session 2 — MMD backtest report

Generated 2026-05-18 (operator UAE local).  
Settled fires loaded: **n = 756**.  
Klines: Binance BTCUSDT 1m, **8528 bars** from 2026-05-12 00:00:00+00:00 to 2026-05-17 22:07:00+00:00.  

Two candidate Market Mode Detectors backtested:

  - **Adapter A — `bukosabino/ta`** (MIT, pure-Python). Rule-based ADX(14) > 25 trend / momentum sign + BB-width(20, 2σ) < 30bps for chop. Lookback 60 min on 1m bars.
  - **Adapter B — `hmmlearn`** (BSD-3). 4-state Gaussian HMM on (log-return, rolling-10 vol) features. In-sample fit on full 5-day series — known upper bound; Session 3 will retrain on rolling window.

## Adapter A — `bukosabino/ta` rule-based

Label distribution: {'MIXED': 271, 'CHOPPY': 193, 'DOWN': 173, 'UP': 119}

| Label | n | WR | $/tr | PnL | mean conf |
|-------|---|----|------|-----|-----------|
| UP | 119 | 48.7% | $-1.86 | $-222 | 0.62 |
| DOWN | 173 | 53.8% | $-2.03 | $-352 | 0.70 |
| CHOPPY | 193 | 53.9% | $-2.29 | $-443 | 0.40 |
| MIXED | 271 | 57.9% | $+1.94 | $+526 | 0.50 |

**Best vs worst (n ≥ 20):** MIXED WR 57.9% n=271 | UP WR 48.7% n=119 | **gap +9.2pp**

## Adapter B — `hmmlearn` 4-state HMM

HMM state→label map: {0: 'DOWN', 3: 'UP', 1: 'CHOPPY', 2: 'MIXED'}

Label distribution: {'DOWN': 264, 'CHOPPY': 200, 'MIXED': 184, 'UP': 108}

| Label | n | WR | $/tr | PnL | mean conf |
|-------|---|----|------|-----|-----------|
| UP | 108 | 57.4% | $-2.49 | $-269 | 0.96 |
| DOWN | 264 | 53.0% | $-0.78 | $-206 | 0.92 |
| CHOPPY | 200 | 49.5% | $-2.28 | $-457 | 0.96 |
| MIXED | 184 | 60.3% | $+2.40 | $+441 | 0.91 |

**Best vs worst (n ≥ 20):** MIXED WR 60.3% n=184 | CHOPPY WR 49.5% n=200 | **gap +10.8pp**

## Co-occurrence A vs B (rows A, cols B)

| A \ B | UP | DOWN | CHOPPY | MIXED |
|---|---|---|---|---|
| UP | 23 | 49 | 22 | 25 |
| DOWN | 52 | 51 | 18 | 52 |
| CHOPPY | 4 | 76 | 74 | 39 |
| MIXED | 29 | 88 | 86 | 68 |

## Acceptance against prompt P.2.2 USEFUL criterion

Threshold: ≥ 10 pp WR delta between best and worst label on subsamples n ≥ 20.

- Adapter A (ta): gap +9.2pp → **FAIL**
- Adapter B (hmm): gap +10.8pp → **PASS**

Charts at `state/research/phase-P-mmd-charts/`. See PHASE_P_SESSION2_MMD_RESEARCH.pdf for the full study.
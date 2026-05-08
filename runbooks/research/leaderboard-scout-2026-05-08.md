# Polymarket BTC 5-min leaderboard scout

Run date: 2026-05-08. Lookback: 7 days. Markets enumerated: 1949 (sampled: 300). Distinct wallets seen: 17,235. Top 50 by notional re-queried for equity. Filtered to $1,000-$200,000: 7. Elapsed: 55s.

**Goal:** find small-equity wallets ($2k-$50k by default) that are profitably trading BTC 5-min markets at scale — i.e., a more scale-relevant template for our $1k bankroll than Bonereaper's $13M.

## Survivors (ranked by gross PnL on the sample)

Reading the columns: `pseudo` is what predicts.guru/Polymarket shows for the wallet; `equity` is current portfolio value via /value endpoint; `markets` is unique BTC 5m markets touched in the sample; `early%` is share of fills in the first minute of the window (Bonereaper's baseline = 28%); `last60s%` is share in the final 60s. **per-$ PnL** = gross_pnl ÷ notional, the closest single number for our 'who has the cleanest edge per dollar' question.

| rank | wallet | pseudo | equity | trades | markets | win-rate | notional | gross PnL | per-trade | per-$ PnL | early% | last60s% |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `0xeebd…ba30` 🐺 | Popular-Insurrec | $1,282 | 650 | 211 | 54.0% | $191,265 | $+1,702 | $+2.62 | +0.89% | 0.0% | 70.5% |
| 2 | `0xdf0d…9f79` | Slow-Minute | $4,458 | 46 | 37 | 97.8% | $66,953 | $+207 | $+4.50 | +0.31% | 0.0% | 71.7% |
| 3 | `0x88f1…d3d0` | — | $1,137 | 64 | 37 | 98.4% | $7,090 | $+183 | $+2.85 | +2.58% | 0.0% | 21.9% |
| 4 | `0xa8cc…41a9` | Exalted-Mattress | $7,613 | 228 | 106 | 58.8% | $9,384 | $+128 | $+0.56 | +1.36% | 0.0% | 71.9% |
| 5 | `0x9a1d…86d6` | Humble-Outcome | $1,369 | 37 | 22 | 54.1% | $5,735 | $-214 | $-5.78 | -3.73% | 0.0% | 48.6% |
| 6 | `0x129b…9274` | Tan-Hometown | $1,060 | 92 | 18 | 51.1% | $6,095 | $-610 | $-6.63 | -10.00% | 0.0% | 90.2% |
| 7 | `0xe907…cff6` | — | $120,414 | 1,757 | 296 | 22.7% | $51,728 | $-2,105 | $-1.20 | -4.07% | 0.0% | 40.4% |

## Reading the results

- Bonereaper (🐺 marker if present in the table) is our reference. Their per-$ PnL on the same sample is the benchmark to beat. Anyone above is plausibly a better template for OUR scale.
- The `early%` column tests the late-window-sniping hypothesis again. If a wallet has very high `last60s%`, that's a different strategy from Bonereaper and worth deep-analyzing.
- `equity` is current snapshot value. A wallet with $5k equity, 1,000 trades, and +$3k gross PnL on the sample is the dream template.
- Per-$ PnL is gross. Real after-fees PnL is lower. Anything above **+1.5%** is interesting; below **+0.5%** probably isn't.

## Next steps for a candidate

If a wallet looks promising, run the full analysis: pass its address to a `--user` flag (need to extend `bonereaper_microstructure.py` first — currently hardcoded to BONEREAPER_ADDR). For now, manually edit the constant and re-run. Then run `bonereaper_spot_vs_book.py` against the resulting trade dump + the same kline parquet to see if the spot-Δ alignment pattern reproduces.

## Caveats

- Sample-only volume — we don't have the full 30-day picture for non-Bonereaper wallets yet. A wallet that's quietly profitable might show flat numbers if their fills aren't in our sample of markets.
- `equity` is current; a wallet that just cashed out shows $0 even if they made $50k yesterday.
- Some `proxyWallet` addresses are routing/relay infrastructure, not individual operators. Watch for round-trip patterns and add to `EXCLUDE_WALLETS` in this script as we identify them.
- Fees not subtracted from gross PnL. Real after-fees ROI is lower.

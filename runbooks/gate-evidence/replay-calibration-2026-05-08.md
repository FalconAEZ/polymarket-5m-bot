# Replay calibration — DeterministicStrategy threshold sweep

Run date: 2026-05-08 (laptop). Captured-tick dates replayed: 2026-05-06, 2026-05-07.
Driven by operator's 2026-05-08 "what's the point lol" question after live `bot-staging` showed zero decisions in its first 30 minutes. Tool: `scripts/run_replay_calibration.py`.

**Captured-data caveat:** the polymarket parquet for 2026-05-07 (file `polymarket_1778107491.parquet`) was corrupt (`File out of specification: must end with PAR1`); cross-midnight windows were lost. Effective coverage: **28 unique 5-min windows** (~2.3 hours of polymarket book activity), all on 2026-05-06.

| threshold | windows | fires | fill-rate | win-rate | gross-PnL | per-fire |
|---:|---:|---:|---:|---:|---:|---:|
| 0.3pp | 28 | 0 | 0.0% | 0.0% | $+0.00 | $+0.00 |
| 0.4pp | 28 | 0 | 0.0% | 0.0% | $+0.00 | $+0.00 |
| 0.5pp | 28 | 0 | 0.0% | 0.0% | $+0.00 | $+0.00 |
| 0.6pp | 28 | 0 | 0.0% | 0.0% | $+0.00 | $+0.00 |

## Headline finding

**Zero fires at every threshold, including the most permissive 0.3pp.** The DeterministicStrategy's composite signal (window-delta + oracle-gap) does not cross 0.3pp on any of the 28 captured windows. **The threshold is not the bottleneck — the signal itself is producing values too small to matter** on 5-min BTC windows in this captured sample.

## What this implies

1. **"Why isn't bot-staging firing?"** — answered. It's not a 0.6 vs 0.5 calibration question; the signal would be silent at 0.3 too. The locked threshold in decision #6 was *not* set too aggressively.
2. **Decision #16's LLM A/B verdict needs scrutiny.** That verdict cut the ensemble for "not beating the deterministic baseline by 3pp." If the baseline fires 0 times, "beat it" is undefined. Worth a follow-up audit before any Phase 8 ensemble revisit.
3. **Operator's 2026-05-08 Bonereaper market-making hypothesis becomes more plausible.** If 5-min directional signal is this weak in real BTC tick data, microstructure-based strategies (spread capture, two-sided market making) become more attractive than directional prediction.
4. **Decision #19 (Bonereaper cloning study aborted)** may have been *premature* if the cloning model treated Bonereaper as a directional predictor. Their actual strategy looks two-sided per operator's screenshot inspection; un-archiving with a market-maker-shaped clone deserves consideration — but only with a written design doc + new gate per anti-vibe rule #1.

## What this does NOT imply

- Do **not** lower decision #6's threshold reflexively. The signal is weak across all thresholds; lowering it doesn't add signal — it just makes the bot fire on noise.
- Do **not** turn on the Claude ensemble "in case it works." We don't yet have evidence it would.
- Do **not** treat 28 windows as conclusive. This is a 2.3-hour sample on one date with a corrupted second day. Signal could be strongly time-of-day or volatility-regime dependent.

## Honest next steps (prioritised)

1. **Instrument the strategy** to log the composite value on EVERY window (whether it fires or not) so we can see the actual distribution. ~10-line change in `src/polymarket_bot/strategies/deterministic.py`. Re-run replay → produces a histogram. **Cheapest highest-EV step.**
2. **Investigate the composite math.** Read `composite_pct` at `src/polymarket_bot/strategies/deterministic.py:37` and verify it matches design intent. Possible bug in normalisation / scaling.
3. **Capture more data.** The live VPS bot accumulates organic data continuously; another 24-72h gives a much bigger sample.
4. **Bonereaper microstructure analysis** — separate task. Pull on-chain trade history, classify two-sided vs directional, compute spread capture. Answers "are they market making?" with data.

## Reading-the-table guide

`windows` = total 5-min windows in the data. `fires` = how many the strategy decided to bet on. `fill-rate` = of the fires, how many got a simulated fill. `win-rate` = of the fills, how many won. `gross-PnL` = sum of realised PnL on the filled trades (fees included). `per-fire` = gross-PnL ÷ fires (strategy's expected return per signal).

**This is a calibration / decision-support artifact, NOT a strategy change.** Lowering decision #6's locked threshold or un-archiving decision #19 would still require a written `runbooks/decisions/<topic>-revision.md` per anti-vibe rule #1.

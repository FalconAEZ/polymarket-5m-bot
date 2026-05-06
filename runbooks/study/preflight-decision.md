# Bonereaper — Phase A Pre-flight Decision

**Decision:** **ABORT** (do not design Phase B against this wallet)

Generated: 2026-05-06 (UTC)
Wallet: `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` (Polymarket profile: `bonereaper`)

---

## Summary

Two independent data sources both fail the abort gate. The behavioral-study
hypothesis ("bonereaper has a high-accuracy BTC 5-min edge worth cloning")
is not supported by the observable data.

| Source | Window | BTC 5-min trades | Win-rate | Conclusion |
|---|---|---|---|---|
| Polymarket Data API (run 2026-05-05) | last ~3 h (offset cap = 3500) | **1,116** trades (1,083 resolved) | **50.6%** (95% CI ≈ 47.6%–53.6%) | **fails** ≥60% gate by ≥6.4 pp at the upper bound |
| Goldsky orderbook subgraph (run 2026-05-06) | Apr 28–29, 2026 (1.5 days) | **0** | n/a | wallet wasn't on indexed exchange in BTC 5m |

The combined picture: bonereaper currently trades BTC 5-min on the **NegRisk
CTF Exchange** (not indexed by the orderbook subgraph). His most recent
observable BTC 5-min performance is a **statistically unambiguous coin-flip**.
His older history on the original CTF Exchange did not include BTC 5-min
trading at all — it was other markets entirely.

---

## Gate evaluation (subgraph run, 2026-05-06)

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| 30-day BTC 5m win-rate | 0.0% (0 trades in subgraph window) | ≥ 60% | ❌ |
| Total BTC 5m trades observable | 0 | ≥ 500 | ❌ |
| 30-day volume change MoM | 0.0% (n/a; no BTC 5m volume) | > -40% | n/a |

## Gate evaluation (Data API run, 2026-05-05)

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| Recent-window BTC 5m win-rate | **50.6%** (1,083 resolved) | ≥ 60% | ❌ — even at 95% CI upper bound (53.6%) |
| Recent-window BTC 5m trade count | 1,116 | ≥ 500 | ✅ |
| Volume trend | n/a (single-window sample) | > -40% MoM | n/a |

## Statistical confidence

The coin-flip finding is robust. With **1,083 resolved BTC 5m trades**, the
95% binomial confidence interval for the true win-rate is
**[47.6%, 53.6%]**. This is **6.4 percentage points** below the 60% gate
floor at the upper bound. The gate failure is not a noise artifact.

## Why both sources are limited but the conclusion is solid

- **Data API** caps offset-based pagination at 3,500 rows. With bonereaper's
  trade volume that's ~3 hours of recent history — narrow, but
  **statistically sufficient** at 1,083 resolved trades.
- **Goldsky orderbook subgraph** indexes only the original CTF Exchange.
  Bonereaper's most recent fill there is ~7 days ago, predating his BTC 5m
  activity entirely (he was trading other markets).
- **Direct on-chain reads** of the NegRisk CTF Exchange (`0xC5d563…f80a`)
  via Polygon RPC would produce the canonical 30-day picture, but they are
  not needed: the Data-API 3-hour window is already a definitive ABORT
  signal at 95% confidence.

## Adjacent context (not in gate)

From the subgraph run (Apr 28–29 window):
- Total fills observable: **22,447** across **166 distinct markets**
- ETH 5m: 0 · ETH 15m: 0 · Other (non-BTC-5m, non-ETH-5m, non-ETH-15m): 22,447

Bonereaper is a high-frequency trader across many market types, but the
specific market we want to study (BTC up/down 5-min) shows no edge over a
statistically meaningful sample.

## Implications for the project

1. **The bonereaper-specific behavioral study is dead.** Phases B–G of
   `BONEREAPER_STUDY.pdf` should NOT be designed against this wallet.
2. **The main bot plan is unaffected.** The locked architecture
   (deterministic Tier-3 = window-delta + oracle-gap, threshold ≥0.6) does
   not depend on a cloning target. Phases 0–6 of `RUNBOOK.md` proceed
   unchanged.
3. **Three forward options (decisions belong to the operator, not the bot):**

   - **(A) Drop the wallet-cloning research stream entirely.** Build the
     main bot per `RUNBOOK.md` with deterministic Tier-3 + (optional) LLM
     ensemble. No reference wallet.
   - **(B) Pick a different reference wallet** with documented BTC 5-min
     edge. Re-run `quick_audit.py` against it. Proceed only if it passes
     the same gate. Polymarket leaderboards filtered by BTC market are the
     cheapest place to shop.
   - **(C) Treat any high-volume BTC 5-min wallet as a labelled-data
     source** (not just one). Aggregate per-market behavior across the top
     N wallets. This turns the study from "clone one bot" into "learn from
     the population's winners," more robust to single-wallet edge decay.

## Artifacts

- This document: `runbooks/study/preflight-decision.md`
- HTML report (charts): `runbooks/study/quick-audit.html`
- Raw subgraph fills: `state/research/bonereaper/subgraph_fills_{maker,taker}_<date>.json` (gitignored)
- Token→condition map: `state/research/bonereaper/token_to_condition_<date>.json` (gitignored)
- Condition→market map: `state/research/bonereaper/markets_<date>.json` (gitignored)
- Labelled dataset: `state/research/bonereaper/labelled_audit.parquet` (gitignored)
- Gate evidence: `runbooks/gate-evidence/study-A.txt`

## Operating-discipline note

This audit found a real signal — an ABORT with two independent
confirmations. Per `BUILD_SPEC.pdf` p. 22 anti-vibe rule #21 ("gate
criteria softened without an approved decision doc → revert, escalate"),
the 60% threshold was NOT relaxed to fit the data. Bonereaper does not
pass. Stopping here is correct.

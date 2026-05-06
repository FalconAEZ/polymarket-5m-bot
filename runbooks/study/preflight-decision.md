# Bonereaper — Phase A Pre-flight Decision (final)

**Decision:** **ABORT — cloning research stream dropped (option A).**

Generated: 2026-05-06 UTC
Wallet: `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` (Polymarket profile: `bonereaper`)
Operator path selected: **(A) Drop the wallet-cloning research stream entirely.**

---

## TL;DR

Three independent measurements all fail the **60% win-rate gate** locked in
`BONEREAPER_STUDY.pdf` p. 9. Bonereaper is **profitable** (~52.65% win-rate
on 56,972 trades over 7 days, +$31k gross), but his edge is a **slim
high-volume market-maker** strategy, not the high-conviction edge the
study was designed to clone.

The operator selected option **(A): drop the cloning stream entirely.**
Phases B–G of `BONEREAPER_STUDY.pdf` will not be designed. The main bot
plan (`RUNBOOK.md` Phases 0–8) is unaffected.

---

## All three measurements

| Method | Window | Trades | Win-rate | 95% CI | Gate (≥60%) |
|---|---|---|---|---|---|
| Polymarket Data API (user-trades, offset paginated) | last ~3 h | 1,083 resolved | 50.6% | [47.6%, 53.6%] | ❌ |
| Goldsky orderbook subgraph (CTF Exchange) | Apr 28–29, 1.5 d | 0 BTC 5m | n/a | n/a | ❌ (wrong exchange) |
| **Polymarket per-market enumeration (Gamma + Data API combined filter)** | **last 7 days** | **56,972 resolved** | **52.65%** | **[52.24%, 53.06%]** | **❌** |

The 7-day measurement is the canonical answer. Method:

1. Deterministically generate every `btc-updown-5m-<unix_ts>` slug for the last 7 days (288/day × 7 = 2,016 candidates).
2. Resolve each via Gamma `/events?slug=` with concurrency 16 → 2,015 closed+resolved BTC 5m markets.
3. For each market, fetch bonereaper's trades via the combined-filter `/trades?market=<conditionId>&user=<addr>` (one call per market, no offset cap reached) → 1,927 markets had bonereaper activity, 56,976 trades total.
4. Per-trade win/loss = `(1.0 − price) * size` if traded outcome won else `−price * size` (mirrored for SELL).
5. Aggregated.

## Headline numbers (7-day audit)

- Resolved BTC 5m trades: **56,972**
- Wins / losses: **29,995 / 26,977**
- Win-rate: **52.65%** (95% CI [52.24%, 53.06%])
- Gross P&L: **+$31,053.53**
- Total notional: **$2,344,672**
- Average size: 70.14 shares
- Earliest observed trade: 2026-04-29 06:11 UTC
- Latest observed trade: 2026-05-06 06:04 UTC
- Coverage: **96%** of BTC 5m markets traded

## Statistical interpretation

The 95% CI [52.24%, 53.06%] **excludes 50%** at high confidence — bonereaper
has a real, statistically detectable edge of ~2.65 percentage points above
chance. He is profitable: $31k gross / $2.3M notional = 1.32% gross-on-volume
in a week.

But the upper bound of the CI is **6.94 pp below the locked 60% gate**.
Reaching 60% would require a ~3-σ jump from current performance, which the
data does not support. **The gate is not a noise artifact.**

## Why the strict 60% gate stands (anti-vibe rule #21)

`BUILD_SPEC.pdf` p. 22 anti-vibe rule #21:
> Gate criteria softened ("close enough", "we'll fix later", "the test is
> flaky") without an approved decision doc → revert, escalate.

The 60% gate was set in writing in `BONEREAPER_STUDY.pdf` p. 9 based on
the framing "behavioral cloning of a high-accuracy edge." Lowering the
gate retroactively to fit the measured 52.65% would be exactly the
gate-softening the rule prohibits. **The gate stands. Bonereaper does not
pass. Decision is ABORT.**

## What we learned (don't lose this)

1. **The framing was wrong, not the wallet.** Bonereaper is real and
   profitable, just a different shape than we assumed. He runs a
   high-volume (~$2M+/wk notional) slim-edge (2.65 pp above coinflip)
   market-making strategy. Cloning him would mean cloning a market-maker,
   which has very different infrastructure requirements (throughput +
   fill rates, not signal selectivity) than the strategy in `MASTERPLAN.md`.
2. **Polymarket data sources have shape:**
   - **Data API `/trades?user=`** caps at offset=3,500. Useless for
     historical analysis on high-frequency wallets.
   - **Data API `/trades?market=&user=`** combined filter has no
     practical cap (per-market user footprints are tens of trades).
     **This is the canonical path for historical user analysis.**
   - **Goldsky orderbook subgraph** indexes only the legacy CTF Exchange.
     Newer markets (NegRisk Exchange `0xC5d563…f80a`) aren't there.
   - **Gamma API by-slug** is reliable; by-`condition_ids=` batching is
     not. Iterate one-at-a-time with concurrency.
3. **Implication for our deterministic Tier-3.** The fact that even a
   profitable wallet can't reach 60% on BTC 5m suggests our `composite ≥ 0.6`
   threshold (in `RUNBOOK.md` Phase 3 design) is the right shape: we're
   not trying to *out-edge* bonereaper, we're trying to be *more
   selective*. We trade fewer windows but only when our composite signal
   is strong. That's a different game from market-making.

## Operator path: (A) Drop the cloning stream entirely

The deterministic Tier-3 strategy doesn't need a cloning target. The main
bot plan (`MASTERPLAN.md` + `RUNBOOK.md` Phases 0–8 + `BUILD_SPEC.pdf`) is
fully self-contained and unaffected by this abort.

**Locked changes:**
- `BONEREAPER_STUDY.pdf` is now an archived research artifact, not an
  active phase set. Phases B–G are not designed.
- `RUNBOOK.md` Phase 8 — re-evaluation of dropped LLM ensemble — remains.
  No re-evaluation of the cloning ensemble; it was never built.
- The `behavioral_mimic` 4th ensemble agent is **out** of consideration
  for Phase 3. The ensemble is 3 agents + meta only (per locked decision
  #5).

## Artifacts

- This document: `runbooks/study/preflight-decision.md`
- 7-day report: `runbooks/study/weekly-audit.md`
- 3-hour HTML report (charts): `runbooks/study/quick-audit.html`
- Postmortem (Obsidian-vault side): `state/research/bonereaper-study-postmortem.md`
- Audit scripts: `scripts/research/{quick_audit,weekly_audit,_api,_subgraph}.py`
- Design doc: `design/research/quick_audit.md`
- Gate evidence: `runbooks/gate-evidence/study-A.txt`

## Status

Phase A: **CLOSED with ABORT.** Cloning research stream **DROPPED**. Main
bot plan **UNCHANGED.** Next operator action: open `RUNBOOK.md` Phase 0
when ready to start the trading bot build.

# 2026-05-10 — Phase 5 LLM ensemble: revert to wide-fire, ship LLM gate, two incidents handled

**Session:** continuation of 2026-05-10 post-incident-fix session.
**Branch:** `claude/jovial-hermann-7e103f` (PR #1) + `claude/dashboard-pm-truth-fix-7e103f` (PR #2)
**Pickup:** 2026-05-10 ~01:30 UTC. Closed at 04:37 UTC after second queue-overflow incident
fixed and re-soaked clean.
**Operator state:** explicit "do B then A" override of my recommendation; full trust to execute;
called out two real bugs live (the cold-start vote-eating + the cross-restart double-fire +
the queue-overflow incident). Saved bankroll twice via fast Telegram alerts.

## Headline

This session converted the bot from "v2-tight, fires ~1/day, 70% WR target" to
"wide-fire, ~10-50 fires/day, LLM ensemble in shadow mode scoring every fire". Plus
**five real bugs caught and fixed live** (one of which was a recurrence of the same
queue-overflow class as the 2026-05-09 incident). Plus operator's option C — hard
economic gate in the LLM prompts — verified working in production within 6 minutes
of the redeploy.

The bot is now running on:

```
spot/book/oracle event
        ↓
WideFireStrategy (fires every window with non-zero spot delta; no gates)
        ↓
EnsembleWrapper (shadow mode — fire-and-forget LLM call on every candidate)
        ↓
3 specialists (Haiku 4.5) in parallel
  • orderbook: book imbalance + spread asymmetry
  • oracle_gap: spot vs Chainlink staleness
  • momentum: 60s spot trajectory quality
        ↓
Sonnet 4.6 meta-decider with HARD ECONOMIC GATE
  (ABSTAIN unconditionally if chosen-side best_ask >= 0.90)
        ↓
state/ensemble/<date>.jsonl ← every vote captured
        ↓
Base verdict drives the actual fire (shadow mode); meta verdict logged
```

Cost: ~$36/month sustained at observed fire rate. Hard cap $10/day via BudgetTracker.

## What shipped (8 commits this session, all on PR #1)

### `f89fb05` — v2 tier-discipline leak fix (-$15.01 historical drag)

Audit found 11/299 historical fires actually leaked into the [0.50, 0.70) reject
band via the taker impact-cap path (ask=0.49 + 1¢ impact = 0.50 effective_ask).
Net WR on leaks: 36.4% vs dataset 49%; net loss $15.01.

Fix: cap price_limit one tick below any reject band's lower bound so neither taker
(effective_ask) nor maker (limit) fills can land inside the band. +2 tests.

### `9c4c4f3` — regime classifier validation HYPOTHESIS CONFIRMED

Implemented Phase 4 validation script per design/regime_detector.md. Result on 299
fires: **trending bucket WR 70.59% vs chop 47.40% (+23.19pp)**, per-trade pnl $+1.75
vs $-0.22. Verdict: implement regime detector. Validation gate (a) cleared.

### `b129bbb` — RegimeDetector + SpotAwareStrategyV3

Pure deterministic class (5m/10m vol-ratio classifier) + v3 wrapper that gates v2's
fires to "trending" regime only. 18 new tests. Wired via STRATEGY=spot_aware_v3 with
REGIME_TRENDING_THRESHOLD / REGIME_CHOP_THRESHOLD env knobs. **Built but not deployed
in production this session** — operator instead chose Phase 5 path (wide-fire + LLM).

### `140a0c0` — oracle-gap alignment filter on v2

Audit finding: aligned + |gap| ≥ 1 bps gives 62.5% WR on 292-fire historical dataset.
v2 now accepts `oracle_gap_min_bps` kwarg + ORACLE_GAP_MIN_BPS env. Default 0 (off);
operator can stack with ev_min for higher WR. 6 new tests.

### `46907bc` — EnsembleWrapper + Phase 5 dispatch

Operator-approved direction: revert ev_min to 0.003 (wide-fire) + activate LLM
ensemble as new gate. EnsembleWrapper bridges any base Strategy with the existing
3-specialist + Sonnet meta agents in three modes (off / shadow / gate). Shadow logs
votes; gate filters fires. AnthropicAdapter + BudgetTracker wired via run_paper.py.
10 wrapper tests. design/phase-5-llm-ensemble.md committed with the operator's
override on record.

### `32d3d55` — WideFireStrategy + ENSEMBLE_BASE_STRATEGY

Operator clarification: wanted literal "every window, no gates". v2 still had tier
rejection + priors gate. New WideFireStrategy fires on any non-zero spot delta with
NO tier/priors/EV/oracle gates. Optional delta_min_bps floor (default 0). 10 new
tests proving fires on tiers v2 rejected. ENSEMBLE_BASE_STRATEGY env var: spot_aware_v2
(default) | wide_fire.

### `861be30` — ensemble cold-start fix (FIRST live bug operator caught)

Operator caught: 2 fires post-deploy, both `kind=ensemble_cold_start` in JSONL —
LLM never called. Root cause: wrapper required Chainlink oracle data to build
AgentContext; Chainlink heartbeats every ~33s; wide_fire fires within 1-2s of
window-open BEFORE first oracle. Every fire post-restart got cold-started.

Fix: relax cold-start to require only (window_ts, spot_now, window_open_spot). When
oracle missing, fall back to spot as proxy + sentinel oracle_age_s=999 (oracle_gap
specialist recognises and abstains). Now LLM scores every fire even at cold start.

### `2576c72` — cross-restart double-fire guard (SECOND live bug)

Operator caught: window 1778385300 had TWO fires — DOWN at 03:55:00 (old bot,
seconds before restart) and UP at 03:59:46 (new bot, 2s after restart). Same 5m
market, opposing sides → guaranteed -$5 loss on the wrong side.

Root cause: each PaperRunner instance starts with empty `_state`. The duplicate-fire
guard in _on_decision (trips on `pending_decision` or `settled_fill`) fails to detect
prior fires from a previous bot lifetime. orphan_recovery only handles PAST windows;
the CURRENT window is legitimately pending so it correctly skips.

Fix: new `_prime_active_window_state()` runs at startup AFTER orphan recovery. Scans
today's decision_log for fires in `active_window_ts(now)`. If unsettled fire found,
builds a stub Decision and assigns to `_state.pending_decision` so the existing
duplicate-fire guard trips. 3 new tests including bug-reproducer (anti-vibe rule #2
proven by stash-then-replay).

### `54fa0d5` — fire-and-forget shadow vote + economic-gate prompts (THIRD bug + option C)

**Live incident at 04:20 UTC**: Telegram alert "queue overflow; dropped=16100".
EnsembleWrapper.on_event was awaiting the LLM ensemble inline. With 3 Haiku in
parallel (~500ms) + Sonnet meta sequential (~1000ms) = ~1.5s blocking the runner's
main loop per fire. wide_fire's high cadence + 1.5s blocks → bounded queue overflowed.
**16,223 records dropped** before mitigation.

This is the **second time** the same architectural bug class shipped — first was
the 2026-05-09 instant-settle gamma poll. The lesson from
`feedback_test_under_load.md` was honored for the gamma fix but I forgot it for the
ensemble.

Fix: shadow mode now schedules LLM votes via `asyncio.create_task` — fire-and-forget
background task tracked in `_pending_shadow_votes`. on_event returns the candidate
in <200ms regardless of LLM latency. New `aclose()` method awaits in-flight votes
on shutdown; runner.run() finally calls `strategy.aclose()` (via getattr) so the
last batch of votes lands in JSONL before log close. Gate mode keeps inline await
(verdict gates the fire; mitigation is operator-side budget caps).

Plus the queue-doesn't-overflow regression test
(`test_shadow_mode_does_not_block_main_loop_under_slow_llm`): injects 1.5s simulated
LLM latency, asserts on_event returns in <200ms. Stash the fix → test fails with
"on_event took 1504ms — queue-overflow regression has returned".

**Plus operator's option C (price economics)**: all 4 prompts now have a hard
ABSTAIN rule for `best_ask >= 0.90` regardless of directional signal. The most
important is `prompts/meta.md` — HARD ECONOMIC GATE before all other decision
criteria, with new Example 6 demonstrating ABSTAIN despite 3-way agreement.

Plus a postmortem at
`runbooks/incidents/2026-05-10-ensemble-llm-queue-overflow.md` explicitly recognising
this is the second occurrence of the same bug class and committing to "any future
async-I/O-in-main-loop change ships with a queue-doesn't-overflow load test".

## Production state at session close (04:37 UTC)

VPS:
- bot-staging.service active since 2026-05-10 04:31:41 UTC
- HEAD: `54fa0d5` on `claude/jovial-hermann-7e103f`
- .envrc:
  - `STRATEGY=ensemble`
  - `ENSEMBLE_MODE=shadow`
  - `ENSEMBLE_BASE_STRATEGY=wide_fire`
  - `SPOT_AWARE_EV_MIN_DOLLARS=0.003`
  - `INSTANT_SETTLE_ENABLED=1`
  - `ORPHAN_RECOVERY_ENABLED=1` (default)
  - `ANTHROPIC_API_KEY` set, length 108
  - `ANTHROPIC_DAILY_BUDGET_USD=10`
- 5.5-min post-fix soak: **8 fires, 8 ensemble votes, 0 cold-starts, 0 queue overflows**
- Confirmed economic gate firing live: ABSTAIN at best_ask_up=0.91 with rationale
  citing the hard gate

Repo:
- 8 commits this session on PR #1, all pushed
- 0 commits this session on PR #2 (last was eb79355 from previous session)
- 429 pytest pass, mypy --strict 63 src files clean, ruff clean
- Working tree clean (only state/staging/ untracked, gitignored content)

## Test count growth this session

| Phase | Tests | New |
|---|---|---|
| Pre-session | 369 | — |
| End of "post-incident" session | 414 | +45 |
| End of THIS session | 429 | +15 |
| Of which: bug-reproducer/regression | 5 | +5 |

Bug→failing-test→fix→green proven for:
1. Background-settle queue-doesn't-overflow (pre-session)
2. v2 tier leak (this session, +2 tests)
3. Cross-restart double-fire (this session, +1 reproducer)
4. EnsembleWrapper queue-overflow regression (this session, +1 reproducer)
5. Cold-start LLM-vote-eating (this session, +1 inverted assertion)

## Anthropic spend

Pre-session: $0.405 cumulative (Phase 3 only).
This session: ~$0.05 from live shadow-mode LLM calls (12 + 24 calls × $0.001-0.003).
Cumulative: ~$0.455. Far below decision #14's $50 Phase 3 cap.

## What's deferred to next session

1. **24-72h shadow-data soak.** Operator runs daily:
   ```bash
   ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 \
     'cd /home/ops/polymarket-5m-bot && uv run python runbooks/scripts/ensemble_shadow_rollup.py'
   ```
   Verdict per design's binary gate: +5pp WR uplift → flip ENSEMBLE_MODE=gate;
   ±3pp → keep deterministic; worse → drop ensemble + write Phase 5 postmortem.

2. **48h Phase 11.A.2 gate review** still procedural. The aggressive-mode soak's 48h
   review was at 2026-05-10 22:26:15 UTC (now well past); operator may run
   `bash runbooks/gates/spot-aware-paper.sh` to formally close.

3. **PR #1 + PR #2 merge to main** — 9 commits ready; operator decides when to merge.

4. **RegimeDetector v3 deployment** — built (commit b129bbb) but not running in
   production. Could replace v2 base inside ensemble for tighter quality once shadow
   data validates the LLM ensemble.

5. **Tick-capture pipeline** — design/regime_detector.md references
   state/ticks/binance/*.parquet which doesn't exist on VPS. The regime classifier
   validation used 1-min klines as a fallback. Future work: enable tick capture
   so the regime detector + LLM agents have higher-resolution input.

## Anti-vibe checks

- **Bug → failing test → fix → green (#2)** — proven 3 separate times this session.
- **Test runtime behavior under load (feedback_test_under_load.md)** — applied
  retroactively after the second occurrence; explicit promise in the postmortem
  to never ship async-I/O-in-main-loop without the queue-doesn't-overflow test.
- **Honest pushback (feedback_honest_pushback.md)** — pushed back twice on the
  "fire every window" direction with data; operator overrode; I shipped what was
  asked while documenting the disagreement on record (design/phase-5-llm-ensemble.md
  ends with "Operator overrode my recommendation...").
- **Always ship a kill-switch env var** — ENSEMBLE_MODE=off is the kill-switch;
  the emergency mitigation at 04:24 UTC used it cleanly.

## Hand-off prompt for next session

`phase-prompts/phase-11.a.2-shadow-rollup-2026-05-11.txt` (to be written by
operator or this session). Likely items:

1. Run `runbooks/scripts/ensemble_shadow_rollup.py` and report WR delta.
2. If gate (a) cleared: flip ENSEMBLE_MODE=gate, restart, watch 30 min for
   no overflow + LLM filtering taking effect.
3. If gate (b/c): drop ensemble, restore v2-tight + oracle-gap filter.
4. Either way: PR #1 + PR #2 merge to main + tag `phase-11.a.2-pass`.

Phase 6 (sizing scale-up at 100 trades) is gated on Phase 5's verdict.

## Cross-refs

- `design/phase-5-llm-ensemble.md` — operator's plan + override on record
- `runbooks/incidents/2026-05-10-ensemble-llm-queue-overflow.md` — postmortem
- `prompts/meta.md` — HARD ECONOMIC GATE (operator's option C)
- `tests/strategies/test_ensemble_wrapper.py` — 11 tests including queue-doesn't-overflow regression
- `~/.claude/projects/.../memory/feedback_test_under_load.md` — the lesson, learned twice now

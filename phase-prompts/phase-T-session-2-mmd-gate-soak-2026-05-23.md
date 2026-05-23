# Phase T — Session 2 prompt — MMD-gate soak + L.5 fix + audit decisions

**Authored:** 2026-05-23 12:17 UTC.
**Branch:** `claude/phase-T-directional-revival` @ `e38c878`.
**Worktree:** `.claude/worktrees/phase-T-directional-revival`.
**Pre-conditions at session start:** bot LIVE on VPS with new MMD-gate config; bankroll reset to exactly $3,000; 3-day Session 1 data archived to `state/decisions/archived/phase-T-soak-1-2026-05-21/`.

---

## §1. What Session 1 found (load-bearing)

Full PDF audit at [pdfs/PHASE_T_LIVE_SOAK_AUDIT.pdf](../pdfs/PHASE_T_LIVE_SOAK_AUDIT.pdf) (17pp, 9 charts). Headlines:

- **57.5h soak** (2026-05-21 02:21Z → 2026-05-23 11:50Z): 1,226 fires at 99.9% fill rate.
- **Bankroll: $3,000 → peak $7,365 → trough $323 → $803.** Net −$2,938.
- **WR 60.5%, $/tr −$2.40.** Highest WR of any phase, worst absolute PnL.
- **MMD shadow data showed the missing piece**: CHOPPY label = $3,708 of losses on n=333 at −$11.13/tr. Counterfactual gate-mode-abstain-CHOPPY flips 3-day net from −$2,938 to +$770.
- **L.5 daily-loss guard NEVER tripped** despite −$1k+ days. **Root cause: L.5 is only wired in ensemble_wrapper.py (line 522). Spot_aware_v2_1 standalone has no daily-loss halt.** This is a critical safety gap.
- **Engineering wins all worked**: fill-rate fix (30%→99.9%), per-cell mechanism (44.5% multi-fire), zero infra failures across 57.5h.

## §2. What was shipped this Session 2 prep step (2026-05-23 12:14-12:17 UTC)

1. **Halted current bot** via halt sentinel (`session-2-config-change-mmd-gate-choppy-restore-h2.12`).
2. **L.5 diagnosis**: confirmed `max_daily_loss` / L.5 logic exists ONLY in `ensemble_wrapper.py:522`. The bot runs spot_aware_v2_1 standalone → no L.5 protection. Queued P1 in §3 below for next session.
3. **Env config updated** in `.envrc` (backup at `.envrc.bak-pre-session-2-20260523-121402`):
   - `MMD_MODE=gate` (promoted from shadow per PDF n=333 validation)
   - `MMD_LABELS_TO_ABSTAIN=CHOPPY` (only the validated bleeder)
   - `SPOT_AWARE_BLOCK_UP_IN_TIERS="70-85%"` (H.2.12 path-A restored — UP-side only)
   - Kept: `MULTI_FIRE_CAP=4`, `BANKROLL_REPLAY_ENABLED=true`, `PMB_STARTING_BANKROLL=3000`
   - NOT restored: `SPOT_AWARE_BLOCK_DOWN_IN_TIERS` (operator wanted UP block only)
4. **Reset bankroll + data to exact $3k**:
   - Archived `2026-05-{19,21,22,23}.jsonl` → `state/decisions/archived/phase-T-soak-1-2026-05-21/`
   - Removed halt sentinel
   - Restarted bot-staging.service (MainPID 1294010 at 12:16:32Z)
   - Confirmed `bankroll replay: starting=$3000.00 current=$3000.00`

## §3. Session 2 plan (do these in order)

### P0 — Verify the soak is healthy + accumulating data (first 30 min of session)
- SSH check: `bot-staging.service` active, no errors in 1h journal, halt sentinel absent.
- Pull today's decisions log; confirm fires are landing with the new gate (`mmd=` annotation shows abstain on CHOPPY-labelled windows).
- Spot-check first 10-20 fires: do they avoid CHOPPY-labelled MMD readings? Do tier 70-85% UP-side fires no longer appear?
- Dashboard live at http://localhost:8505 — visual check.

### P1 — Ship L.5 daily-loss halt as a strategy-agnostic runner-level guard
**This is the critical safety work.** L.5 must protect ANY strategy, not just ensemble.
- Design doc: `design/phase-T-l5-runner-daily-loss-guard.md`
- Location: `_paper/runner.py` — read bankroll delta vs start-of-UTC-day; if delta < −threshold AND time > UTC 23:50 (or continuous check), write halt sentinel.
- Make threshold env-tunable: `DAILY_LOSS_HALT_USD=300` (10% of $3k) or pct-of-starting.
- 5+ tests covering: trip when threshold crossed, no-trip when above, threshold-zero is disabled.
- Acceptance: existing tests pass + new tests pass + ruff/mypy clean.
- **Do this before letting the bot run another 24h.**

### P2 — Day-1 audit of new gate config (at ~12h soak mark)
- Pull decision log; recompute per-MMD-label PnL.
- Compare: vs Session 1's −$2,938 baseline.
- Expected (per PDF counterfactual): roughly +$770 over 3 days if regime stays consistent — translates to ~+$10/hr at peak rate.
- If actual ≤ 50% of expected: investigate (regime drift? MMD label drift? new cell flip?).
- If actual ≥ expected: continue to Day-7 soak.

### P3 — Cell-flip detector promotion (if Day-1 audit passes)
- Improvement #2 Part B (cell_flip_detector.py) is already in code but `CELL_FLIP_ENABLED=false` env default.
- Wire: `CELL_FLIP_ENABLED=true` + `CELL_FLIP_WINDOW_SIZE=20` + `CELL_FLIP_ABSTAIN_THRESHOLD_PP=5` + `CELL_FLIP_MIN_SAMPLES=10`.
- Catches SURV-style mid-soak regime shifts (the Phase N + Phase T Day-1-PM pattern).
- Should produce another $300-500 of saved drawdown across a week.

### P4 — Hour-blocklist (Improvement #1 — env opt-in)
- Bleed hours from PDF §6: 02/04/14/20/21/22Z had cumulative −$8.4k across 3 days.
- After CHOPPY abstain lands, re-measure hour PnL. Many bleed hours may be CHOPPY-dominant and already mitigated.
- Wire remaining bleed-hour-tier pairs: `SPOT_AWARE_HOUR_BLOCKLIST_PAIRS="..."`.

### P5 — Day-7 gate (T+7d from clean reset)
- Cum PnL > +$300 = PASS → consider scale-up
- Cum ∈ [+$5, +$30] = MARGINAL → extend 7 days
- Cum ≤ $0 or any incident = FAIL → close Phase T, document, decide on MMB or shelve

## §4. Live state at session start

| Item | Value |
|---|---|
| Branch / HEAD | `claude/phase-T-directional-revival` @ `e38c878` |
| VPS git HEAD | `4144302` (one commit behind — session 2 docs pushed) |
| Strategy | spot_aware_v2_1 |
| MMD | **GATE mode**, abstain CHOPPY only |
| H.2.12 path A | RESTORED (block UP in tier 70-85%) |
| BLOCK_DOWN | NOT restored (operator chose UP-only) |
| Kelly | 0.15× |
| multi_fire_cap | 4 |
| per-cell fire | enabled |
| Cell-flip detector | code shipped, env disabled |
| Hour-blocklist | code shipped, env empty |
| L.5 daily-loss | **NOT WIRED** for spot_aware_v2_1 (only ensemble) — P1 fixes |
| Bankroll | $3,000.00 (clean reset) |
| Bot uptime | restarted 2026-05-23 12:16:32Z |

## §5. Don't-do rules

- Do NOT enable cell-flip detector OR hour-blocklist in the same change as P1 (one knob at a time).
- Do NOT raise Kelly above 0.15× while the soak is running.
- Do NOT delete the archived Session 1 data — `state/decisions/archived/phase-T-soak-1-2026-05-21/` is the empirical base for the PDF audit.
- Do NOT skip the L.5 P1 work — running another 24h without a daily-loss halt would re-create Session 1's −$2k bleed risk if MMD-CHOPPY-abstain doesn't deliver the predicted edge.
- Do NOT change `MMD_LABELS_TO_ABSTAIN` mid-soak to chase data — give it 24h minimum to validate.

## §6. References

- Audit PDF: [pdfs/PHASE_T_LIVE_SOAK_AUDIT.pdf](../pdfs/PHASE_T_LIVE_SOAK_AUDIT.pdf) (this is the primary read)
- Phase T revival prompt (Session 1): [phase-prompts/phase-T-directional-revival-2026-05-20.md](phase-T-directional-revival-2026-05-20.md)
- Paper-vs-live delta: [runbooks/paper-vs-live-delta.md](../runbooks/paper-vs-live-delta.md)
- Phase P MMD design (gate-mode reference): [design/P.1-market-mode-detector-integration.md](../design/P.1-market-mode-detector-integration.md)
- Session 1 archived decision logs: `state/decisions/archived/phase-T-soak-1-2026-05-21/2026-05-{19,21,22,23}.jsonl`
- Session 1 .envrc backup on VPS: `/home/ops/polymarket-5m-bot/.envrc.bak-pre-session-2-20260523-121402`

## §7. Operator hand-off note

The bot is running fresh from $3k with the one config change the data unambiguously asked for. If the PDF counterfactual is right, the next 24-72h shows positive $/tr in the 40-60% MMD-label-MIXED-DOWN-UP space without the CHOPPY drag. If it's wrong, we get a fast empirical answer (within ~24h) and a definitive close-out on Phase T.

Either way, the L.5 P1 work is non-negotiable before the next 24h elapses.

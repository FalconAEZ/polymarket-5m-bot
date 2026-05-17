# Phase O — Remediation

**Status:** OPEN (Session 1 complete 2026-05-17)
**Predecessor:** Phase N forensic audit (PHASE_N_FORENSIC_AUDIT.pdf)
**Opened on operator sign-off:** 2026-05-17 (full plan steps 1-6)

Phase O is the actionable phase after Phase N's investigation. It ships
data-grounded remediations to the bleed identified in Phase N (peak
+$1,235 → −$327 over 45h on 2026-05-15 → 2026-05-17).

## Session roadmap

| session | scope | status |
|---|---|---|
| 1 | Disable M.1a v1, enable SURV canary, keep M.5 active. Bot resume. | **DONE 2026-05-17** |
| 1.5 | Bankroll reset $1k→$3k (decision #10 override), L.5 scaling −$30→−$90, M.5 lookback 30→15, dashboard env fix. | **DONE 2026-05-17 16:32→17:00Z** |
| 2 | J.2 per-tier-hour env redesign; day-1 re-soak observation; SURV canary obs (decisions-tape extension if operator wants) | pending — see `state/sessions/2026-05-18-phase-O-session-2-prep.md` |
| 3 | N.5 regime classifier validity test (if obs data motivates) | pending |
| 4 | If bleed continues: Kelly demotion 0.15→0.10 (PDF §7.4) | conditional |
| ... | Phase H/J/L/M defenses stay; strategy class flip is LAST RESORT | |

## Phase O Session 1 deliverables (closed 2026-05-17)

### Commits

- `16e8f38` — Phase N forensic PDF + O.1 SURV canary impl + tests + backtest
- `d3ed2a8` — Phase O vault docs (initial session note + ledger)
- `98940b1` — dashboard bankroll env-honoring fix (`PMB_STARTING_BANKROLL` +
  `BANKROLL_REPLAY_ENABLED` passthrough)

### Files shipped

- `design/O.0-phase-n-m5-persistence-null.md` — M.5 persistence is moot
- `design/O.1-surv-cell-shift-canary.md` — canary spec
- `src/polymarket_bot/strategies/surv_canary_metrics.py` (NEW)
- `src/polymarket_bot/strategies/spot_aware_v2_1.py` — canary gate
- `src/polymarket_bot/dashboard/bankroll.py` — `replay_enabled` kwarg
- `src/polymarket_bot/dashboard_server/state.py` — env passthrough
- 11 new tests in `tests/strategies/test_spot_aware_v2_1.py`
- `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` (22 pp, 14 charts)

### VPS config flips applied this session

| flip | from | to | timestamp |
|---|---|---|---|
| `REGIME_M1A_V1_ENABLED` | true | **false** (falsifier killed it) | ~16:25Z |
| `SURV_CANARY_ENABLED` | (absent) | **true** | ~16:25Z |
| `SURV_CANARY_LOOKBACK_N` | — | 15 | ~16:25Z |
| `SURV_CANARY_MIN_SAMPLES` | — | 10 | ~16:25Z |
| `SURV_CANARY_BREAK_EVEN_MARGIN` | — | −0.01 | ~16:25Z |
| `SURV_CANARY_MIN_ABS_DELTA_BPS` | — | 5.0 | ~16:25Z |
| `PMB_STARTING_BANKROLL` | 1000 | **3000** (decision #10 override) | 16:32Z |
| `BANKROLL_REPLAY_ENABLED` | true | **false** | 16:32Z |
| `DAILY_PNL_GATE_USD` (L.5) | −30 | **−90** (3× scaling) | 16:34Z |
| `REGIME_M5_LOOKBACK_N` | 30 | **15** (faster recovery) | 17:00Z |
| `REGIME_M5_MIN_SAMPLES` | 20 | **10** (2/3 ratio preserved) | 17:00Z |

Plus systemd drop-in
`/etc/systemd/system/dashboard-server.service.d/bankroll.conf` adds
the bankroll env vars to the dashboard service.

### Live config snapshot at Session 1 close

```
KELLY_MULT=0.15
PMB_STARTING_BANKROLL=3000
BANKROLL_REPLAY_ENABLED=false
DAILY_PNL_GATE_USD=-90.0

# Phase O actives
REGIME_M5_PATH_A_GATE_ENABLED=true   (lookback=15, min=10, margin=0.02)
SURV_CANARY_ENABLED=true             (lookback=15, min=10, margin=-0.01)

# Shadow only
REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true   # M.1a v0
ORDERBOOK_IMBALANCE_SHADOW_ENABLED=true    # M.2 v0

# Disabled
REGIME_M1A_V1_ENABLED=false

# Carry-overs from Phase H/J
SPOT_AWARE_BLOCK_UP_IN_TIERS="70-85%"
SPOT_AWARE_HOUR_BLOCKLIST_UTC=22,23,0
SPOT_AWARE_HOUR_BLOCKLIST_TIERS=70-85%
SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK=0.0   # J.1.5 fold
```

### Session 1 outcome (5h window after bot resume)

- 1 fire (17:39:36Z): tier 30-50% × DOWN @ $0.45, bet $163.64 — LOST
  −$163.67 (chainlink-fallback resolved UP, polymarket post-hoc
  confirmed UP)
- M.5 successfully closed all Path-A candidates (zero new tier-70-85%
  fires)
- L.5 trip at 23:50Z UTC LOCKED IN (today PnL −$518.58 ≪ −$90 gate)
- Auto-resume cron at 23:53Z will pick up the bot (sentinel reason
  `auto-halt-daily-pnl` matches)
- Bot LIVE at MainPID 1002001 since 17:00:22Z waiting for 23:50Z trip

## Locked rules for Phase O

1. Every remediation must trace to a falsifiable Phase N finding.
2. No new feature ships without back-testing on n=755 forensic data.
3. No env flip on VPS without a `.envrc` backup + dated comment.
4. L.5 daily-PnL auto-halt stays active throughout (the safety net).
5. If a re-soak day bleeds > −$30 (L.5 trip), HALT and review.

## What unlocks Phase P

- 5-day re-soak with new config showing net-positive PnL
- M.5 actively gating Path-A fires (verify via decision-log abstain count)
- SURV canary not over-firing (verify via WARNING-level log frequency)
- Operator decision on next remediation tier

## Cross-references

- Phase N PDF: `pdfs/PHASE_N_FORENSIC_AUDIT.pdf`
- Phase N ledger: `state/phases/phase-N-forensic-audit.md`
- Session note: `state/sessions/2026-05-17-phase-O-session-1-bot-resumed.md`
- Phase M ledger: `state/phases/phase-M-pre-live-edge-stacking.md` (paused)

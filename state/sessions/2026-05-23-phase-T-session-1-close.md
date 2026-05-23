# Phase T Session 1 — CLOSE 2026-05-23 12:17 UTC

**Branch:** claude/phase-T-directional-revival @ e38c878 (PDF audit) + next prep ahead.
**Duration of live soak:** 2026-05-21 02:21Z → 2026-05-23 11:50Z (57.5h, 1,226 fires).
**Verdict:** Engineering wins all worked; strategy bled $2,938 net; data unambiguously identifies the fix (MMD CHOPPY abstain).

## Shipped this session (10 commits)

1. `b33cb6e` Phase T revival prompt + 6 queued improvements
2. `228703a` Improvement #1 — J.2 per-pair hour-blocklist (+6 tests)
3. `ad0a797` Improvement #2 — cell-flip-detector design (Part A)
4. `6d118ce` Paper-vs-live delta — directional has no live-order path
5. `afdc51d` Improvement #2 Part B — cell-flip detector implementation (+14 tests)
6. `33c3e2b` Improvement #1.5 — per-cell fire mechanism (+5 tests)
7. `4144302` Fill-rate fix — size-guard now price-conditional (+4 tests)
8. `e38c878` 3-day live-soak forensic PDF audit (17pp + 9 charts)
9. (this session-close + Session 2 prompt + vault updates — about to commit)

## Live-soak headline

- Bankroll: $3,000 → peak $7,365 (Day 1 19:17Z, +145%) → trough $323 (Day 3 04:30Z, −96% from peak) → $803
- Net PnL across 1,226 fires: −$2,938 (−$2.40 / trade)
- WR 60.5% (741W / 484L)
- Fill rate: 99.9% (fix landed Day 1)
- Per-cell mechanism: 44.5% multi-fire windows
- L.5 daily-loss never tripped (root cause: not wired to spot_aware_v2_1)

## The single load-bearing finding

MMD shadow data over 1,226 fires shows CHOPPY label is the dominant bleeder:
  - CHOPPY: n=333, WR 57.7%, $/tr −$11.13, PnL −$3,708
  - MIXED:  n=465, WR 60.3%, $/tr −$3.38, PnL −$1,569
  - DOWN:   n=287, WR 60.3%, $/tr +$1.24, PnL +$355
  - UP:     n=141, WR 68.1%, $/tr +$14.07, PnL +$1,984

Counterfactual: gate-mode + abstain CHOPPY only would have flipped net from −$2,938 to +$770.

## Critical safety gap found

L.5 daily-loss guard exists in code (`ensemble_wrapper.py:522`) but is NOT wired to spot_aware_v2_1 standalone. The bot ran 57.5h with multiple −$1k+ days unprotected. Fixed-in-design via Session 2 P1 (runner-level daily-loss halt as strategy-agnostic).

## Session 2 prep already completed (12:14-12:17 UTC)

- Halted bot via halt sentinel
- Backed up .envrc (`.envrc.bak-pre-session-2-20260523-121402`)
- Set `MMD_MODE=gate` + `MMD_LABELS_TO_ABSTAIN=CHOPPY`
- Restored `SPOT_AWARE_BLOCK_UP_IN_TIERS=70-85%` (H.2.12 path A)
- Archived 4 decision logs to `state/decisions/archived/phase-T-soak-1-2026-05-21/`
- Restarted bot-staging at 12:16:32Z (MainPID 1294010)
- Confirmed clean reset: `bankroll replay: starting=$3000.00 current=$3000.00`

## Next session pickup

Read `phase-prompts/phase-T-session-2-mmd-gate-soak-2026-05-23.md` first.

Priority:
- P0: 30-min health check on the new config
- P1: SHIP L.5 daily-loss halt at runner level (non-negotiable; design + impl + tests)
- P2: Day-1 audit of new gate config (~12h mark)
- P3: Cell-flip detector promotion (if Day-1 passes)
- P4: Hour-blocklist refinement (after Day-1)
- P5: Day-7 gate (PASS = cum > +$300)

## State of the world

- Bot: LIVE on VPS at e38c878 + new env config; bankroll clean $3,000
- MMB: parked on origin/claude/phase-S-market-maker @ 8fe6007
- All Phase T improvements either deployed or shipped+ready-to-enable

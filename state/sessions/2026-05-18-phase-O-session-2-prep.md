# 2026-05-18 — Phase O Session 2 prep (overnight L.5 trip + day-1 soak)

This note is forward-pointing: it documents the EXPECTED 23:50Z L.5
trip + auto-resume cycle for 2026-05-17 → 2026-05-18, plus the
Session-2 watchlist. Once 2026-05-18 events land in JSONL the operator
should append a "what actually happened" section here.

## Carryover from Session 1 (2026-05-17)

State at Session 1 close (19:33Z observation):
- bot-staging.service ACTIVE since 17:00:22Z, MainPID 1002001
- Bankroll **$3,000** (replay=false, decision #10 override)
- L.5 gate **−$90** (3× scaled with bankroll)
- M.5 lookback **15** / min_samples **10** / margin **+0.02** (active)
- SURV canary lookback **15** / min_samples **10** / margin **−0.01** (active)
- M.1a v0 shadow active; M.1a v1 disabled
- Today PnL (2026-05-17 UTC) **−$518.58**, 1 fire post-restart (LOSS)

## Expected overnight cycle

| time UTC | event | outcome |
|---|---|---|
| 23:50:00Z | L.5 daily-PnL check at gate=−$90; today PnL −$518.58 | **L.5 TRIPS** |
| 23:50:00-04Z | sentinel written, Telegram CRITICAL fired, bot SIGTERM | bot drains queue, exits |
| 23:53:00Z | cron `l5_auto_resume.sh` runs | sentinel reason `auto-halt-daily-pnl` MATCHES; **auto-resumes** the bot |
| 23:53:00-15Z | bot-staging.service restart | new MainPID, fresh day clock |
| 2026-05-18 00:00:00Z | new UTC day rolls over | today PnL counter resets to $0 |

## What operator should verify in the morning UTC

1. **Bot is active**: `systemctl is-active bot-staging.service` → `active`
2. **No sentinel**: `ls state/halt.sentinel` → should not exist
3. **Auto-resume log**: `tail /tmp/l5_auto_resume.log` → should show
   the resume action
4. **Bankroll unchanged**: dashboard hero row still **$3,000** (replay
   off means it's anchored, daily PnL won't compound)
5. **Day-1 fires accumulating**: `wc -l state/decisions/2026-05-18.jsonl`
   should grow as new windows close

## Session-2 watchlist (Day 1 of Phase O re-soak)

### What to look for in the day-1 data

| signal | what it tells us |
|---|---|
| Fires/hour | Phase O baseline target ~4-5/hr (M.5 closes ~30% of cells) |
| Win-rate (Day 1) | >50% on tier 30-50% means SURV cell is recovering; <45% means new regime |
| L.5 trip count | 0 = clean day, 1 = expected on hard day, ≥2 = real problem |
| M.5 abstains | the bot's M.5-blocked Path-A candidates won't appear in JSONL — proxy via journal log lines |
| SURV canary trips | logged at WARNING level; first trip auto-Telegram'd |

### Day-1 thresholds for further action

- **Day 1 PnL ≥ +$300**: Phase O config holding well; widen J.2
  (Session 2 task #1) to enable hour-block redesign
- **Day 1 PnL in [−$90, +$300]**: nominal Phase O variance; stay
  the course
- **Day 1 PnL < −$90 (L.5 trips)**: investigate which cell bled,
  consider Kelly demotion 0.15→0.10 (PDF §7.4)
- **Day 1 multiple-L.5 + bankroll < $2,500**: STOP, re-audit before
  any further config changes; possibly the SURV canary margin is too
  loose (try −0.02 or −0.03)

### Open work items (from Session 1 close)

1. **J.2 per-tier-hour env-flag redesign**: design + implement so we
   can block tier 30-50% × {05, 06, 17, 21, 23, 00} UTC without
   also blocking tier 30-50% × hour 22 (a winner cell). ~1-2h.
2. **Decisions-tape observability**: operator-requested visibility
   for non-fire windows. Bot needs an `abstained` record kind; the
   dashboard React tape needs to render them. ~1h backend + frontend
   follow-up.
3. **N.5 regime classifier validity test** (from Phase N PDF §6):
   build a proxy regime classifier from |Δbps| + per-window
   realized-vol; backtest on n=755; compare to M.1a vol-ratio
   classifier.
4. **N.7 Kelly counterfactual** (from Phase N PDF §6): replay all
   fires under Kelly 0.10× and $5-flat to bound the strategy-class
   vs Kelly-variance attribution.

### NOT to do unless data motivates

- Re-enable M.1a v1 (falsifier on n=755 contradicted; new data needs
  to overturn before re-enable)
- Disable M.5 (PDF §7.1 primary recommendation; data-most-supported)
- Change bankroll back to $1k or further escalate to $5k+ (Day-1 data
  needed to assess +3× variance impact first)
- Change Kelly multiplier (defer until +5d of Phase O data accumulates)

## Cross-references

- Session 1 note: `2026-05-17-phase-O-session-1-bot-resumed.md`
- Phase N PDF: `pdfs/PHASE_N_FORENSIC_AUDIT.pdf`
- Phase O ledger: `state/phases/phase-O-remediation.md`
- Bankroll-reset memory: `memory/project_bankroll_reset_2026_05_17.md`
- Phase O checkpoint: `memory/checkpoint_phase_O.md`

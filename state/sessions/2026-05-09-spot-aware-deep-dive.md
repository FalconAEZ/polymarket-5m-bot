# 2026-05-09 — Spot-aware deep dive: gate, dashboard fix, edge audit, v2 + instant-settle

**Session:** continuation of the gate early-read; pulled forward to a wide-lens
audit + the "find the hidden edge" deep dive + v2 strategy + instant-settle
implementations.
**Branch:** `claude/jovial-hermann-7e103f` (worktree from `main` @ `1baf993`).
**Pickup:** 2026-05-09 ~16:30 UTC. Closed ~19:30 UTC. ~3h elapsed.
**Operator state across the session:** asked for honest reads, refined
prompts iteratively, approved each plan before action, deferred all
deploys to operator review post-gate.

## Headline

The bot peaked at **+$133.88** at 2026-05-09 05:30 UTC and gave it ALL back
(drawdown -$134.68 from peak, currently around -$0.80 → -$6 → +$5 across the
day depending on which exact minute you read). The data showed a hidden
edge: the 30-50% tier is real (50% WR, +$0.79/trade, n=54). The 50-70%
tier is the drag (-$77, 49% WR, n=195). Aggressive mode dilutes the edge
by firing 76% of all trades into 50-70%. The fix is `spot_aware_v2`
(tier-restricted, no fallback) shipped this session, NOT deployed —
deploys at the 48h gate.

The dashboard truth-source bug found mid-session ($54 PnL gap; oracle vs
PM-truth) is also fixed and deployed.

## What shipped (3 commits this session, all on PR #1)

### Commit `40e5a01` — v2 gate early-read

- `phase-prompts/phase-11.a-gate-2026-05-10-v2.txt` — improved gate prompt
  (full-history audit + dashboard-vs-truth diff + refinement plan deliverable)
- `runbooks/gates/spot-aware-paper.sh` — 5-criteria gate script
- `runbooks/scripts/audit_spot_aware_history.py` — per-era + per-tier matrix
- `runbooks/gate-evidence/phase-11.a.2{,-full-history,-dashboard-diff}.txt`
- `runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md` — the
  dashboard incident note (medium severity)
- `runbooks/decisions/phase-11.a.2-refinement-plan-2026-05-09.md` — ranked
  tightening rungs (rung 4 = tier-restricted v2, now implemented)

Verdict at 18.1h: **DEFER** (5 OK / 0 BREACH / 1 INFO under 24h pickup).

### Commit `e46a56c` — Edge-discovery deep-dive

- `runbooks/scripts/edge_discovery_audit.py` — multi-dim slicing + what-if
  filtered backtests
- `runbooks/research/edge-discovery-2026-05-09.md` — synthesis with peak
  +$133.88 / drop tier 50-70 → +$76 swing finding
- `runbooks/research/edge-discovery-2026-05-09-output.txt` — raw audit

Headline: dropping tier 50-70% would have produced **+$75.93 / +$1.31 per
trade** instead of -$0.80 / -$0.003 per trade. Same data, one filter.

### Commit `89d6fae` — v2 strategy + instant-settle

- `design/spot_aware_v2_tier_restricted.md` — locked spec
- `design/instant_settlement.md` — locked spec
- `src/polymarket_bot/strategies/spot_aware_v2.py` — new SpotAwareStrategyV2
- `src/polymarket_bot/gamma_resolver.py` — neutral top-level module (poll +
  re-resolve + realised_pnl)
- `src/polymarket_bot/_paper/runner.py` — async settle path with Gamma poll
  via `asyncio.to_thread`, fallback to Chainlink-local, alert on Nth timeout
- `src/polymarket_bot/_paper/decision_log.py` — record_settled accepts
  optional `resolution_source` param
- `scripts/run_paper.py` — dispatches v2 + reads INSTANT_SETTLE_* env vars
- `tests/test_gamma_resolver_top.py` (13 tests)
- `tests/strategies/test_spot_aware_v2.py` (12 tests)
- `tests/paper/test_runner_instant_settle.py` (4 tests)

Verification: ruff ✅ · mypy --strict 59 files ✅ · import-linter 3/3 KEPT ✅ ·
**369 pytest pass** (340 baseline + 29 new).

### Commit (pending) — code review fixes + deploy script + vault closeout

- Critical: made `_settle_current_window` async + wrapped gamma poll in
  `asyncio.to_thread` (was blocking event loop for up to 30s)
- Added alert on every Nth Gamma timeout (operator visibility into degraded state)
- Added warning log when `STRATEGY=spot_aware_v2 + SPOT_AWARE_AGGRESSIVE_MODE=1`
  conflict (silent-ignore was confusing)
- Removed unused LOG import in spot_aware_v2.py
- Moved `import time` to module top in gamma_resolver.py
- `runbooks/scripts/deploy-v2-and-instant-settle.sh` — gate-day one-shot
  deploy with pre-flight + dry-run mode + apply mode + rollback mode
- This session note + memory checkpoint refresh

### Adjacent — Dashboard PR #2 (claude/dashboard-pm-truth-fix-7e103f branch)

- Commit `ecc51b3` — backend serves PM-truth via resolver loop
- Commit `d19e438` — pnl_by_day field on /api/state
- DEPLOYED to VPS (after one redeploy due to a parallel session's revert).
  Current VPS HEAD: `d19e438`. `decisions_truth_source: polymarket`. ✅

## Discoveries / lessons

1. **Dashboard truth-source bug** (medium severity). Operator was about to
   revert based on -$43 dashboard reading; PM-truth was +$11 ($54 gap). Fixed
   in PR #2. Saved memory note `feedback_vps_deploy_verify_late.md` because
   another session reverted my deploy 9 min after I shipped it.

2. **Edge concentration**: aggressive mode fires 95% of the time on |Δ|<2
   bps (pure-noise zone) and 76% of the time in tier 50-70% (asymmetric
   payoff loser). Both findings independently justify v2.

3. **EV [0.02, 0.05) bucket is the WORST performer** (-$60 on n=57, 38%
   WR). The `p_win=0.54` aggressive fallback creates false-positive EV
   signals here. v2 drops the fallback entirely — priors miss = no fire.

4. **Per-day PnL view exists** post commit `d19e438`. The "TODAY" panel
   resets at 00:00 UTC by design; `pnl_by_day` field shows yesterday +
   today + 5 prior days as separate rows.

5. **Latency edge is for ORDER PLACEMENT, not settlement.** The operator
   conflated the two when complaining about 60s settle latency. Honest
   correction provided + still fixed the slow-settle (1-3s via Gamma poll)
   because it's a Phase 6 prereq and was a real annoyance.

6. **Bot uptime ≠ aggressive elapsed.** Bot was restarted at 13:21:05 UTC
   during orphan-FD recovery; aggressive config unchanged across restart;
   decisions JSONL continuous (zero loss). Always compute elapsed from the
   launch timestamp, not from systemctl uptime.

## What's deferred / queued

- **48h gate review** at 2026-05-10 22:26:15 UTC (~25h away from session close)
- **Gate-day deploy**: run `bash runbooks/scripts/deploy-v2-and-instant-settle.sh --apply`
- **PR #1 + PR #2 review** by operator before merge
- **7-day v2 re-soak** post-deploy
- **Append "FIXED at d19e438" annotation** to `runbooks/gate-evidence/phase-11.a.2-dashboard-diff.txt`
  after both PRs merge to main
- **React panel for `pnl_by_day`** (optional UI follow-up; backend data already
  exposed)
- **Pipeline latency wiring** (deferred Phase A.5 item — needs HealthAggregator
  in run_paper.py; do at the natural restart for v2 deploy or after)
- **Polymarket Streams WS** for sub-second settle (Phase 6 prereq; v1
  instant-settle does 1-3s via Gamma REST, "good enough" for paper)

## Hand-off pointer (next session)

Pick up at the 48h gate. Run order:

1. `bash runbooks/scripts/sync_staging.sh` — fresh data
2. `bash runbooks/gates/spot-aware-paper.sh` — gate verdict
3. `uv run python runbooks/scripts/edge_discovery_audit.py` — refresh edge data
4. **Decide**: PROMOTE v1 (no, per edge data) or REVERT + deploy v2 (recommended)
5. If REVERT + deploy: `bash runbooks/scripts/deploy-v2-and-instant-settle.sh --apply`
6. Verify per the script's post-deploy checklist
7. Vault closeout + memory checkpoint refresh
8. Push, merge PRs

Bot continues running v1+aggressive unchanged through the soak window.
Dashboard live with PM-truth + pnl_by_day.

## Anthropic spend

Cumulative: $0.405 (Phase 3 only). This session adds $0 (no LLM calls;
deterministic strategy + paper-trading code). Phase 11.A.2 still under
budget for the 7-day soak window per decision #14.

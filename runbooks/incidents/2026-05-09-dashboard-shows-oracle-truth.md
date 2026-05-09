# Incident: dashboard shows oracle-truth, not Polymarket-truth (2026-05-09)

**Discovered:** 2026-05-09 ~16:30 UTC during the Phase 11.A.2 gate
early-read session (v2 prompt: `phase-prompts/phase-11.a-gate-2026-05-10-v2.txt`).

**Severity:** medium. Strategy decisions are unaffected; operator
decision-making is affected (operator was about to revert based on
wrong numbers).

## Symptom

Operator reported "bot is sitting at -$39, 47.1% win rate" and was
considering revert. The laptop-side audit (after `sync_staging.sh` +
`resolve_decisions.py`) said **+$11.00 / 49.8% WR / 225 settled**. $54
PnL gap, 2.7pp WR gap.

## Root cause

The v3 dashboard backend (`apps/dashboard-server` on VPS at
127.0.0.1:8505) computes `bankroll.delta_usd` directly from
`/home/ops/polymarket-5m-bot/state/decisions/*.jsonl`. Those JSONL files
have `resolution_source = "chainlink-local"` — i.e., the bot's local
Chainlink AnswerUpdated reads, which disagree with Polymarket Streams
on ~33% of windows (per
`runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md`).

The post-hoc fix lives in `scripts/resolve_decisions.py` and runs as
part of `runbooks/scripts/sync_staging.sh` on the laptop. It writes
corrected decisions to `state/staging/decisions/`. The Streamlit
dashboard at `PMB_DASH_STATE_DIR=state/staging` reads this corrected
view. The v3 React dashboard on the VPS does NOT.

## Three numbers, three sources

| Source                              | PnL      | WR     | n_won | n_lost |
|-------------------------------------|----------|--------|-------|--------|
| Dashboard (VPS `/api/state`)        | -$43.07  | ~47%   | -     | -      |
| Raw VPS decisions (oracle-truth)    | -$38.07  | 47.1%  | 106   | 119    |
| Polymarket-truth (resolved)         | +$11.00  | 49.8%  | 112   | 113    |

The $5 between dashboard and raw oracle-truth is dashboard arithmetic
differences (bankroll computation vs raw cumulative-pnl) and one
unresolvable decision being skipped.

## Per-tier impact

The resolution gap is concentrated in the 50-70% tier (largest sample):

| Tier   | Oracle PnL | PM-truth PnL | Δ          |
|--------|------------|--------------|------------|
| 30-50% | +$63.26    | +$54.18      | -$9.08     |
| 50-70% | -$134.32   | -$78.20      | +$56.12    |
| 70-85% | -$10.00    | -$2.97       | +$7.03     |

Net: oracle UNDERSTATES the strategy by ~$54 vs Polymarket-truth.
Oracle says the 50-70% tier is a -$134 disaster; PM-truth says it's a
-$78 underperformer. Big behavioral difference if the operator is
tier-tuning based on the dashboard.

## Detection

The v2 gate prompt added a "dashboard-vs-truth diff" sub-step
(STEP 3.5) explicitly to catch this kind of drift. The diff fired
immediately on the first early-read pickup.

## Defense

**Short-term (this session):**
- Operator-facing reading guide (in
  `checkpoint_phase_11_a_x_b_dashboard_v3.md`) now states explicitly:
  the v3 dashboard's PnL is **oracle-truth**, not Polymarket-truth.
  For gate decisions, use the laptop-side audit only.

**Medium-term (separate task):**
- v3 dashboard backend either:
  (a) Runs `resolve_decisions.py` on demand against its own
      decisions JSONL (cheap; same code path as sync_staging),
  (b) Queries Gamma at settle time during decision processing
      (more invasive; requires backend change),
  (c) Both, with (a) as the safety net.

The recommended path is **(a)** — it's a copy of the existing
laptop-side fix, no new dependencies.

## Why this is medium-severity

- **Strategy unaffected**: the bot fires based on signals, not on
  what the dashboard shows. Aggressive-mode is firing fine.
- **Settlements unaffected**: real money never changes hands during
  paper trading; PnL is just bookkeeping. The bookkeeping is wrong.
- **Operator-decision affected**: the operator was about to revert
  aggressive-mode based on the wrong PnL. This is the actual harm.

If the v3 dashboard ever drives a real-money decision (Phase 11.B and
beyond), this becomes high-severity. Fix before Phase 11.B.

## Lessons

1. Any state file the bot writes that the dashboard reads needs an
   explicit truth-source annotation. "decisions.jsonl" is ambiguous;
   "decisions.raw.jsonl" + "decisions.resolved.jsonl" would be
   self-documenting.
2. Operator-facing reading guides (per the dashboard checkpoint) need
   to be machine-checked. A regression test that diffs the dashboard
   API output vs a known-good Polymarket-truth pull would have caught
   this before it confused the operator.

## Cross-refs

- `runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md` — the
  underlying Chainlink vs Polymarket Streams gap.
- `runbooks/incidents/2026-05-09-orphan-fd-decisions.md` — same
  dashboard backend; same surface.
- `runbooks/gate-evidence/phase-11.a.2-dashboard-diff.txt` — the
  numbers that started this incident note.
- `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_11_a_x_b_dashboard_v3.md`
  — operator-facing reading guide that needs updating.

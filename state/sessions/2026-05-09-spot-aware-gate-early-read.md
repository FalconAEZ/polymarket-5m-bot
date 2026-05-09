# 2026-05-09 — Phase 11.A.2 gate early-read + dashboard-truth bug discovery

**Session:** v2 prompt execution (`phase-prompts/phase-11.a-gate-2026-05-10-v2.txt`)
**Pickup time:** 2026-05-09 ~16:30 UTC (18.1h after aggressive launch, 6h
before the 24h pickup minimum, 30h before the 48h committed gate review).
**Branch:** `claude/jovial-hermann-7e103f` (worktree from `main` @ `1baf993`).

## What the operator asked for

Operator pulled the gate session forward — wanted a wider-lens audit
covering all paper-trading data, not just the aggressive window the v1
prompt focused on. Reported "bot is sitting at -$39 / 47.1% WR" (which
turned out to be the dashboard reading, not ground-truth — see Headline
finding below).

Specifically requested: improve the v1 prompt, then execute, leveraging
the obsidian vault for context.

## What shipped

1. **Improved gate prompt** at
   `phase-prompts/phase-11.a-gate-2026-05-10-v2.txt`. Adds a full-history
   audit pre-step, a dashboard-vs-truth diff sub-step, and a refinement-
   plan deliverable on top of the v1 work. v1 stays in tree.
2. **Full-history audit script** at
   `runbooks/scripts/audit_spot_aware_history.py`. Buckets fires by
   config era using the `mode=aggressive` rationale marker as the
   canonical boundary; reports per-era + per-tier WR/PnL/fire-rate.
   Output: `runbooks/gate-evidence/phase-11.a.2-full-history.txt`.
3. **Gate script** at `runbooks/gates/spot-aware-paper.sh`. Five
   criteria parallel to `runbooks/gates/phase-5.sh`. Exits with PROMOTE/
   REVERT/HOLD/DEFER verdict based on breach count + elapsed time.
4. **Gate evidence** at `runbooks/gate-evidence/phase-11.a.2.txt`.
   Verdict: **DEFER (under 24h elapsed; 4 OK / 0 BREACH / 1 INFO).**
5. **Dashboard-vs-truth diff** at
   `runbooks/gate-evidence/phase-11.a.2-dashboard-diff.txt`. Captures
   the $54 PnL gap between dashboard and Polymarket-truth.
6. **Incident note** at
   `runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md`.
   The dashboard backend on the VPS reads oracle-truth (uncorrected
   Chainlink-local resolution). Operator was about to revert based on
   wrong numbers. Medium severity (decisions OK, decision-making
   harmed).
7. **Refinement plan** at
   `runbooks/decisions/phase-11.a.2-refinement-plan-2026-05-09.md`.
   Tier × era matrix; what dashboard now exposes vs blind; ranked
   single-knob tightening rungs (rung 1 = drop aggressive, rung 4 =
   tier-restricted v2 strategy that needs its own design doc).

## Headline finding: dashboard shows oracle-truth, not Polymarket-truth

The dashboard on the VPS (`http://127.0.0.1:8505/api/state`) reports
**bankroll.delta_usd = -$43.07** and the user reads "47.1% WR". That
matches RAW oracle-truth from the VPS decisions JSONL within $5 (which
is dashboard arithmetic differences).

The Polymarket-truth audit (after `sync_staging.sh` runs
`resolve_decisions.py` against Gamma) reports **+$11.00 / 49.8% WR /
n=225 settled**.

$54 PnL swing. The 50-70% tier (largest sample, n=174) shows -$134 in
oracle-truth vs -$78 in Polymarket-truth — same direction, half the
hole.

This is the same surface the orphan-FD postmortem flagged (the v3
dashboard backend doesn't run resolve_decisions). The gap was
inevitable; the v2 prompt's dashboard-vs-truth sub-step caught it on
first pickup.

## Five-criteria gate state at this read

| # | Criterion                              | Threshold       | Actual (PM-truth)         | Verdict |
|---|----------------------------------------|-----------------|---------------------------|---------|
| 1 | Cumulative PnL (worst rolling 24h)     | ≥ -$50          | +$3.83                    | OK      |
| 2 | Fire rate (24h projected)              | ≤ 350/day       | 292/day                   | OK      |
| 3 | Net WR (only if n_settled ≥ 100)       | ≥ 47%           | 49.8% (n=225)             | OK      |
| 4 | Elapsed since aggressive launch        | ≥ 48h to PROMOTE| 18.13h                    | INFO    |
| 5 | Services healthy + zero exceptions/24h | active + 0      | active+active+active+active, 0 exc | OK |

Under oracle-truth (what the operator was reading): all 5 still pass —
PnL -$38 ≥ -$50, WR 47.1% ≥ 47%. Tighter on margin but no breach.

## Decision

**DEFER** the binding promote/revert until the operator-chosen pickup
time (24h or 48h elapsed). Strong DO-NOT-REVERT signal under both
truth views. The 30-50% tier crossed n=40 at 53.3% WR / +$54.18 — the
"looks hot but n=10" caveat from the launch session is now resolved
positive.

## Notable observations

- **30-50% tier has crossed the meaningful-n bar.** n=45 filled+settled,
  53.3% WR, +$54.18. Up from the launch-session n=10/87.5% reading. The
  edge is no longer noise.
- **50-70% tier is the drag**, even under PM-truth: 174 fills, 48.9% WR,
  -$78.20. Big sample. Worth thinking about for a tier-restricted v2.
- **Fire rate at 292/day** is well under the 350/day cap but high enough
  to give us the fast sample we wanted from loose-start. No fire-once-
  per-window violations.
- **Bot uptime ≠ aggressive elapsed** — bot was restarted 2026-05-09
  13:21:05 UTC during orphan-FD recovery. Decisions JSONL is continuous
  through the restart (zero loss per the orphan-FD postmortem). The v2
  prompt now flags this so future sessions don't get the math wrong.

## What's deferred

- Final promote/revert verdict (until ≥24h elapsed; ideally ≥48h).
- Dashboard-truth fix — separate task. Recommended path: copy
  `resolve_decisions.py`'s logic into the dashboard backend so it
  serves Polymarket-truth.
- Rung 4 tier-restricted v2 strategy — only if rungs 1-3 underperform
  later. Needs its own design doc per CLAUDE.md rule #1.
- Operator reading-guide update in the dashboard checkpoint to flag the
  truth-source caveat.

## Hand-off pointer

Next pickup: re-run `bash runbooks/gates/spot-aware-paper.sh` after
24h or 48h elapsed (2026-05-09 22:26:15 UTC or 2026-05-10 22:26:15
UTC). The script auto-classifies DEFER / HOLD / PROMOTE / REVERT
based on elapsed + breach count.

If a binding decision is wanted before 24h, the operator can override
by reading the script output and acting manually — gates pass; the
constraint is the decision-tree convention, not a hard one.

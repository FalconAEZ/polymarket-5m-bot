# 2026-05-17 — Phase N kickoff (forensic Session 1)

## Context handoff (from Phase M close 2026-05-17 12:43Z)

Bot HALTED at 12:43:23Z; bankroll $673, cum -$327. Sentinel reason = `operator-cooldown` (NOT the daily-PnL auto-halt — operator soft-floor pause). VPS bot-staging.service is `inactive`. Cron auto-resume at 23:53 UTC will NO-OP (sentinel reason mismatch). Five M.* layers live on HEAD `e72142c`:

- L.5 (daily PnL auto-halt) shipped Sat 12:52Z
- M.1a v0 (regime SHADOW log) shipped Sat 19:14Z
- M.1a v1 (chop+unknown ABSTAIN) shipped Sun 11:26Z
- M.5 (Path A regime wrapper) shipped Sun 11:45Z
- M.2 v0 (imbalance SHADOW log) shipped Sun 11:58Z

## Session 1 work

- N.0 audit infrastructure ✓
  - Pulled `state/decisions{,-resolved}/*.jsonl` from VPS → `/tmp/phaseN_data/` (738 KB tarball)
  - Built `scripts/research/phase_n_forensic_audit.py` (from scratch — `phase_l_soak_audit.py` referenced by the Phase N prompt was never committed in this branch; honest pushback noted)
  - Output: `runbooks/research/phase-N-forensic-output-2026-05-17.txt`
- N.1 peak-to-floor forensic ✓
- N.2 tier 30-50% deep dive ✓ (full, not just partial)
- Side addenda: tier 70-85% path A slice, per-regime label, per-imbalance label

## Dataset

- n=755 settled fires, window 2026-05-13 08:00Z → 2026-05-17 12:38Z (4.2 days)
- 100% strategy=`spot_aware_v2_1`, mode=`kelly_multi` (Kelly 0.15× + replay throughout)
- 614 actually filled (141 zero-PnL records — settled but not filled, e.g. phantom-defended)
- 127 of 756 settlements are `settled_correction` (truth-corrected — 17% correction rate)
- M.1a regime annotations: 83/755 fires (only Sat 19:14Z onward)
- M.2 imbalance annotations: 3/755 fires (only Sun 11:58Z onward, all labeled `too_thin`)

## Headline findings (full output in `runbooks/research/phase-N-forensic-output-2026-05-17.txt`)

1. **Peak confirmed at 2026-05-15 15:40:00Z** — fire #445/755 was a tier 30-50% DOWN
   bet of $92.58 that won +$92.93, pushing cum-PnL to +$1,235.41. Bankroll
   peak ≈ $2,235.

2. **First post-peak loss came in the SAME 5-min window** — fire #446 at
   15:45:15Z was tier 70-85% DOWN (Path A), Δbps=-7.24, p_win=0.80 (the
   v2.1 priors-ceiling), bet $91.74 → LOST -$91.76. Zero intervening wins.

3. **SURV cell (tier 30-50% × |Δ|≥5) — Phase L's "surviving winner" — broke**:
   - Pre-peak: n=112, WR=60.7%, $/tr=+$12.78, PnL=+$1,431
   - Post-peak: n=228, WR=46.5%, $/tr=-$5.09, PnL=-$1,161
   - The peak-to-floor swing of -$1,562 is mostly explained by this one cell.

4. **Tier 70-85% Path A is a 5-day net loser**:
   - n=237, WR=74.3%, $/tr=-$1.55, PnL=-$368
   - 100% are DOWN-side (H.2.12 path-A block_up is doing its job)
   - WR 74.3% is below ~77.5% break-even at $0.71-0.85 entry cost → bleeder
   - This is exactly what M.5 was designed to catch; need to audit whether
     M.5 ever ACTIVATED (cold-start n<20 hypothesis from prompt B.5).

5. **CH3 cell (tier 30-50% × |Δ|<5) post-peak n=0**: Phase J.1.5 fold is
   confirmed working. CH3 ALL-time still net negative (n=178 pre-fold,
   WR=34.8%, PnL=-$228) but isolated to pre-fold history; not contributing
   to the recent bleed.

6. **M.1a v1 chop-abstain may be inverted** (n is small — n=23 chop, 58 mixed
   on annotated subset only; honest pushback):
   - regime=chop:     n=23, WR=60.9%, $/tr=+$1.33, PnL=+$30.57   ← WINNING
   - regime=mixed:    n=58, WR=44.8%, $/tr=-$5.11, PnL=-$296.28  ← LOSING
   - regime=trending: n=2 (too small)
   - M.1a v1 abstains chop+unknown. If the labels are correct, M.1a v1 was
     abstaining WINNERS while letting the LOSING "mixed" regime through.

7. **Today's bleed (05-17, n=22 tier 30-50%, PnL=-$30) is small relative to
   the broader 5-day picture**. The operator's at-halt impression that
   "today's losses are tier 30-50%" was right for today but the dominant
   peak-to-floor driver was SURV-cell post-peak + tier 70-85% Path A.

## What's NOT in the data (honest limits)

- **No persistent spot tick capture** — only fire-time snapshots. Regime
  classifier validity testing (N.5) is bounded by this; can't rebuild
  a 5m/10m vol ratio for fires that fired before M.1a v0 shipped.
- **Imbalance annotation n=3** — M.2 v0 was live for only 45 min before
  halt. No meaningful per-label stats.
- **Book snapshot history beyond fire-time does not exist on VPS**.
- **45-h bleed window is statistically small** — findings are SUGGESTIVE,
  not definitive. Per prompt N-P3.

## Files written this session

- `scripts/research/phase_n_forensic_audit.py` (NEW — 380 LOC)
- `runbooks/research/phase-N-forensic-output-2026-05-17.txt` (NEW — full audit text)
- `runbooks/research/phase-N-forensic-summary.md` (NEW — operator briefing, ≤1 page)
- `state/sessions/2026-05-17-phase-N-kickoff.md` (this file)
- `state/phases/phase-N-forensic-audit.md` (NEW — Phase N ledger)
- `memory/checkpoint_phase_N.md` (NEW — cross-session checkpoint)
- `memory/MEMORY.md` (UPDATED — Phase N entry, Phase M marked PAUSED-IN-FORENSIC)

## Bot state — DO NOT RESUME

- HEAD `e72142c`, branch `claude/jovial-hermann-7e103f`
- bot-staging.service `inactive`
- halt.sentinel reason `operator-cooldown` (cron auto-resume will NO-OP)
- Phase N is investigation-only; no env flips, no restarts, no code ships
- Operator must clear sentinel manually to resume — after Phase O remediation

## Session 2 scope proposal (for operator review)

Confidence-ranked by current findings; operator picks 2-3:

A. **M.* feature audit deep-dive** (N.3) — was M.5 ever ACTIVE?
   re-compute compute_path_a_metrics over full 5-day data;
   verify M.1a v1 abstain inversion suspicion on the annotated subset;
   walk through 3-5 sample fire pipelines end-to-end.

B. **SURV cell post-peak decomposition** (N.2 follow-up + N.5) —
   what changed in the SURV cell post-peak? Per-day, per-side, per-hour,
   per-Δbps within SURV. Compute proxy regime (spot delta vs window-open)
   for ALL 755 fires (not just M.1a-annotated subset) and re-run per-regime.

C. **Counterfactual PnL trajectories** (N.7) — replay all 755 fires at
   Kelly 0.10× and at $5-flat (locked decision #9) to separate
   strategy-class question from Kelly-variance question.

D. **Per-UTC-hour bleed forensic** (N.7 partial) — hours 17 / 21 / 23 are
   the worst losers on tier 30-50%. J.2 blocks 22/23/0 × tier 70-85% but
   doesn't cover 30-50% × bleed-hours. Map a candidate J.2-extension.

Recommendation: A + B as Session 2 (forces falsification of the strongest
two findings before chasing remediation). C + D as Session 3 prep.

## Session 1 close

- N.0 done · N.1 done · N.2 done (more comprehensive than the prompt's
  "partial" target — n=755 supports the full slice)
- N.3 / N.4 / N.5 / N.6 / N.7 / N.8 pending Sessions 2-4
- Anthropic spend this session: ~$1 (research-only, no code beyond audit
  script)
- Hard ceiling met: no bot env flips, no restart, no src/* changes

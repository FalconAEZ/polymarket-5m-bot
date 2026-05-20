# Phase T — Directional bot revival prompt (next session)

**Authored:** 2026-05-20.
**Worktree:** `.claude/worktrees/phase-T-directional-revival`
**Branch:** `claude/phase-T-directional-revival` (tracks `origin/claude/phase-P-hard-reset`)
**Base commit:** `9516f39` (Phase P session 3 + Phase Q sidecar + dashboard fix)
**Risk class:** dormant — bot currently halted per decision #23. **DO NOT FLIP TO LIVE** without operator's explicit re-deploy approval.
**Companion phase deferred:** Phase S MMB pushed to `origin/claude/phase-S-market-maker` @ `8fe6007` with `pdfs/PHASE_S_MMB_OVERVIEW.pdf` as the operator-reference doc. Resume MMB only after directional builds bankroll OR Phase T fails its gate.

---

## §1. Why this phase exists (the operator decision 2026-05-20)

After reviewing the MMB overview PDF + the comparative analysis (copy-trade vs directional vs MMB), operator chose to revive the directional bot first and build bankroll before deploying MMB. **Stated rationale:** prove out the directional class with the post-forensic improvements before committing real $1k to the maker-ladder class.

**The honest framing this phase must respect** (per saved feedback on family/friends framing):
- Cumulative realized PnL across Phases G→P = ~$0 net on n=~3,500 fires
- Phase G measured 50.0% WR / −$18.96 net = zero edge
- Phase K peaked +$1,235 in 3 days then collapsed −$1,294 in 18h
- Phase M halted at −$327 with 5 defense layers shipped in 22h
- Phase N forensic identified the SURV cell flip as the killer
- Operator override of decision #23 (directional bot halted) is **explicit and informed**, not silent

This is NOT a fresh start. It's a targeted revival aimed at fixing the specific failure modes Phase N forensic identified.

---

## §2. Starting state — what's already shipped at `9516f39`

Per `memory/checkpoint_phase_P.md` + Phase Q sidecar commit `599b5ff`:

| Layer | Status | What it does |
|---|---|---|
| **J.1.6 baseline** | Active | Kelly 0.15× + `BANKROLL_REPLAY_ENABLED=true` |
| **J.1.5 fold** | Active | CH3 cell (tier 30-50% × \|Δbps\|<5) blocked. Confirmed: 0 CH3 fires post-fold. |
| **H.2.12 path-A block** | Active | Tier 70-85% × side=UP blocked. Confirmed: 0 of 237 fires UP-side. |
| **J.2 hour-blocklist** | Active (partial) | UTC 22/23/00 × tier 70-85% blocked. **PHASE N FOUND THIS HAS GAPS** (see §3 improvement #1). |
| **L.5 daily-loss guard** | Active | Halt at UTC 23:50 if today's PnL ≤ −$30. Confirmed working. |
| **MMD detector (bukosabino/ta)** | **Shadow** mode | Annotates fires with regime label; not gating. 29 tests. |
| **MMD_ABSTAIN_BY_SIDE** | Code shipped, default OFF | Phase Q sidecar — side-conditional MMD gate |
| **PMB_STARTING_BANKROLL + BANKROLL_REPLAY_ENABLED** | Dashboard honors them | UI shows correct bankroll post-replay |

**Disabled relative to Phase M:**
- M.1a v1 (chop-abstain) — Phase N falsified this on n=755
- M.5 (Path A rolling-WR abstain) — correctly designed, but Phase P stripped it back during the hard revert; needs re-introduction as part of improvement #2 below

**Required reading before any code change:**
1. [pdfs/PHASE_N_FORENSIC_AUDIT.pdf](../pdfs/PHASE_N_FORENSIC_AUDIT.pdf) — the 22pp study that identified what to fix
2. [pdfs/PHASE_S_MMB_OVERVIEW.pdf](../pdfs/PHASE_S_MMB_OVERVIEW.pdf) — fetch from `origin/claude/phase-S-market-maker` for the comparison framing
3. [memory/checkpoint_phase_K.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_K.md) — what actually happened
4. [memory/checkpoint_phase_P.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_P.md) — what's live now (dormant)

---

## §3. The 6 improvements (in priority order)

Each derives from a specific Phase N forensic finding. Land them as separate commits with tests.

### Improvement #1 — Extend J.2 hour-blocklist to tier 30-50%

**Source:** Phase N forensic finding F7.
**The gap:** J.2 currently blocks UTC 22/23/00 only for tier 70-85%. Phase N data (n=755, 5 days) shows tier 30-50% bleed hours are different:

| UTC hour | Tier 30-50% PnL |
|---|---:|
| 05 | −$266 |
| 06 | −$251 |
| 17 | −$259 |
| **21** | **−$516** |
| 23 | −$288 |
| 00 | −$168 |

**Implementation:** extend the blocklist to a tier×side×hour 3D lookup. Block tier 30-50% in those hours (both sides — verify in Phase N data if side-specific gap exists).
**Tests:** unit test that fires in blocked hours abstain; backtest replay over Phase K-M data should show ~+$1,748 prevented loss.
**Files:** `src/polymarket_bot/strategies/spot_aware_v2_1.py` (or wherever J.2 lives), `src/polymarket_bot/strategies/blocklist.py` if it exists as a separate module.

### Improvement #2 — SURV-cell-flip detector

**Source:** Phase N forensic finding F1 — the killer.
**The problem:** The SURV cell (tier 30-50% × \|Δbps\|≥5) flipped from 60.7% WR pre-peak to 46.5% WR post-peak. Static blocklists can't catch this; you need rolling per-cell WR with abstain triggers.
**Design sketch:**
```python
@dataclass
class CellFlipDetector:
    window_size: int = 20            # rolling N fires per cell
    abstain_threshold_pp: float = 5  # abstain if rolling_wr < break_even - 5pp
    min_samples: int = 10            # don't abstain on noise

    def should_abstain(self, cell_key, fill_price, recent_fires):
        if len(recent_fires) < self.min_samples:
            return False
        rolling_wr = sum(f.won for f in recent_fires[-self.window_size:]) / min(self.window_size, len(recent_fires))
        break_even = fill_price  # for binary 0/1 settlement
        return rolling_wr < (break_even - self.abstain_threshold_pp / 100)
```
**Tests:** simulator test reproducing the SURV cell flip; detector should abstain within 10-15 fires of the regime shift, saving ~$800-$1,000 of the $1,562 swing.
**Files:** new `src/polymarket_bot/strategies/cell_flip_detector.py`, wire into `MarketMakerStrategy.compute_fire()` after the existing gates.

### Improvement #3 — MMD gate-mode promotion (only after fresh soak validates)

**Source:** Phase P §10 + Phase O failure (1 fire = −$163 lost trying to promote MMD without validation).
**The discipline:** MMD lived in shadow for ~24h in Phase P before halt. Per-label edge wasn't validated on enough data. Phase O tried to skip the validation and ate a loss.
**Plan:** at restart, MMD stays SHADOW. After 5 days of fresh post-restart data, audit `mmd_label` distribution + per-label realized $/tr. ONLY promote to gate mode if MIXED label shows > +$0.50/tr and CHOPPY shows < $0/tr (per Phase Q backtest hypothesis).
**Tests:** none for the gate change (it's a config); add audit script `scripts/research/mmd_label_per_label_pnl.py` that the operator runs at T+5d.

### Improvement #4 — Kelly demotion to 0.10× until #2 ships

**Source:** Phase K variance amplification math.
**The reasoning:** Kelly 0.15× turned a regime shift into a $1,562 swing in 45h. Until Improvement #2 (cell-flip detector) is live + tested, demote to 0.10× to reduce variance amplification. Doesn't give up compounding — just slows it. Re-promote to 0.15× after #2 is validated in 5+ day soak.
**Implementation:** env var `KELLY_MULT=0.10` (already supported per Phase J.1.6 design).
**Tests:** none beyond verifying the env-var path; existing tests cover Kelly math.

### Improvement #5 — Per-cell-per-hour edge table (replaces flat hour blocklist)

**Source:** Phase N forensic finding F7 extension.
**The opportunity:** Phase N data shows WIN hours too on tier 30-50% — UTC 15 (+$483), UTC 19 (+$691), UTC 22 (+$302). A 3D lookup `(tier, side, hour) → multiplier` could:
- Block bleed hours (set multiplier to 0)
- Optionally boost win hours (set multiplier to 1.5x)
**Risk:** boosting introduces new variance. **Recommend block-only first, no boost.** Add boost as Improvement #5b after #5 ships and 5 days of data confirms win-hours are stable.
**Tests:** the table itself + a config-driven evaluation harness.

### Improvement #6 — Cell-staleness flag

**Source:** Phase K lesson — bot kept firing the SURV cell at full size after it went cold.
**The mechanic:** If a cell hasn't fired in N hours, mark its priors as "stale." Require a fresh-sample threshold (e.g. n ≥ 10 fires in the last 24h) before sizing up beyond the minimum bet.
**Tests:** staleness logic + integration test that simulates cell-cold scenario.

---

## §4. Session 1 task list (the next live session picks this up)

Before any code changes:

1. **Verify the worktree is at `9516f39`** with monitoring services on VPS dormant (per current state — but re-verify at restart):
   ```bash
   ssh -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 "systemctl is-active bot.service bot-staging.service"
   # Expect: inactive inactive
   ```
2. **Re-read** the Phase N PDF + the MMB overview PDF (compare-and-contrast)
3. **Run the test suite** at `9516f39` baseline: `uv run pytest -q` (expect green; record n)
4. **Pull the data** the Phase N forensic worked from: `runbooks/research/phase-N-forensic-output-2026-05-17.txt` + `runbooks/research/phase-L-soak-audit-2026-05-16.txt`
5. **Backtest Improvement #1** (hour-blocklist extension) against Phase K-M data offline. Quantify $-prevented. If quantification doesn't show ≥+$500 prevention, revisit the hours from the data, not assumed values.
6. **Ship Improvement #1** as a separate commit if the backtest justifies it
7. **Start Improvement #2** (cell-flip detector) — design doc first per anti-vibe-coding rule #1, then code
8. **STOP at 50% context** per CLAUDE.md session discipline

---

## §5. The gate — when does Phase T succeed or fail?

**SUCCESS criteria** (gate to consider scaling bankroll + later layering MMB):
- 14-day soak on $1k bankroll
- Cumulative realized PnL > +$300 (≈ 30% in 2 weeks; aggressive but plausible if improvements work)
- Zero unrecovered heartbeat misses, zero halt-sentinel trips
- Fill rate sane (in normal bounds)
- Per-cell rolling WR stays within 5pp of pre-fire WR across the soak (i.e. SURV cell flip is caught + handled by Improvement #2)

**FAIL criteria** (Phase T concluded; revisit strategy class):
- Cumulative PnL ≤ $0 at T+14d
- OR any incident requiring operator intervention (halt unrecovered, defense bypass, etc)

**MARGINAL** (cum PnL ∈ [$0, +$100]): extend 7 more days; if still marginal after 21 days, conclude that the directional class doesn't justify continued investment regardless of further patches.

**Honest expectation:** the audit data doesn't strongly predict success. Phase N's last line was "what the directional class can express in 5-min resolution windows with single-fire takers reached its limit." The 6 improvements address specific failure modes but don't change the strategy class. **Bet a small budget of time on Phase T, set a hard gate at 14 days, accept the outcome either way.**

---

## §6. What happens to MMB during Phase T

- Branch `claude/phase-S-market-maker` @ `8fe6007` on origin contains everything: code shipped, 809 tests green, operator-handoff doc, MMB overview PDF
- **Do NOT deploy MMB during Phase T**. The operator's stated plan: directional first, MMB after.
- If Phase T PASSES → after the bankroll builds (e.g. $1k → $2k+), operator can choose:
  - (A) Continue scaling directional only
  - (B) Diversify: keep directional running, deploy MMB on a separate $1k slice (would need fresh funding given decision #12 HW wallet trigger)
  - (C) Pivot entirely to MMB
- If Phase T FAILS → MMB becomes the obvious next bet, deploy per `runbooks/OPERATOR_HANDOFF_PHASE_S.md`

---

## §7. Don't-do rules

- Do NOT re-introduce **M.1a v1** (chop-abstain). Phase N falsified it on n=755. The activation evidence was n=23 — too small.
- Do NOT promote **MMD to gate mode** before 5 days of fresh post-restart shadow data
- Do NOT raise **Kelly back to 0.15×** before Improvement #2 ships
- Do NOT change strategy code during the 14-day soak. Patches mid-soak invalidate the gate.
- Do NOT increase bankroll past $2k without HW wallet (locked decision #12 + #23 addendum)
- Do NOT touch the Phase S MMB branch — it's frozen until Phase T resolves

---

## §8. Quick links

- Phase N forensic: [pdfs/PHASE_N_FORENSIC_AUDIT.pdf](../pdfs/PHASE_N_FORENSIC_AUDIT.pdf)
- Phase S MMB overview: `git fetch origin claude/phase-S-market-maker && git show origin/claude/phase-S-market-maker:pdfs/PHASE_S_MMB_OVERVIEW.pdf`
- Phase P MMD ship PDF: [pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf](../pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf)
- Phase Q MMD backtest: [pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf](../pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf)
- Phase K live readiness: `pdfs/PHASE_K_LIVE_READINESS.pdf` (operator Desktop)
- VPS access: `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/reference_vps_ssh.md`
- Operator handoff (MMB, deferred): `git show origin/claude/phase-S-market-maker:runbooks/OPERATOR_HANDOFF_PHASE_S.md`

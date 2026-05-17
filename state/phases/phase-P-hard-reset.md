# Phase P — Hard Revert to J.1.6 + MMD Build

**Authored:** 2026-05-18 (operator UAE local) — actual VPS deploy at 2026-05-17 21:37:28 UTC.
**Source-of-truth prompt:** `~/Desktop/phase-P-hard-reset-2026-05-18.txt` (operator desktop).
**Branch:** `claude/phase-P-hard-reset`, cut from `83fe119` (last commit before L.5 shipped on Phase M).
**Status:** Session 1 CLOSED; Session 2 + 3 PENDING.

## Why this phase

Operator framing (raw — see prompt): the bot shipped 5 layers in 22 hours
during Phase M (L.5 + M.1a v0 + M.1a v1 + M.5 + M.2 v0) on a downtrend,
then layered Phase O remediations (SURV canary, $3k bankroll, L.5 scale,
M.5 tune). One fire post-Phase O Session 1 lost −$163; Phase N forensic
on n=755 falsified M.1a v1 and confirmed M.5 was the right design shipped
3 days late. Operator's call: stop, undo, restart from the J.1.6 peak
config, add **one** new thing (a Market Mode Detector) on data-grounded
process, then re-soak.

## Session 1 — Hard revert + dashboard reset + kickoff PDF — CLOSED 2026-05-17 21:37 UTC

Outcome: bot LIVE on the J.1.6 baseline at $1,000 bankroll. Mac main repo
+ VPS + GitHub aligned on `claude/phase-P-hard-reset` HEAD. Dashboard fully
reset. PHASE_P_KICKOFF.pdf rendered. 5-day forensic data preserved on the
new branch + archived on VPS.

### What landed

1. **Branch cut** from `83fe119` (J.1.6 anchor; docs-only commit, last
   before L.5). New branch `claude/phase-P-hard-reset` pushed to GitHub.
2. **Survival preserve** at `53e08c9`: cherry-picked Phase N PDF + builder
   + audit scripts + 14 charts + runbooks + phase ledgers + session notes
   from `e3133e6` (jovial-hermann HEAD pre-revert).
3. **VPS aligned**: bot stopped, `.envrc` backed up to
   `.envrc.bak.phase-P-revert-2026-05-18`, modified files stashed, branch
   checked out, `.envrc` rewritten to J.1.6 target (56 lines; all M/O env
   vars stripped).
4. **5-day decisions archived**: `state/decisions/2026-05-{13..17}.jsonl`
   + `state/decisions-resolved/2026-05-{13..17}.jsonl` moved to
   `archived/phase-P-reset/`. Fresh empty `2026-05-18.jsonl` touched.
5. **Dashboard reset**: systemd drop-in
   `/etc/systemd/system/dashboard-server.service.d/bankroll.conf` removed;
   daemon-reload + restart; `/api/state` confirms
   `starting_usd=$1000 / current_usd=$1000 / delta_usd=$0 / today.n_settled=0
   / decisions[]=0 / cumulative_pnl_series=0`.
6. **Bot restart** at 2026-05-17 21:37:28 UTC, MainPID 1019607. Startup
   log shows the J.1.6 signature exactly:
   `spot_aware_v2_1: kelly_mult=0.15 max_bet_abs=$500 multi_fire_cap=1
   tier_relax_p_win_fallback=None tier_relax_price_floor=0.420
   block_up_in_tiers=('70-85%',) hour_blocklist_utc=(22, 23, 0)
   hour_blocklist_tiers=('70-85%',)` and
   `bankroll_getter wired (start=$1000.00, replay=True, cap=1)`. No L.5
   / M.5 / M.1a / SURV / MMD lines.
7. **Vault**: `runbooks/research/phase-P-feature-inventory.md`,
   `state/phases/phase-P-hard-reset.md` (this file),
   `state/sessions/2026-05-18-phase-P-session-1-revert.md`,
   `memory/checkpoint_phase_P.md`, `memory/MEMORY.md` updated (Phase O
   marked SUPERSEDED, Phase P added),
   `memory/project_bankroll_reset_2026_05_17.md` marked HISTORICAL.
8. **PDF**: `pdfs/PHASE_P_KICKOFF.pdf` rendered via
   `pdfs/build_phase_p_kickoff_pdf.py`.

### Acceptance — all green

- [x] Mac main repo HEAD == VPS HEAD == origin/claude/phase-P-hard-reset
- [x] bot-staging.service active on the new HEAD; J.1.6 baseline confirmed in log
- [x] Dashboard `/api/state`: $1,000 / $1,000 / $0 / empty decisions[] / empty cumulative_pnl_series
- [x] `state/decisions/2026-05-18.jsonl` exists (empty)
- [x] `state/decisions{,-resolved}/archived/phase-P-reset/*.jsonl` preserves 5-day data
- [x] Dashboard systemd drop-in `bankroll.conf` REMOVED
- [x] `state/halt.sentinel` absent
- [x] `pdfs/PHASE_P_KICKOFF.pdf` rendered
- [x] Vault + memory checkpoint + MEMORY.md updated
- [x] No Phase M/O bot-runtime code in `src/` on the new branch
- [x] Forensic data (Phase N PDF + audit script + charts) survives

## Session 2 — MMD research + backtest on n=756 — CLOSED 2026-05-18

Outcome: top-2 MMD candidates evaluated + backtested on Phase N forensic
data (n=756 settled fires). Adapter A (`bukosabino/ta` rule-based) locked
as the Session 3 ship. Bot stayed LIVE on J.1.6 baseline through Session 2
— zero env flips, zero src/ ships.

### What landed

1. **Phase N data acquired locally** at `/tmp/phase-P-mmd-data/` via SCP
   from VPS archive `state/decisions{,-resolved}/archived/phase-P-reset/`.
   Loader: `scripts/research/phase_n_forensic_audit.py::load_data`.
   n_settled_with_won = 756.
2. **Binance 1m klines cached** at `state/research/binance_historical/btcusdt_1m_2026-05-12_to_2026-05-18.parquet`
   (8,528 bars covering 2026-05-12 → 2026-05-17 22:07Z, includes 24h pre-window
   lookback buffer). Bulk-fetched from public `/api/v3/klines`.
3. **Backtest script** at `scripts/research/phase_p_mmd_backtest.py` —
   loads fires, fits both adapters, classifies each fire by 60-min lookback
   window, computes per-label WR/$tr/n/mean-conf tables + co-occurrence
   + WR-gap-vs-gate verdict.
4. **Adapter A (`bukosabino/ta` rule-based)**: MIXED=271 fires 57.9% WR
   (+$1.94/tr +$526), DOWN=173 53.8% (-$2.03 -$352), CHOPPY=193 53.9%
   (-$2.29 -$443), UP=119 48.7% (-$1.86 -$222). Best-worst WR gap +9.2pp
   (1pp shy of 10pp gate, within ±10.7pp noise CI). Counterfactual
   abstain-non-MIXED: +$1,018 PnL improvement on actual −$492.
5. **Adapter B (`hmmlearn` 4-state HMM)**: MIXED=184 60.3% (+$2.40
   +$441), UP=108 57.4% (-$2.49 -$269), DOWN=264 53.0% (-$0.78 -$206),
   CHOPPY=200 49.5% (-$2.28 -$457). WR gap +10.8pp PASSES gate.
   Counterfactual: +$933 PnL improvement (in-sample caveat).
6. **Cross-validation**: both adapters agree MIXED is the only profitable
   label. Co-occurrence diagonal strong in CHOPPY (74) and MIXED (68);
   weaker on UP/DOWN (different definitions of trending).
7. **Pick locked**: **Adapter A** (operator-confirmed 2026-05-18) for:
   simpler integration (no training step), deterministic output, lighter
   dep footprint (~3 MB vs ~25 MB), higher actionable PnL (+$1,018 vs
   +$933), no in-sample fit caveat. WR-gate miss is not statistically
   load-bearing.
8. **Design locked** at `design/P.1-market-mode-detector-integration.md`
   — module signature, plumbing pattern, bar-feed wiring (Binance REST
   poll every 30s), 10 env flags (all default off), failure modes (HARD
   pass-through on UNKNOWN), 12-test minimum for Session 3, rollback
   procedure, Phase Q decision matrix.
9. **PDF** at `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf` (11 pp + 4
   embedded charts) — builder at `pdfs/build_phase_p_session2_pdf.py`.
10. **Vault**: this ledger updated, session note at
    `state/sessions/2026-05-18-phase-P-session-2-mmd-research.md`,
    memory checkpoint updated, commit + push.

### Acceptance — all green

- [x] Top-2 MMD candidates evaluated against P.2.1 criteria + backtested on n=756
- [x] `runbooks/research/phase-P-mmd-backtest-2026-05-18.md` + 4 charts rendered
- [x] `design/P.1-market-mode-detector-integration.md` locked
- [x] `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf` rendered (11 pp)
- [x] Bot still LIVE on J.1.6 baseline; zero env flips; zero src/ ships
- [x] Vault: session note + memory checkpoint + commit + push

## Session 3 — MMD shadow-ship + 5-day re-soak — PENDING

Outcome target: chosen MMD ships to bot in SHADOW mode (rationale
annotation only, no firing change). 5-day observation window opens.

Trigger: operator GO after Session 2 PDF review.

## Cross-references

- Predecessor: `memory/checkpoint_phase_O.md` (Phase O Session 1 — SUPERSEDED)
- Phase N (preserved): `memory/checkpoint_phase_N.md`, `pdfs/PHASE_N_FORENSIC_AUDIT.pdf`
- Phase J anchor: `memory/checkpoint_phase_J.md` (J.1.6 = Kelly 0.15× + replay)
- Source-of-truth prompt: `~/Desktop/phase-P-hard-reset-2026-05-18.txt`
- Feature inventory: `runbooks/research/phase-P-feature-inventory.md`
- Session 1 note: `state/sessions/2026-05-18-phase-P-session-1-revert.md`
- PDF: `pdfs/PHASE_P_KICKOFF.pdf` (builder at `pdfs/build_phase_p_kickoff_pdf.py`)

## Hard DO-NOTs (operator-stated)

- Do not re-add any Phase M/O bot-runtime feature during Session 2 or 3.
- Do not change the bankroll from $1,000 (decision #10 restored).
- Do not activate MMD on small-n during Session 3 — shadow first, always.
- Do not re-introduce M.5 / SURV canary in Phase P — wait for the
  Phase Q decision after Day-5 MMD re-soak data.

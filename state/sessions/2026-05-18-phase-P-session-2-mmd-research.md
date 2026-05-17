# 2026-05-18 — Phase P Session 2 — MMD research + n=756 backtest

**Bot state at session start + close:** unchanged. Active on
`claude/phase-P-hard-reset@95a75e4` at MainPID 1019607 since 2026-05-17
21:37:28 UTC, $1,000 bankroll, J.1.6 baseline. **Zero env flips, zero
src/ ships this session** — research-only per prompt P.2.5.

Session 2 ran same-day as Session 1 (operator-directed). Plan target
T+1-3 days compressed to T+0; rationale: backtest is read-only on the
preserved Phase N data, doesn't depend on Session-1 baseline soak.

## Operator decision points this session

1. **Top-2 shortlist confirmed by self-research** — bukosabino/ta + hmmlearn
   (dropped pandas-ta duplicate; dropped mlfinlab as research-grade;
   dropped backtrader on GPL; GitHub search yielded no qualified
   community repos at ≥ 100 stars + recent activity matching the criteria).
2. **MMD pick = Adapter A (bukosabino/ta)** — operator-confirmed via
   AskUserQuestion at end of backtest. Rationale: simpler, deterministic,
   higher actionable PnL counterfactual, no in-sample training caveat.

## Session 2 sequence (chronological, VPS UTC)

1. **21:50–21:54 UTC** — SCP-pulled Phase N archived JSONL data from
   VPS `state/decisions{,-resolved}/archived/phase-P-reset/2026-05-{13..17}.jsonl`
   to local `/tmp/phase-P-mmd-data/`. Verified Phase N loader joins
   fires + settlements + corrections correctly (n_fired=756, n_settled=757,
   n_settled_correction=128, n_settled_with_won=756 after join).
2. **21:55–21:58 UTC** — Inspected fire schema. Per-fire snapshot has
   only 4 spot points (spot_now, window_open_spot, oracle_last,
   open_oracle); no tick history. Decided to use Binance public REST
   `/api/v3/klines` BTCUSDT 1m bars as the dense input.
3. **21:59 UTC** — Wrote `scripts/research/phase_p_mmd_backtest.py`
   (~500 LOC): Binance bulk-fetcher + parquet cache; `TARuleMMD`
   adapter (ADX > 25 + momentum sign + BB-width compression); 
   `HMMRegimeMMD` adapter (4-state Gaussian HMM on (return × 1e4, vol)
   with diag covariance to avoid Cholesky non-PD failure on tiny
   variances); per-label aggregation; ASCII + markdown report writer;
   matplotlib chart pipeline (4 charts).
4. **22:01 UTC** — First run failed on numpy column_stack length
   mismatch in HMM features (off-by-one). Fixed.
5. **22:03 UTC** — Second run failed on Cholesky non-PD ("'covars'
   must be symmetric, positive-definite"). Fixed by scaling log-returns
   ×1e4 + switching from full to diag covariance + min_covar=1e-3.
6. **22:05 UTC** — Third run GREEN. Backtest classified all 756 fires
   in seconds. Reports + 4 charts rendered.
7. **22:08–22:15 UTC** — Wrote `design/P.1-market-mode-detector-integration.md`
   (full design lock; 230 lines; 11 sections).
8. **22:15–22:25 UTC** — Built `pdfs/build_phase_p_session2_pdf.py` +
   rendered `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf` (11 pages, 293 KB,
   4 embedded charts).
9. **22:25 UTC** — Vault: phase ledger updated, this session note
   written, memory checkpoint updated.

## Key findings to remember

- **Both adapters agree MIXED is the only profitable label.** Cross-validation
  on n=756. The actionable strategy is the same regardless of adapter:
  abstain on non-MIXED labels.
- **Adapter A (bukosabino/ta)** misses 10pp WR-gate at 9.2pp but the
  miss is within ±10.7pp 95% CI on this sample — not statistically
  load-bearing. Higher actionable PnL counterfactual (+$1,018) than B
  (+$933).
- **Adapter B (hmmlearn)** passes the 10pp gate at 10.8pp and gives
  native posterior probabilities ∈ [0, 1] as confidence. In-sample fit
  on full 5-day series — production needs rolling retrain (parked).
- **Counterfactual is in-sample**; live re-soak will show lower deltas.
- **Phase N file format**: `kind ∈ {fired, settled, settled_correction}`;
  Phase N loader joins by `decision_id` and prefers correction over
  initial settle (this captures the post-hoc gamma truth).

## Files written this session

- `scripts/research/phase_p_mmd_backtest.py` (the backtest pipeline)
- `runbooks/research/phase-P-mmd-backtest-2026-05-18.md` (full results)
- `state/research/phase-P-mmd-charts/01_per_label_wr.png`
- `state/research/phase-P-mmd-charts/02_per_label_per_trade.png`
- `state/research/phase-P-mmd-charts/03_label_distribution.png`
- `state/research/phase-P-mmd-charts/04_cum_pnl_best_vs_worst.png`
- `state/research/binance_historical/btcusdt_1m_2026-05-12_to_2026-05-18.parquet` (kline cache, regenerable)
- `design/P.1-market-mode-detector-integration.md`
- `pdfs/build_phase_p_session2_pdf.py`
- `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf` (11 pp + 4 charts)
- `state/phases/phase-P-hard-reset.md` (Session 2 row added)
- `state/sessions/2026-05-18-phase-P-session-2-mmd-research.md` (this file)

## What did NOT happen this session (intentional)

- No code in `src/` (research only).
- No tests (no src/ changes).
- No bot restart on VPS (J.1.6 still live).
- No `.envrc` change on VPS.
- No PR opened.

## What's next

- **Operator review** of `PHASE_P_SESSION2_MMD_RESEARCH.pdf` +
  `design/P.1-market-mode-detector-integration.md`.
- **Session 3 (T+5-7 days)** — Implement `market_mode_detector.py` per
  the locked design. ≥ 12 new tests + mypy --strict + ruff +
  import-linter all green. VPS deploy with `MMD_ENABLED=true MMD_MODE=shadow`.
  Verify first 3 fires gain `mmd=<label> mmd_conf=<conf>` annotation.
  5-day observation window OPENS.
- **Phase Q decision (Day 5 from Session 3 ship)** — promote / iterate /
  shelve per the decision matrix in design §10.

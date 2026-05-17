# 2026-05-18 — Phase P Session 3 — MMD shadow ship + 5-day observation OPEN

**Bot state at session start:** active on `claude/phase-P-hard-reset@7ec400f`
at MainPID 1019607 (Session 1's process), $790.15 bankroll (post-Session-1
drawdown from $1000). 12 fires today, 0 with MMD annotation.

**Bot state at session close:** active on `claude/phase-P-hard-reset@fd56b61`
at MainPID 1023320 (NEW process, MMD live in SHADOW), $790.15 bankroll
(replay reconstructed). 13 fires today (1 NEW post-restart with the
canonical `mmd=MIXED mmd_conf=0.50` annotation).

Session 3 ran T+0 from Session 2 (operator compressed T+5-7d → T+0).
Acceptable because (a) Sessions 1-2 left the bot LIVE on J.1.6 — Session 3
is a shadow ship that can't break firing (UNKNOWN pass-through), (b) test
budget was met before deploy (29 new tests + full suite), (c) pre-deploy
gates green.

## Session 3 sequence (chronological, VPS UTC)

1. **22:20–22:25** — Inspected `spot_aware_v2_1.py::_maybe_fire` + `run_paper.py`
   `_build_strategy` + `main()` wiring patterns. Confirmed the M.5 pattern
   (optional getter + post-construct rebind) is the precedent for MMD wiring.
2. **22:25–22:35** — Wrote `src/polymarket_bot/strategies/market_mode_detector.py`
   per design/P.1. Followed all design §6 failure-mode contracts (UNKNOWN
   on lib-missing, under-30 bars, indicator exception, getter raise).
3. **22:35–22:38** — Plumbed `mmd_getter`/`mmd_mode`/`mmd_labels_to_abstain`
   into `SpotAwareStrategyV2_1.__init__` + `_maybe_fire` (annotation +
   optional abstain, UNKNOWN-always-pass-through invariant).
4. **22:38** — Plumbed env reads in `_build_strategy` + poller task creation
   in `main()`. mmd_task added to shutdown gather.
5. **22:38–22:39** — Wrote `tests/strategies/test_market_mode_detector.py`
   with 29 tests covering all design §8 budget items. Fixed off-by-one in
   poller test (poll_interval validation was too strict; relaxed to > 0).
   All 29 MMD tests green.
6. **22:39** — Added `ta>=0.11.0` to `pyproject.toml` runtime deps; ran
   `uv lock` → Added ta v0.11.0. Pre-deploy gates ALL GREEN (pytest 667,
   mypy --strict 84 src files, ruff, import-linter).
7. **22:39** — Committed `fd56b61` and pushed to origin. Pre-commit hooks
   auto-formatted 3 files (ruff-format); re-committed cleanly.
8. **22:41:05** — SSH'd to VPS: `git pull --ff-only` to fd56b61, backed
   up `.envrc` to `.envrc.bak.phase-P-session-3-pre-mmd`, appended
   `MMD_ENABLED=true MMD_MODE=shadow` to `.envrc`.
9. **22:41:25** — `sudo systemctl restart bot-staging.service`. The
   systemd unit's `uv run` rebuilt the bot package + installed ta==0.11.0
   automatically. MainPID=1023320 active+running.
10. **22:41:26–27** — Startup log canonical signatures present:
    - `spot_aware_v2_1: ... mmd_mode=shadow mmd_labels_to_abstain=() overrides={}`
    - `MMD ENABLED: lookback_min=60 poll_interval_s=30.0 adx_strong=25.0 adx_weak=20.0 bb_compressed_bps=30.0 momentum_bps=10.0`
    - `bankroll_getter wired (start=$1000.00, replay=True, cap=1)`
    - `bankroll replay: starting=$1000.00 current=$790.15`
    - First Binance kline poll succeeded: `GET .../api/v3/klines 200 OK`.
11. **22:45:00** — First post-restart fire on window 1779057900:
    `bankroll=790.15 fire_n=1/1 mmd=MIXED mmd_conf=0.50`. **Wire confirmed
    end-to-end live.**
12. **22:45–22:50** — Built `pdfs/build_phase_p_session3_pdf.py` +
    rendered `pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf` (9 pp, 18.3 KB).

## Decisions this session

1. **Plumbing pattern**: optional `mmd_getter` callback in strategy
   constructor + `set_mmd_getter` post-construct rebind (mirrors M.5
   pattern). One-way dependency: strategy duck-types the reading rather
   than importing `MmdReading` (keeps the type direction clean).
2. **Failure mode for getter exceptions**: caught at fire-time, treated as
   UNKNOWN, fire proceeds (matches design §6 spec; covered by a test).
3. **`ta` as runtime dep**: added to `pyproject.toml` rather than keeping
   research-only, because Session 3 is a live ship. But MMD still falls
   back to no-op stub on import failure (defense in depth).
4. **Poll interval validation**: relaxed from `>= 1.0` to `> 0` so tests
   can use sub-second intervals; production default stays at 30.0 s.

## Files written this session

- `src/polymarket_bot/strategies/market_mode_detector.py` (NEW)
- `src/polymarket_bot/strategies/spot_aware_v2_1.py` (modified)
- `scripts/run_paper.py` (modified)
- `tests/strategies/test_market_mode_detector.py` (NEW)
- `pyproject.toml` + `uv.lock` (added `ta>=0.11.0`)
- `pdfs/build_phase_p_session3_pdf.py` (NEW)
- `pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf` (NEW; 9 pp)
- `state/phases/phase-P-hard-reset.md` (Session 3 row added)
- `state/sessions/2026-05-18-phase-P-session-3-mmd-ship.md` (this file)

## VPS-side artifacts

- `.envrc` appended with `MMD_ENABLED=true` + `MMD_MODE=shadow`
- `.envrc.bak.phase-P-session-3-pre-mmd` backup
- `state/decisions/2026-05-17.jsonl` now contains 13 fires (12 pre-restart
  + 1 post-restart with mmd annotation)
- `state/decisions/2026-05-18.jsonl` still empty (UTC date hasn't rolled)

## What did NOT happen this session (intentional)

- No bankroll change (still $1k decision-#10 target, $790.15 current per replay).
- No env change beyond MMD enable (all other knobs at J.1.6 baseline).
- No PR opened — branch is the deliverable until 5-day re-soak closes.
- No Phase Q work (gate decision waits for Day-5 audit).

## What's next

- **Day-1 audit** (2026-05-18 22:41 UTC, ~24h): quick check that mmd=
  annotations are present on every post-restart fire + UNKNOWN-rate is low.
- **Day-5 audit** (2026-05-22 22:41 UTC): extend
  `scripts/research/phase_p_mmd_backtest.py` to load the new live JSONL
  fires; compute per-label WR/$tr on live data; compare to Session-2
  backtest numbers; emit `runbooks/research/phase-P-day-5-mmd-audit.md`.
- **Phase Q decision** opens immediately after Day-5 audit per
  `design/P.1` §10 matrix.
- **Phase P CLOSE**: after Phase Q decision lands.

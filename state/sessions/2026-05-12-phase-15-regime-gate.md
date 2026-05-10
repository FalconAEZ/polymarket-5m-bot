# Phase 15 — regime gate audit + design (in progress)

**Session start:** 2026-05-12 UTC at HEAD `f7b5dec` (worktree `claude/thirsty-poincare-2046a0`)
**Bot state at start:** active on bot-staging since 2026-05-10 16:31:15 UTC, VPS HEAD `c66fc07` (Phase 14 not yet deployed), STRATEGY=ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire. Dashboard track still uncommitted (Phase 15 deploy blocker confirmed).
**Phase 14 verdict carried over:** infra-only ship; blocklist empty; deploy deferred to bundle with dashboard track.

## Item 1 — Audit (DONE, awaiting operator sign-off)

Per master plan §4 → Phase 15: re-confirm the regime-classifier hypothesis on bot-staging's ACTUAL fire distribution (2026-05-08 .. 2026-05-10, n=477 fires / 412 settled), using the live `RegimeDetector` class against binance 1-min klines as the spot-tick proxy (raw VPS ticks aren't retained per `runbooks/scripts/regime_classifier_validation.py` note).

Audit script: `scripts/audit_regime_wr.py` (NEW). Mirrors `scripts/audit_per_tier_wr.py` operator-facing format; uses `RegimeDetector(min_samples=3)` so the 1-min kline cadence doesn't false-cold-start the classifier (5/10 closes in the 5m/10m windows respectively).

### Aggregate (3 days, n=477)

| regime    | n_fired | n_settled | n_won |   WR   | 95% CI (Wilson)  | PnL ($)  | avg/trade | gate-criterion                     |
|-----------|--------:|----------:|------:|-------:|:----------------:|---------:|----------:|:-----------------------------------|
| trending  |      33 |        27 |    16 |  59.3% | [40.7, 75.5]     |  +329.41 |  $+12.201 |                                    |
| mixed     |     154 |       136 |    69 |  50.7% | [42.4, 59.0]     |  +450.35 |   $+3.311 |                                    |
| chop      |     290 |       249 |   128 |  51.4% | [45.2, 57.5]     | +1725.12 |   $+6.928 | **MARGINAL** (consider trending-only) |
| unknown   |       0 |         0 |     0 |    n/a |    n/a           |    +0.00 |       n/a |                                    |

### Per-day

| day        | trending (n / WR / PnL)         | mixed (n / WR / PnL)            | chop (n / WR / PnL)              | chop flag                       |
|------------|:--------------------------------|:--------------------------------|:---------------------------------|:--------------------------------|
| 2026-05-08 | n=1 / 100.0% / +$4.26           | n=10 / 30.0% / -$23.24          | n=18 / 50.0% / +$28.45           | n<30 (insufficient)             |
| 2026-05-09 | n=17 / 58.8% / +$10.21          | n=89 / 47.2% / -$24.24          | n=156 / 53.8% / +$40.09          | MARGINAL                        |
| 2026-05-10 | n=9 / 55.6% / +$314.94          | n=37 / 64.9% / +$497.83         | n=75 / 46.7% / +$1656.58         | STRONG SUPPORT (WR<50% n≥30) but PnL DOMINANT |

### Counterfactuals

**Abstain on {chop}:**
- current  n_settled=412, WR=51.7%, total=+$2504.89, avg=+$6.08
- kept     n_settled=163, WR=52.1%, total=+$779.77, avg=+$4.78
- delta    WR **+0.45pp**, total **-$1725.12**, avg **-$1.30**, dropped 249 fires (60%)

**Abstain on {chop, mixed} (trending-only gate):**
- kept     n_settled=27, WR=59.3%, total=+$329.41, avg=+$12.20
- delta    WR +7.56pp, total **-$2175.48**, avg +$6.12, dropped 385 fires (93%)

## Honest pushback — same PnL paradox as Phase 14

The 3-day raw verdict — chop WR=51.41% in [50, 55) — reads as the master plan's option (b) MARGINAL. Per the prompt, that should trigger "trending-only gate" consideration. BUT the empirical PnL picture explicitly contradicts that recommendation:

1. **Chop generates 69% of total bot PnL** (+$1725 of +$2504). Blocking it loses real money to chase a 0.45pp cosmetic WR lift.
2. **Trending-only gate drops 93% of fires** to keep a 27-trade sample with a Wilson 95% CI of [40.7, 75.5] — wide enough that the "trending" bucket could equally plausibly be 41% WR (loss) or 75% WR (great). Sample is far too small to act on.
3. **2026-05-10 is the dominant data day**: 176/477 = 37% of fires, but +$2469/+$2504 = 99% of total PnL. The 2026-05-09 picture (small ±$40 PnL across all buckets) doesn't separate buckets at all. This is single-day-dominated and shouldn't drive a permanent gate.

**This is the Phase 14 pattern exactly:** the gate criterion triggers on WR alone, but PnL says the "losing" bucket is actually the highest dollar contributor. Auto-populating ABSTAIN_REGIMES would lose ~$575/day in real PnL for a 0.45pp WR cosmetic.

## Recommendation (for operator sign-off)

**Ship the REGIME_GATE infrastructure dark, blocklist empty** — same pattern as Phase 14:

- `REGIME_GATE_ENABLED` defaults `false`
- `REGIME_GATE_ABSTAIN_REGIMES` defaults `""` (empty CSV) — so even if `ENABLED=true`, no behavior change until operator populates the set
- Wire the regime check into `EnsembleWrapper` as a pre-LLM filter (same slot as Phase 14 tier gate, applied AFTER tier gate so the cheaper structural-prior filter runs first)
- Emit `kind="regime_abstained"` JSONL records when the gate fires (so operator can observe what WOULD have been blocked without enforcing)
- Add 5 tests mirroring Phase 14's set + queue-doesn't-overflow guard

**Do NOT auto-set** `REGIME_GATE_ABSTAIN_REGIMES=chop` per the master plan's deploy default. The empirical evidence on the current bot's behavior says that flip costs $575/day with no clear lift.

## Open questions for operator

1. **Sign-off on infra-only ship?** Same as Phase 14: code + tests + design committed; envs default off; deploy deferred to dashboard-track bundling.
2. **Defer ABSTAIN-set decision to a longer sample?** Suggest re-running `scripts/audit_regime_wr.py` after another 7-14 days of fire data; ideally with the 2026-05-10 outlier diluted by more days.
3. **Trending-only gate as a separate experiment?** That gate is conceptually different — not "block losing regime" but "fire only on best regime". Sample too small to recommend today; flag for post-Phase 16 if operator wants to explore.

## What's still to do this session (pending sign-off)

- Item 2: implement `REGIME_GATE_ENABLED` + `REGIME_GATE_ABSTAIN_REGIMES` envs, `EnsembleWrapper` pre-fire branch, 5 tests, `design/phase-15-regime-gate.md`
- Item 3: deploy DEFERRED — dashboard track still uncommitted on VPS (per operator-housekeeping item 1 in the prompt)
- Commit + push to `claude/thirsty-poincare-2046a0`

## Item 2 — Implementation landed (operator approved 2026-05-12)

Operator confirmed: "do what is recommended" → infra-only ship, abstain set empty (option 1).

### Files touched

- `src/polymarket_bot/strategies/ensemble_wrapper.py` — new `regime_detector: RegimeDetector | None` + `abstain_regimes: Iterable[str]` constructor args (both default empty/None). New `REGIME_GATE_LABELS` constant (`{trending, chop, mixed}` — `unknown` excluded to prevent cold-start blackout). Spot-tick observation added inside `_update_context()` when detector is supplied. Refusal branch in `on_event()` slotted AFTER the Phase 14 tier-gate and BEFORE the off/shadow/gate mode dispatch (mirrors tier-gate ordering exactly). Emits `kind="regime_abstained"` JSONL records with `regime`, `abstain_regimes`, `window_ts`, `base_rationale`, `decision_id_hint`.
- `scripts/run_paper.py` — `REGIME_GATE_ENABLED` (bool, default false) + `REGIME_GATE_ABSTAIN_REGIMES` (CSV, default empty). When enabled, instantiates `RegimeDetector()` with module defaults (5m/10m windows, trending>1.20 / chop<0.80). Validation against canonical labels happens inside `EnsembleWrapper` (unknown labels → `ValueError` at boot). Same `ENSEMBLE_MODE=off` ignored warning as tier-gate.
- `tests/strategies/test_ensemble_wrapper.py` — 5 new tests:
  - `test_regime_gate_empty_abstain_set_is_regression_safe` — empty set = no-op even with detector wired in
  - `test_regime_gate_blocks_chop_regime_in_gate_mode` — chop classifier → refusal + no LLM call (specialist + meta `call_count == 0`)
  - `test_regime_gate_passes_trending_regime` — trending classifier → normal LLM flow
  - `test_regime_gate_logs_record_on_refusal` — exactly one `kind=regime_abstained` JSONL line with all expected fields
  - `test_regime_gate_constructor_rejects_unknown_label` — both "not-a-regime" and "unknown" raise `ValueError`
  - `test_regime_gate_under_load_no_overhead` — 100 evals < 500ms (queue-overflow guard)
- `design/phase-15-regime-gate.md` (NEW) — locked design per anti-vibe rule #1.
- `scripts/audit_regime_wr.py` (NEW) — re-runnable per-regime WR audit (already landed in Item 1).

### Gates (all green at commit time)

- `ruff check src/ tests/ scripts/` — All checks passed!
- `mypy --strict src/` — 64 source files, no issues
- `pytest -q` — **487 passed** (was 481 at session start → +6 = 5 new Phase 15 tests + 1 elsewhere)
- `lint-imports` — 3/3 contracts kept

### Item 3 — Deploy SHIPPED 2026-05-10 21:58:44 UTC

Operator authorized bundled deploy ("execute all yourself"). Full sequence:

1. **Local FF push:** `git push origin claude/thirsty-poincare-2046a0:claude/jovial-hermann-7e103f` — Phase 15 commit `fbcd38a` advances `claude/jovial-hermann-7e103f` over the Phase 14 tip (was at `f7b5dec`). Fast-forward; no merge commit.
2. **VPS dashboard track preserved (NOT discarded):**
   - Tarball backup: `/home/ops/dashboard-track-backup-2026-05-12/dashboard-track-20260510T215745Z.tar.gz` (27 files — `dashboard/{loaders,theme,bankroll,components,gamma_resolver,markets,pipeline_latency,polymarket_orderbook,profit_pace,provider_rtt,rtt_collector,rtt_loader,streaks}.py` + `dashboard_server/` package).
   - `git stash@{0}: phase-15-deploy-2026-05-12: WIP dashboard track preserved; tarball at /home/ops/dashboard-track-backup-2026-05-12/` — holds the 3 tracked mods (`dashboard/loaders.py`, `dashboard/theme.py`, `state/token_side_index.json`).
   - Pre-deploy `git status` snapshot saved to `/home/ops/dashboard-track-backup-2026-05-12/git-status-before-stash.txt`.
3. **VPS pull:** `git pull --ff-only origin claude/jovial-hermann-7e103f` advanced HEAD `c66fc07` → `fbcd38a`. Fast-forward only.
4. **`.envrc` appended** (with `.envrc.bak.phase-15-deploy-*` snapshot first):
   ```bash
   export TIER_GATE_ENABLED=false
   export TIER_GATE_BLOCKLIST=
   export REGIME_GATE_ENABLED=false
   export REGIME_GATE_ABSTAIN_REGIMES=
   ```
5. **`sudo systemctl restart bot-staging.service`** — service `active` since `2026-05-10 21:58:44 UTC`. Clean boot journal:
   - "ensemble ENABLED mode=gate daily_budget=$10.00 log_root=state/ensemble"
   - "ensemble base=wide_fire — NO tier/priors/EV gates; LLM is the only filter"
   - "active window 1778450100 already has unsettled fire 9d8024a9 — priming _state to block double-fire" (orphan-recovery worked across restart)
   - No `TIER_GATE_ENABLED=true` warning (gate dark — as intended)
   - No `REGIME_GATE_ENABLED=true` warning (gate dark — as intended)
6. **Prior-run shutdown counted dropped_records=119722** over ~5.5h gate-mode — consistent with 12s LLM blocking envelope; no regression class.

### Dashboard-track restoration (operator's task post-deploy)

The dashboard track is preserved but NOT restored — `loaders.py` modifications (systemd MainPID integration) likely conflict with Phase 14's `loaders.py` refactor (tier-constants re-export). When operator is ready:

```bash
# On VPS:
cd /home/ops/polymarket-5m-bot
# Option A — git stash pop (may conflict on loaders.py):
git stash pop  # then resolve conflicts in loaders.py
# Option B — restore from tarball + manually merge:
tar xzf /home/ops/dashboard-track-backup-2026-05-12/dashboard-track-20260510T215745Z.tar.gz
```

### +5min / +30min re-verify (feedback_vps_deploy_verify_late)

**+5min verify @ 2026-05-10 22:03 UTC — CLEAN:**
- (a) service `active`, ActiveEnterTimestamp = `Sun 2026-05-10 21:58:44 UTC` — unchanged (no parallel-SSH reset)
- (b) HEAD = `fbcd38a`
- (c) Only WARN since restart = the expected `wide_fire — NO tier/priors/EV gates` notice. No ERROR / Traceback / CRITICAL. Periodic orphan-recovery firing normally (last: 22:03:46 "0 orphans found")
- (d) Firing healthy — 3 recent windows fired (1778449500/1778450100/1778450400), 2/3 filled (3rd had ask=0.01 phantom-fill class → expected no-fill). 179 settled today.

**+30min verify** scheduled (~22:28 UTC).

## Honest pushback recorded (for the vault)

1. **Audit verdict** = MARGINAL per the prompt's reading, but PnL data explicitly contradicts the master plan's "ABSTAIN if chop" recommendation. Same pattern as Phase 14's 30-50% tier.
2. **Master plan deploy default** `REGIME_GATE_ABSTAIN_REGIMES=chop` rejected in favor of empty default — would lose ~$575/day on current bot distribution.
3. **Trending-only gate** considered + rejected (n=27, Wilson CI 41-76% — too wide to act on; same conceptual class as Phase 14's "block losing tier" but inverted).

All three judgments aligned with operator preferences (`feedback_no_vibe_coding`, `feedback_honest_pushback`, `feedback_defer_deploys_to_natural_restart`).

## Audit artifacts

- `scripts/audit_regime_wr.py` — re-runnable audit (CLI mirrors `audit_per_tier_wr.py`)
- `state/research/binance_historical/btcusdt_1m_2026-05-{08,09,10}.parquet` — kline cache
- `/tmp/regime_audit.out` — full audit stdout (transient; not committed)

## Anti-vibe rules applied so far

- Design doc before code: deferred to post-sign-off, since the design hinges on whether to default ABSTAIN_REGIMES to `chop` (master plan) or `""` (audit-recommended).
- Honest pushback: data presented + recommendation against the master plan's deploy default, with explicit reasoning.

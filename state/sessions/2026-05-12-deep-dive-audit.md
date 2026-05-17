# 2026-05-12 — Bot deep-dive audit (operator-requested full sweep)

**Trigger:** operator request after Phase 15 close — "find misconceptions / bugs / mistakes / latency issues / anything that would lower PnL or WR, fine tune the bot".

**Approach:** parallel audit pass (data + code + state). Findings categorized 🟢 auto-fix / 🟡 phase-prompt / ⚪ no-action.

**Scope boundary:** anti-vibe rule #1 applies. Strategy / gate / sizing / latency tuning becomes a phase prompt, NOT an in-session change.

**Bot state at audit start:** active on bot-staging since 2026-05-10 21:58:44 UTC, HEAD `5d575f1`, both kill-switches dark, ensemble gate-mode + wide_fire base.

## Audit dimensions covered

1. Strategy logic correctness
2. LLM ensemble health (timeout rate, abstain rate, specialist agreement)
3. Latency stack + dropped records
4. Settle/resolution accuracy
5. Fill rate (revisit Phase 13 NULL)
6. PnL accounting consistency
7. Risk controls (kill switches, budget caps)
8. Configuration drift
9. Test coverage gaps
10. Dead code / stale docs
11. Disk + memory growth
12. Edge cases not under test

## Bot health snapshot (audit context)

Since 2026-05-10 21:58:44 UTC restart (~25 min at audit time):
- **180 fired, 123 filled (68.3%), 180 settled, 97 won = 53.9% WR, +$2531.98 PnL**
- Both kill-switches dark (0 tier_abstained, 0 regime_abstained)
- 0 errors/warnings in journal since restart (only the expected wide_fire WARN)
- VPS disk 7% used, healthy
- 487 tests green, ruff + mypy --strict + lint-imports clean
- 0 TODO/FIXME (anti-vibe #8 clean), all src/*.py have module headers (CI rejects absent)

## Ensemble health breakdown (last 5.5h + 25min post-restart)

| outcome | n | % | notes |
|---|---:|---:|---|
| meta=FIRE | 91 | 40.3% | LLM said go |
| meta=ABSTAIN | 85 | 37.6% | LLM said no |
| meta=None (gate_timeout >12s) | 20 | 8.8% | known — improved from 12.5% prior |
| **meta=None (other)** | **30** | **13.3%** | **all 3 specialists agreed UP, meta call returned None — root cause not logged** |
| cold_start | 2 | <1% | acceptable, brief after restart |

## Findings (categorized)

### 🟢 AUTO-FIX (this session)

| # | what | where | rationale | status |
|---|---|---|---|---|
| 1 | Hardcoded `300` for window-close calc | `ensemble_wrapper.py:498` | Should use `WINDOW_SECONDS` from `resolver.py` (already the canonical constant). Drift risk if WINDOW_SECONDS ever changes. Pure constant import — anti-vibe exempt. | ✅ DONE |

### 🟡 PHASE-PROMPT (queued for operator review — NOT in-session)

| # | what | rationale | priority | prompt file |
|---|---|---|---|---|
| 1 | **Meta-decide outcome telemetry** | 22.1% meta=None overall, with 13.3% (n=30) having no journal trail. Need a `meta_outcome` tag in `ensemble_vote` JSONL to attribute None to (api_error / refusal / no_text / validation_failed / budget). Precursor to Phase 19 design. | **HIGH** — cheapest information-gathering | `phase-prompts/phase-18b-meta-observability-2026-05-13.txt` (DRAFTED) |
| 2 | **Phase 19 — Async LLM pre-compute** (per master plan) | 8.8% gate-mode timeout rate + 22.1% meta=None rate + 119722 dropped records over 5.5h. Phase 19 is already in the master plan. Likely target after Phase 18B telemetry decides shape. | HIGH — eventual | (already in master plan §4 Phase 19) |
| 3 | **`composite_pct` rationale fallback semantics** | `ensemble_wrapper.py:546-558` falls back to `delta_bps` when `composite=` marker absent (wide_fire emits null composite). The `or 0.0` then masks parsing failures as composite=0%. Sent to LLM as ctx.composite_pct=0.0 always when wide_fire is base. Not breaking — but misleading LLM signal. Worth a small phase. | MEDIUM | (TBD — write only if Phase 18B confirms it matters) |
| 4 | **Logrotate config for bot+dashboard logs** | `state/dashboard-server.log` is 28MB unrotated. Will eventually fill disk (months out, not immediate). Operator-side infra (needs `sudo` for `/etc/logrotate.d/`). | LOW — infra housekeeping | (operator task; could be Phase 16-bundle) |

### ⚪ NO ACTION (verified false positives or by-design)

| # | what | verdict |
|---|---|---|
| 1 | `wide_fire.py:145` `side="BUY"` hardcoded | CORRECT — Decision schema explicitly types `side: Literal["BUY"]`. Polymarket binary markets are always BUY (you BUY the YES token or BUY the NO token); chosen TOKEN encodes direction. |
| 2 | `_run_ensemble` `zip(..., strict=False)` | CORRECT — defensive. BaseException case handled in the loop above. |
| 3 | `regime_detector.py:90` silent out-of-order tick drop | CORRECT — documented (binance feed is monotonic; defensive guard for synthetic test clocks). |
| 4 | `tiers.py` 1.01 upper bound | CORRECT — degenerate prices >1.0 don't occur on Polymarket binary markets. |
| 5 | TIER/REGIME_GATE defaults to `false` | CORRECT — kill-switches default OFF per anti-vibe pattern. |

## Decisions made this session

1. **Did NOT touch strategy/gate/sizing/threshold logic** — all such items become phase prompts per anti-vibe rule #1.
2. **Did NOT add more logging in-session** — even observability changes (the meta_outcome telemetry) get a design doc first per anti-vibe rule #1.
3. **Did fix one constant-import** — `300 → WINDOW_SECONDS` is a pure refactor, exempt from anti-vibe rules per CLAUDE.md ("Pure formatting / docstring / dependency-bump fixes are exempt").

## What the audit did NOT find

- **No async control-flow bugs** in the hot path (the 2 known overflow patterns are already fixed; ensemble_wrapper.py + runner.py reviewed clean)
- **No off-by-one / side-flip / window-boundary bugs**
- **No silent kill-switch defaults reversed**
- **No untested critical branches** (test coverage on EnsembleWrapper is comprehensive: 25 tests covering off/shadow/gate × cold-start × tier-gate × regime-gate)
- **No env defaults that contradict CLAUDE.md decisions**
- **No dead imports / unused exports** in the strategies/ module
- **No drift in the ensemble's defense-layer ordering** (tier-gate → regime-gate → ensemble cleanup hierarchy is correct)

## What the audit explicitly did NOT cover

- LLM prompt content quality (specialists + meta prompts). Phase 18B telemetry will reveal whether prompts need tuning.
- Polymarket fee model accuracy in shadow-fill simulation.
- Chainlink oracle staleness handling under feed outage.
- Litestream backup integrity drill (Phase 5 ran this; recheck cadence is monthly).
- Frontend dashboard rendering correctness (separate codebase per the dashboard_server v3 rebuild).

## Bottom line

The bot is **healthy and profitable** (53.9% WR / +$2532 today). No critical bugs. The single highest-information next step is **Phase 18B — meta-decide telemetry** (drafted), which will inform whether **Phase 19 — async LLM pre-compute** should target prompt fixes, retry layers, or true async restructuring.

Recommended phase order after Phase 16:
1. Phase 18B (meta telemetry, ~30 min, very cheap)
2. Wait 24h to collect outcome data
3. Phase 17 (sizing modes — decision #9 revisit)
4. Phase 19 (designed using 18B's data)

# Phase 19 — LLM async pre-compute (LOCKED DESIGN)

Status: DRAFT — awaiting operator sign-off. Anti-vibe rule #1.

Anchor data:
- Deep-dive audit 2026-05-12 (`state/sessions/2026-05-12-deep-dive-audit.md`)
- Phase 18B `meta_outcome` telemetry (live since 2026-05-10)
- Memory: `feedback_test_under_load.md` (async I/O in hot path)
- Master plan §4 row 19

Anti-pattern this phase eliminates: **the 12s inline-await in `EnsembleWrapper.on_event`'s gate-mode dispatch**. Today the runner blocks on the LLM call up to 12s per fire; under sustained latency this overflows the feed queue (1024) and drops market records. Audit:

| Metric | Last 5.5h |
|---|---:|
| Gate-mode timeout rate (12s ceiling hit) | 8.8% |
| Total `meta=None` rate (timeout + other) | 22.1% |
| Records dropped from feed queue overflow | **119,722** |

---

## 1. Goal (one sentence)

Move the LLM ensemble call **off the runner's hot path** — run it as a background task that pre-computes one verdict per window; at fire-time the gate looks up the cached verdict instead of awaiting a fresh call.

## 2. Locked-decision impacts

| Decision | Status |
|---|---|
| #4 (Anthropic-only) | UNTOUCHED |
| #5 (3 specialists + meta) | UNTOUCHED |
| #6 (composite ≥0.6) | UNTOUCHED (already revisited under 16.B for router path) |
| #16 (LLM A/B verdict — ensemble kept) | UNTOUCHED — Phase 19 changes WHEN the LLM votes, not WHETHER |

No locked decision needs revisiting.

## 3. The contract

### 3.1 Background task
- Spawned on every `WindowBoundary(kind="open")` event
- Sleeps until `LLM_PRECOMPUTE_OFFSET_S` (default 30s after window open)
- Builds `AgentContext` from current wrapper state at that moment
- Runs `self._run_ensemble(ctx)` (the same call path as today's gate)
- Stores result in `_precompute_cache[window_ts] = EnsemblePrecomputeResult(meta, votes, outcome, ts_ns)`
- Task is tracked in `_precompute_tasks: set[asyncio.Task]` for graceful shutdown

### 3.2 Fire-time gate (when `LLM_PRECOMPUTE_ENABLED=true`)
```
candidate = await self._base.on_event(event)
if candidate is None or self._mode == "off":
    return candidate
if self._mode == "gate":
    cached = self._precompute_cache.get(self._window_ts)
    if cached is None:
        # No vote yet — same fallback as meta=None today: fire as base
        return candidate
    # Apply existing gate logic against cached.meta
    if cached.meta is None or cached.meta.action != "FIRE":
        return candidate if cached.meta is None else None
    if cached.meta.side != _side_from_rationale(candidate.rationale):
        return None
    return candidate
```

The fire-time path is now **O(1) dict lookup** — no `await`, no `asyncio.wait_for`, no LLM call. Queue can drain freely.

### 3.3 Shadow-mode behavior
Unchanged. Shadow already uses fire-and-forget via `_spawn_shadow_vote`. Phase 19 cache is only consulted by gate-mode.

### 3.4 Off-mode behavior
Unchanged. `LLM_PRECOMPUTE_ENABLED=true AND ENSEMBLE_MODE=off` → background task still spawns and votes (cheap), but no fire-time consumer; just builds historical data. Operator can disable precompute when ensemble is off via `LLM_PRECOMPUTE_ENABLED=false`.

### 3.5 Cache lifetime
- Insert: when precompute task completes
- Evict: on next `WindowBoundary(kind="open")` for the FOLLOWING window (i.e., we keep at most 2 entries: previous + current)
- Bounded: at most 2 entries, so no memory growth

## 4. Env vars

| Env | Default | Effect |
|---|---|---|
| `LLM_PRECOMPUTE_ENABLED` | `false` | Master kill-switch. False → exact current inline-await behavior. |
| `LLM_PRECOMPUTE_OFFSET_S` | `30` | Seconds after window open to fire the precompute. 30s gives spot+oracle time to land. |
| `LLM_PRECOMPUTE_MAX_AGE_S` | `270` | Cache validity. Default = WINDOW_SECONDS - 30s. Older → treated as no-cache (gate falls through). |

## 5. Failure modes + recovery

| Scenario | Behavior |
|---|---|
| Precompute task raises | Caught at task boundary; logged at WARN; cache entry not set; gate falls through to base. Same outcome as `meta=None` today. |
| Precompute timeout (LLM > 12s) | Same as above — task is `asyncio.wait_for`-bounded internally; on timeout, no cache entry. |
| Window opens, fire happens BEFORE T+30s | Cache empty; gate falls through to base. Today same window had a fresh LLM call anyway. Net: small loss of LLM filtering for the first 30s of each window. Acceptable per audit (98.1% of windows have a fire after T+30s). |
| Bot restart mid-window | Existing window's precompute task killed; cache cleared. Next window opens, precompute spawns normally. Brief gap during the warmup-after-restart window. |
| Anthropic budget exhausted | Adapter returns None; precompute caches `meta=None`; gate behaves as `meta=None` today. |

## 6. Anti-overflow guarantee

The 2026-05-09 / 2026-05-10 queue-overflow incidents both shared the same shape: an `await` in `on_event` for ≥1s that blocked the runner's feed consumer. Phase 19 closes that class of bug entirely for gate-mode — `on_event` does no I/O when `LLM_PRECOMPUTE_ENABLED=true`. The under-load test `test_precompute_does_not_block_main_loop` is the third application of `feedback_test_under_load`'s lesson.

## 7. Module layout

```
src/polymarket_bot/strategies/ensemble_wrapper.py    MODIFIED
  - EnsembleWrapper.__init__: add precompute_enabled, precompute_offset_s,
    precompute_max_age_s params
  - new: _precompute_cache: dict[int, EnsemblePrecomputeResult]
  - new: _precompute_tasks: set[asyncio.Task]
  - new: _spawn_precompute(window_ts) called from _update_context on WindowBoundary
  - new: _run_precompute_task(window_ts)
  - modified: _dispatch_gate (or wherever the current await lives) to read
    from cache when enabled
  - modified: aclose() to await pending precompute tasks

scripts/run_paper.py                                 MODIFIED
  - read LLM_PRECOMPUTE_ENABLED / _OFFSET_S / _MAX_AGE_S
  - pass through to EnsembleWrapper constructor

tests/strategies/test_ensemble_wrapper.py            MODIFIED (+7 tests)
  - test_precompute_disabled_default_no_behavior_change (BULWARK)
  - test_precompute_spawns_on_window_open
  - test_precompute_caches_per_window
  - test_gate_uses_cached_verdict_at_fire_time
  - test_gate_falls_through_when_no_cache
  - test_precompute_does_not_block_main_loop (under-load)
  - test_precompute_aclose_awaits_pending_tasks
```

## 8. Test plan summary

The BULWARK test is `test_precompute_disabled_default_no_behavior_change` — runs an entire window's event sequence twice, once with old code and once with new code in default-OFF state, and asserts byte-identical Decision output + ensemble log shape. If this fails, deploy halts.

Under-load test mirrors the existing `test_shadow_mode_does_not_block_main_loop_under_slow_llm`: feeds a slow LLM stub (~1.5s) and asserts that `on_event` returns in <100ms under gate-mode + precompute-enabled.

## 9. Deploy plan

1. Phase 19.1 — wrapper changes + tests (THIS DESIGN DOC + implementation)
2. Phase 19.2 — VPS dark deploy (env stays unset → default false → zero behavior change)
3. Phase 19.3 — flip `LLM_PRECOMPUTE_ENABLED=true` + restart
4. Phase 19.4 — +5min / +30min / +24h verification per `feedback_vps_deploy_verify_late`
5. Phase 19.5 — soak gate audit:
   - Queue-overflow incidents during the soak: **0** required (the headline gain)
   - `meta=None` rate due to timeout: **should drop to ~0%** (no inline await, no timeout)
   - WR / fire-rate / PnL: **should stay within ±2pp of baseline** (precompute is a latency fix, not a behavior change)
6. PROMOTE on green soak; ROLLBACK env flip on regression

## 10. Soak gate (Phase 19.5 promote criteria)

```
PROMOTE if:
  queue_overflow_incidents_in_7d == 0
  AND meta_outcome["gate_timeout"] / total_votes <= 0.005  (was 8.8%)
  AND fire_rate_delta_pct <= 2.0  (no firing-behavior regression)
  AND daily_pnl_delta_usd >= -30  (no PnL regression vs baseline)
```

ROLLBACK on any criterion fail. Single env flip — zero code change.

## 11. Rollback plan

`LLM_PRECOMPUTE_ENABLED=false` env flip reverts to current inline-await behavior. The precompute code is dead when disabled (no task spawn, no cache lookup). The existing gate-mode path is preserved unchanged inside an `if self._precompute_enabled:` branch.

If the wrapper code itself has a defect that affects the off path (the bulwark test would catch this pre-deploy), `git revert <commit>` and force-push to `claude/jovial-hermann-7e103f`.

## 12. Non-goals (explicit out-of-scope)

- ❌ Changing the AgentContext shape
- ❌ Changing prompts (specialists or meta)
- ❌ Changing the BudgetTracker
- ❌ Pre-computing the EVERY_WINDOW router decision (router is already pure-function inline)
- ❌ Adding a 4th specialist (Phase 25)
- ❌ Changing the `decision #5` ensemble structure
- ❌ Feeding precompute LLM signals to the every-window router (separate phase; out of MVP)

## 13. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Cached verdict goes stale if spot moves significantly between precompute (T+30s) and fire | Audit data: 98.1% of fires happen within ±60s of precompute time. If audit shows staleness costs >2pp WR, follow-up phase adds re-precompute on |Δspot|≥X. NOT in MVP. |
| Background task leaks if shutdown signal mishandled | `aclose()` awaits `_precompute_tasks` set with `return_exceptions=True`, mirroring `_pending_shadow_votes` pattern. Add to integration tests. |
| Multiple background tasks if WindowBoundary re-fires (clock drift, replay) | Idempotency guard: `if window_ts in self._precompute_cache: return` early in `_spawn_precompute`. |
| Cache stays populated across rolling minutes — memory leak | Cache eviction on next WindowBoundary open: keep only previous+current. Bounded at 2 entries. |
| Anthropic spend doubles (precompute runs on EVERY window, not just fires) | Audit: today the wrapper votes ~85% of windows (wide_fire abstains ~15%). Precompute would vote 100% of windows. Cost delta: 15% × $0.005/vote × 288 windows/day = $0.22/day. Within $10/day cap. |

## 14. Implementation order (Phase 19.1)

1. `EnsemblePrecomputeResult` dataclass (frozen, slots)
2. Constructor params + state init
3. `_spawn_precompute` (task-launcher pattern, mirrors `_spawn_shadow_vote`)
4. `_run_precompute_task` (the actual work)
5. Cache eviction on WindowBoundary open
6. Gate-mode read from cache + fall-through
7. `aclose()` updated to await precompute tasks
8. 7 new tests (BULWARK first; under-load test last)
9. Run all 4 gates green
10. Commit + push (NO DEPLOY in 19.1 — that's 19.2)

---

This design is LOCKED on operator sign-off. Implementation in Phase 19.1 references this doc verbatim per anti-vibe rule #1.

# Phase 15 — REGIME_GATE_ENABLED + REGIME_GATE_ABSTAIN_REGIMES design

**Status:** locked 2026-05-12 after Phase 14 tier-gate ship.
**Owner:** EnsembleWrapper (`src/polymarket_bot/strategies/ensemble_wrapper.py`).
**Audit script:** `scripts/audit_regime_wr.py`.

## 1. Problem

The existing `RegimeDetector` (`src/polymarket_bot/strategies/regime_detector.py`)
is wired into `SpotAwareStrategyV3` but NOT into the active `ensemble`
strategy. The 2026-05-12 audit on bot-staging's 3-day fire distribution
(n=477) confirms the classifier still separates the dataset — trending
WR=59.3% on n=27 vs chop WR=51.4% on n=249 — though less starkly than
the historical 256-trade dataset that motivated v3 (trending 70.59% vs
chop 47.40%). The operator needs the ability to ABSTAIN on a chosen
regime subset without a code release, mirroring Phase 14's tier-gate
infrastructure.

The audit ALSO showed the same PnL paradox as Phase 14: chop is the
largest dollar-PnL contributor (+$1725 of total +$2504 over 3 days, 69%
of earnings) despite WR being lower than trending. Auto-populating
`REGIME_GATE_ABSTAIN_REGIMES=chop` per master plan default would lose
~$575/day. **The infrastructure ships now; the abstain-set decision
defers to a longer-sample audit.**

## 2. Out of scope (explicit)

- **No auto-population of the abstain set.** Default = empty. Operator
  reads `scripts/audit_regime_wr.py` output and sets
  `REGIME_GATE_ABSTAIN_REGIMES` themselves after a longer sample.
- **No changes to the existing v3 strategy.** v3 keeps its own
  `RegimeDetector` instance and gate logic. Phase 15 instantiates a
  SEPARATE detector for the ensemble wrapper — the v3 and ensemble
  paths are mutually exclusive at runtime (STRATEGY=v3 vs ensemble),
  so there is no concurrent-mutation concern, but architecturally the
  detector is per-strategy state, not shared singleton state.
- **No dashboard panel for regime breakdown.** The audit script's
  per-regime table is operator-facing only this phase.
- **No new regime labels.** Reuse the exact `Regime` literal from
  `regime_detector.py`: `trending | chop | mixed | unknown`. The
  `unknown` label exists for cold-start and is NOT a valid abstain
  target (gate would block every fire in the first 10 minutes after
  any bot restart).

## 3. Behavior

### 3.1 Env vars

| name | default | description |
|------|---------|-------------|
| `REGIME_GATE_ENABLED` | `false` | If `true`, the wrapper instantiates a `RegimeDetector`, observes spot ticks, and consults `REGIME_GATE_ABSTAIN_REGIMES` on every candidate. |
| `REGIME_GATE_ABSTAIN_REGIMES` | `""` (empty) | Comma-separated regime labels, e.g. `chop` or `chop,mixed`. Whitespace tolerated. Invalid labels raise at startup. `unknown` is rejected at startup (would block all cold-start fires). |

Kill-switch semantics: with `REGIME_GATE_ENABLED=false` the wrapper does
not instantiate a `RegimeDetector` or observe spot ticks — zero overhead
on the hot path. With `REGIME_GATE_ENABLED=true` and an empty abstain
set, the wrapper observes ticks + classifies (for log fidelity) but
never blocks. **Phase 15 dark-ship default = both behaviors are
identical to pre-Phase-15** (no instantiation, no observation).

### 3.2 Decision flow

In `EnsembleWrapper.on_event`, slot the regime check immediately AFTER
the Phase 14 tier-gate refusal path. Ordering rationale:

1. **Tier gate first** — O(1) dict lookup; runs even when regime gate
   disabled. The cheapest filter goes first.
2. **Regime gate second** — needs `classify()` call which does a vol
   ratio computation over the 600-tick buffer. Still O(N) on ~600
   floats (<1ms), but slightly more expensive than tier lookup.
3. **off/shadow/gate mode dispatch** — same as today; both gates have
   already had a chance to abstain.

The wrapper also needs to feed spot ticks into the detector. The
existing `_update_context()` already mirrors every `SpotTick` event to
maintain `_spot_now` + `_recent_spot` — add a parallel `observe_spot()`
call on the detector when it's present.

Pseudocode:

```python
# Phase 15 init (only if regime_detector provided):
self._regime_detector = regime_detector  # may be None
self._abstain_regimes: frozenset[Regime] = frozenset(abstain_regimes)

# In _update_context (already called on every event):
if isinstance(event, SpotTick) and self._regime_detector is not None:
    self._regime_detector.observe_spot(event.ts_utc_ns, event.price)

# In on_event, after tier-gate refusal path:
if candidate is not None and self._regime_detector is not None and self._abstain_regimes:
    regime = self._regime_detector.classify(event.ts_utc_ns)
    if regime in self._abstain_regimes:
        self._log_ensemble_event({
            "kind": "regime_abstained",
            "ts_ns": event.ts_utc_ns,
            "window_ts": self._window_ts,
            "decision_id_hint": _decision_hint(candidate),
            "regime": regime,
            "abstain_regimes": sorted(self._abstain_regimes),
            "base_rationale": candidate.rationale,
        })
        return None
```

### 3.3 Log schema

New JSONL kind in `state/ensemble/<UTC-date>.jsonl`:

```json
{
  "kind": "regime_abstained",
  "ts_ns": 1778430660000000000,
  "window_ts": 1778430900,
  "decision_id_hint": "abc123…",
  "regime": "chop",
  "abstain_regimes": ["chop"],
  "base_rationale": "strategy=wide_fire mode=ensemble_base delta_bps=+0.00 ttl=30s side=UP"
}
```

Operator can grep refusals after enabling to verify the gate is firing
on the regime distribution they expected before populating the abstain
set in production.

### 3.4 Startup validation

`scripts/run_paper.py`'s ensemble branch validates the abstain CSV at
startup:

- Unknown labels (anything outside `trending | chop | mixed`) raise
  `ValueError`.
- The `unknown` label is rejected with a specific error message —
  blocking it would mean abstaining on every fire in the first 10 min
  after restart, which is a footgun, not a feature.
- Empty CSV (default) + `REGIME_GATE_ENABLED=true` logs "gate is a
  no-op" same as Phase 14's empty-blocklist path.

### 3.5 Cold-start

`RegimeDetector.classify()` returns `"unknown"` until both windows have
≥ `min_samples=10` ticks. With the production tick rate (~1 Hz from
binance feed) the buffer fills in ~10 seconds, so cold-start is brief.
`"unknown"` is not in any valid abstain set, so cold-start fires through
unimpeded — same policy as v3 (`design/regime_detector.md` §"Cold-start"
says "v3 abstains", but the ensemble gate intentionally does NOT abstain
on unknown because the bot has multiple defense layers below it and
blocking cold-start fires has known production cost).

## 4. Files touched

1. **`src/polymarket_bot/strategies/ensemble_wrapper.py`** — add
   `regime_detector: RegimeDetector | None` + `abstain_regimes:
   Iterable[Regime]` constructor args (both default empty/None); add
   spot-tick observation in `_update_context`; add the pre-mode-dispatch
   refusal branch after tier-gate; add log emission for refusals.
2. **`scripts/run_paper.py`** — read `REGIME_GATE_ENABLED` +
   `REGIME_GATE_ABSTAIN_REGIMES`, validate, instantiate a `RegimeDetector`
   when enabled, pass both to `EnsembleWrapper`.
3. **`tests/strategies/test_ensemble_wrapper.py`** — five new tests (see §5).
4. **`design/phase-15-regime-gate.md`** (this file) — design doc per
   anti-vibe rule #1.
5. **`scripts/audit_regime_wr.py`** (NEW; already landed during the audit
   item) — re-runnable per-regime WR audit.

## 5. Test plan (anti-vibe rule #2)

| name | purpose |
|------|---------|
| `test_regime_gate_disabled_no_change` | `regime_detector=None` / empty abstain set → candidate passes through unchanged (regression guard) |
| `test_regime_gate_blocks_chop_regime` | abstain={chop} + detector primed to return "chop" → returns None + emits `kind=regime_abstained`; LLM never invoked (specialist + meta `call_count == 0`) |
| `test_regime_gate_passes_trending_regime` | abstain={chop} + detector primed to return "trending" → passes through + LLM consulted |
| `test_regime_gate_logs_record` | refusal emits exactly one `kind="regime_abstained"` JSONL line with all expected fields (regime, abstain_regimes, window_ts, base_rationale) |
| `test_regime_gate_under_load` | 100 candidate evals with gate enabled + detector primed for "chop" complete in well under 500ms (no queue-overflow risk; classify() is O(buffer)) |

The under-load test is the queue-doesn't-overflow guard per
`feedback_test_under_load` memory + the 2026-05-09/10 incidents. It
matches the Phase 14 test of the same shape.

## 6. Deploy plan

1. Local `make verify` (ruff + mypy --strict + pytest + lint-imports) green.
2. Commit + push to GitHub.
3. **DEPLOY DEFERRED.** Same blocker as Phase 14: VPS has uncommitted
   dashboard track on `claude/jovial-hermann-7e103f`. Per
   `feedback_defer_deploys_to_natural_restart`, Phase 15 bundles with
   the next natural VPS restart.
4. When the dashboard track lands + bot restarts:
   ```bash
   ssh ops@108.132.51.116
   cd /home/ops/polymarket-5m-bot && git pull --ff-only
   # Add to .envrc — both default to off; safe to set permanently:
   export REGIME_GATE_ENABLED=false
   export REGIME_GATE_ABSTAIN_REGIMES=
   sudo systemctl restart bot-staging.service
   ```
5. Verify per `feedback_vps_deploy_verify_late`: tail journal at +5min
   AND +30min for unexpected restarts or parallel-SSH resets.

## 7. Rollback

If anything regresses with the gate enabled:
```bash
ssh ops@108.132.51.116 "cd /home/ops/polymarket-5m-bot && \
  sed -i 's/^export REGIME_GATE_ENABLED=.*/export REGIME_GATE_ENABLED=false/' .envrc && \
  sed -i 's/^export REGIME_GATE_ABSTAIN_REGIMES=.*/export REGIME_GATE_ABSTAIN_REGIMES=/' .envrc && \
  sudo systemctl restart bot-staging.service"
```

If the bug is in startup validation or detector instantiation (not the
gate behavior itself), rollback is a `git revert` of the Phase 15 commit
followed by VPS pull + restart.

## 8. Success metric

Phase 15 is "GREEN" at the deploy moment if:
- Service restart returns active.
- No new errors in journal.
- Default (`REGIME_GATE_ENABLED=false`) produces identical fire/abstain
  behavior to pre-deploy.
- New tests green in CI.

Phase 15 is "PRODUCING VALUE" when:
- Operator has 7+ days of post-gate-mode data showing a real regime
  bucket with WR<50% on n≥30 AND non-positive PnL.
- Operator flips `REGIME_GATE_ENABLED=true` + populates the abstain set.
- Subsequent 24-72h soak shows fire rate drop proportional to blocked
  regime and PnL improvement (not just WR — see §1 PnL paradox).

The infra ships now; the production value arrives later. **The 2026-05-12
audit explicitly recommends NOT auto-enabling `chop` despite the master
plan's deploy default — because the empirical PnL contribution of chop
on bot-staging's current strategy class is positive and dominant.**

## 9. Risks + mitigations

- **Drift between ensemble's RegimeDetector and v3's RegimeDetector.**
  Different instances of the same class, same defaults; no shared state.
  Mitigated by both paths importing from the same module.
- **Operator misconfigures abstain set (typo, wrong label).** Mitigated by
  startup validation that raises ValueError on unknown labels AND on
  `unknown`.
- **Regime gate triggers on cold-start fires.** Mitigated by NOT including
  `unknown` in the valid abstain set; classify() returns "unknown" during
  cold-start which is never blocked.
- **Detector buffer memory growth.** Bounded by detector's own
  `window_10m_s` deque trim; ~600 ticks max → ~5KB.
- **Concurrent SpotTick observation race.** None — `on_event` is awaited
  serially by the runner main loop; the detector is single-writer.
- **`mode=off` ignores the gate.** Intentional — `mode=off` bypasses the
  entire wrapper. If operator wants to enable the regime gate without
  the LLM ensemble, they need at least `mode=shadow`. Mirrored from
  Phase 14 tier-gate behavior. Logged at startup so operator sees the
  warning.

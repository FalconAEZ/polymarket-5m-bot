# Phase 14 — TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST design

**Status:** locked 2026-05-10 after Phase 13 NULL result.
**Owner:** EnsembleWrapper (`src/polymarket_bot/strategies/ensemble_wrapper.py`).
**Audit script:** `scripts/audit_per_tier_wr.py`.

## 1. Problem

The dashboard's per-tier WR breakdown is observational only. There is
no way for the operator to enforce "skip windows whose price-tier
historically loses money" without a code release. The 2026-05-10
per-tier audit (3 days, n=467 fires) showed the 30-50% entry tier at
WR=49.3% on n=75 settled, which is the kind of subset where a kill-
switched tier-blocklist would be useful — **but** that same tier had
positive PnL (+$65) on the 3-day window. The infrastructure should
exist so the operator can flip it on after a longer audit; the
infrastructure must NOT auto-enable a block.

## 2. Out of scope (explicit)

- **No auto-population of the blocklist.** Default = empty. Operator
  reads the audit and sets `TIER_GATE_BLOCKLIST` themselves.
- **No removal of the existing wide_fire / spot_aware_v2 base strategy
  filters.** Tier gate sits AFTER the base strategy already produced a
  candidate; it's an additional refusal class.
- **No changes to the dashboard's per-tier panel.** The panel already
  shows the data operator needs to choose a blocklist.
- **No new tier buckets.** Reuse the exact `PRICE_TIER_BUCKETS` definition
  from `dashboard/loaders.py:341`. To avoid drift, extract it to a
  shared module (`polymarket_bot/tiers.py`) and have both the dashboard and
  the new gate import from there.

## 3. Behavior

### 3.1 Env vars

| name | default | description |
|------|---------|-------------|
| `TIER_GATE_ENABLED` | `false` | If `true`, the wrapper consults `TIER_GATE_BLOCKLIST` on every candidate. |
| `TIER_GATE_BLOCKLIST` | `""` (empty) | Comma-separated tier labels, e.g. `30-50%,<15%`. Whitespace tolerated. Invalid labels raise at startup. |

Kill-switch semantics: with `TIER_GATE_ENABLED=false` the wrapper does
not even compute the tier, so the code path is zero-overhead. With
`TIER_GATE_ENABLED=true` and an empty blocklist, the wrapper computes
the tier (for log fidelity) but never blocks.

### 3.2 Decision flow

In `EnsembleWrapper.on_event`, slot a new branch immediately after the
base strategy emits a candidate, BEFORE the off/shadow/gate mode
dispatch. This means:

- The tier gate applies in all three modes (off / shadow / gate). When
  ENSEMBLE_MODE=off, the wrapper acts as a thin tier-filter.
- The tier gate runs BEFORE the LLM ensemble call — saves a Haiku/Sonnet
  call per blocked window.

Pseudocode:

```python
candidate = await self._base.on_event(event)
if candidate is None:
    return candidate
if self._tier_blocklist and candidate.price_limit is not None:
    tier = tier_label_for_price(candidate.price_limit)
    if tier in self._tier_blocklist:
        self._log_ensemble_event({
            "kind": "tier_abstained",
            "ts_ns": event.ts_utc_ns,
            "window_ts": self._window_ts,
            "decision_id_hint": _decision_hint(candidate),
            "price_limit": candidate.price_limit,
            "tier": tier,
            "blocklist": sorted(self._tier_blocklist),
            "base_rationale": candidate.rationale,
        })
        return None
if self._mode == "off":
    return candidate
# ... existing shadow / gate flow ...
```

### 3.3 Log schema

New JSONL kind in `state/ensemble/<UTC-date>.jsonl`:

```json
{
  "kind": "tier_abstained",
  "ts_ns": 1778430660000000000,
  "window_ts": 1778430900,
  "decision_id_hint": "abc123…",
  "price_limit": 0.42,
  "tier": "30-50%",
  "blocklist": ["30-50%", "<15%"],
  "base_rationale": "strategy=wide_fire mode=ensemble_base delta_bps=+0.00 ttl=30s side=UP"
}
```

The dashboard can later count `kind=tier_abstained` per tier to show
"tier gate refusals" panel.

### 3.4 Startup validation

`scripts/run_paper.py`'s ensemble branch validates the blocklist CSV
against the canonical `PRICE_TIER_BUCKETS` labels. Unknown labels raise
ValueError at startup (fast-fail; operator sees the error in the journal
before the bot processes any market data).

## 4. Files touched

1. **`src/polymarket_bot/tiers.py` (NEW, ~30 lines)** —
   canonical `PRICE_TIER_BUCKETS` + `tier_label_for_price`. Source of
   truth. Lives at top-level (not under `strategies/`) so the dashboard
   can import it without violating the layered-3 import-linter contract
   that forbids `dashboard → strategies`.
2. **`src/polymarket_bot/dashboard/loaders.py`** — replace local
   `PRICE_TIER_BUCKETS` + `_tier_label` with re-export from tiers.py.
   Backward-compatible (same names, same semantics).
3. **`src/polymarket_bot/strategies/ensemble_wrapper.py`** — add
   `tier_blocklist: frozenset[str]` constructor arg (default empty);
   add the pre-mode-dispatch check; add log emission for refusals.
4. **`scripts/run_paper.py`** — read `TIER_GATE_ENABLED` +
   `TIER_GATE_BLOCKLIST`, validate, pass to `EnsembleWrapper`.
5. **`tests/strategies/test_ensemble_wrapper.py`** — five new tests
   (see §5).
6. **`tests/test_tiers.py` (NEW)** — small module-level tests for
   `tier_label_for_price` boundaries. Lives at `tests/` root rather
   than `tests/strategies/` to mirror the top-level module path.

## 5. Test plan (anti-vibe rule #2)

| name | purpose |
|------|---------|
| `test_tier_gate_disabled_no_change` | empty blocklist → candidate passes through unchanged (regression guard) |
| `test_tier_gate_blocks_in_off_mode` | blocklist=["30-50%"], candidate.price_limit=0.42 in mode=off → returns None + logs tier_abstained |
| `test_tier_gate_blocks_in_gate_mode` | same with mode=gate, LLM not invoked at all (assert no specialist call) |
| `test_tier_gate_passes_unlisted_tier` | blocklist=["30-50%"], candidate.price_limit=0.65 → passes through + LLM runs |
| `test_tier_gate_logs_record` | refusal emits exactly one `kind="tier_abstained"` JSONL line with all expected fields |
| `test_tier_label_boundaries` (in test_tiers.py) | 0.14 → "<15%", 0.15 → "15-30%", 0.29 → "15-30%", 0.30 → "30-50%", 0.85 → "85-100%", 1.00 → "85-100%" |
| `test_tier_gate_under_load` | 100 candidates with gate enabled + blocklist={"30-50%"} complete in <500ms total (no queue overflow risk; should be ~zero overhead per candidate) |

`test_tier_gate_under_load` is the queue-doesn't-overflow guard per
`feedback_test_under_load` memory + the 2026-05-09/10 incidents.

## 6. Deploy plan

1. Local `make verify` (ruff + mypy --strict + pytest) green.
2. Commit + push to GitHub.
3. SSH to VPS, `git pull`, add to `.envrc`:
   ```bash
   export TIER_GATE_ENABLED=false
   export TIER_GATE_BLOCKLIST=
   ```
   (defaults = no behavior change; ship dark)
4. `sudo systemctl restart bot-staging.service`.
5. Verify:
   - `systemctl is-active bot-staging.service` returns active
   - tail `state/decisions/<date>.jsonl` — fires continue, no
     `tier_abstained` records (because blocklist empty)
   - tail journal — no startup error
6. Per `feedback_vps_deploy_verify_late` memory: re-check at +5min AND
   +30min to catch parallel-SSH resets.

## 7. Rollback

If anything regresses:
```bash
ssh ops@108.132.51.116 "cd /home/ops/polymarket-5m-bot && \
  sed -i 's/^export TIER_GATE_ENABLED=.*/export TIER_GATE_ENABLED=false/' .envrc && \
  sed -i 's/^export TIER_GATE_BLOCKLIST=.*/export TIER_GATE_BLOCKLIST=/' .envrc && \
  sudo systemctl restart bot-staging.service"
```

If the bug is in startup validation or the import path (not the gate
behavior itself), rollback is a `git revert` of the Phase 14 commit
followed by VPS pull + restart.

## 8. Success metric

Phase 14 is "GREEN" at the deploy moment if:

- Service restart returns active.
- No new errors in journal.
- Default (`TIER_GATE_ENABLED=false`) produces identical fire/abstain
  behavior to pre-deploy.
- New tests green in CI.

Phase 14 is "PRODUCING VALUE" when:

- Operator has 7+ days of post-gate-mode data showing a real
  WR<50% on n≥30 in some tier.
- Operator flips `TIER_GATE_ENABLED=true` + populates the blocklist.
- Subsequent 24-72h soak shows fire rate drop proportional to blocked
  tier and WR climb ≥1.5pp.

The infra ships now; the production value arrives later. This is
intentional — anti-vibe rule says ship infra only when an audit calls
for it, and Phase 14 audit motivated the infra (the gap between
"observation panel" and "enforcement").

## 9. Risks + mitigations

- **Drift between strategy gate buckets and dashboard buckets.** Mitigated
  by extracting `PRICE_TIER_BUCKETS` to `polymarket_bot/tiers.py` and
  re-exporting from `dashboard/loaders.py`.
- **Operator misconfigures blocklist (typo, wrong label).** Mitigated by
  startup validation that raises ValueError on unknown labels.
- **Tier gate triggers in shadow mode and operator sees fewer fires
  than expected.** Documented in this design: tier gate is mode-
  independent. Operator can set `TIER_GATE_ENABLED=false` to disable
  without touching ENSEMBLE_MODE.
- **Future strategies emit `Decision` with `price_limit=None`.** Gate
  treats `None` as unknown-tier and passes through (does NOT block).
  Tested explicitly.

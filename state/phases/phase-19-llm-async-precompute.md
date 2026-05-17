---
title: Phase 19 — LLM async pre-compute
status: SHELVED 2026-05-12 by Phase F cut (LLM removed from fire path; latency problem dissolves)
tags: [phase, optimization, llm, async, latency, queue-overflow, shelved]
---

# Phase 19 — LLM async pre-compute (SHELVED)

**Status: SHELVED 2026-05-12 per [[phase-F-architecture-audit]].** The 12s inline-await problem that motivated this phase no longer exists in production — the LLM ensemble is no longer in the fire path (`STRATEGY=spot_aware_v3` directly, no `EnsembleWrapper`). Design doc preserved as a research artifact for revival if/when the ensemble experiment is re-engaged via env flip and shown to add lift.

Master plan reference: §4 row 19, ~4h estimate, kill-switch env `LLM_PRECOMPUTE_ENABLED`.

Design doc: `design/phase-19-llm-async-precompute.md` (LOCKED but implementation shelved).

## Why this phase exists

Per deep-dive audit 2026-05-12 (`state/sessions/2026-05-12-deep-dive-audit.md`):

| Metric | Last 5.5h soak |
|---|---:|
| Gate-mode timeout rate (12s ceiling hit) | 8.8% |
| Total `meta=None` rate (timeout + other) | 22.1% |
| Records dropped from feed queue overflow | **119,722** |

Root cause: gate-mode in `EnsembleWrapper.on_event` awaits the LLM inline for up to 12s per fire. While awaiting, the runner can't drain the feed queue (1024 cap), so market records overflow and drop. Same architectural class as the 2026-05-09 instant-settle and 2026-05-10 LLM-ensemble queue-overflow incidents (`feedback_test_under_load`).

## Architecture (in one sentence)

Move the LLM ensemble call **off the runner's hot path** — run it as a background task that pre-computes one verdict per window; at fire-time the gate looks up the cached verdict (O(1)) instead of awaiting a fresh call.

## Sub-phases

| Sub | State |
|---|---|
| 19.0 — Design doc | ✅ LOCKED 2026-05-12 |
| 19.1 — Wrapper changes + 7 tests | ⏳ pending (next session) |
| 19.2 — VPS dark deploy | ⏳ pending |
| 19.3 — Flip `LLM_PRECOMPUTE_ENABLED=true` | ⏳ pending |
| 19.4 — +5min/+30min/+24h verify | ⏳ pending |
| 19.5 — 7d soak gate → PROMOTE / ROLLBACK | ⏳ pending |

## Soak gate (Phase 19.5 PROMOTE)

```
PROMOTE if:
  queue_overflow_incidents_in_7d == 0
  AND meta_outcome[gate_timeout] / total_votes <= 0.005
  AND |fire_rate_delta_pct| <= 2.0
  AND daily_pnl_delta_usd >= -30
```

## Related

- [[../sessions/2026-05-12-deep-dive-audit|Deep-dive audit]]
- [[../sessions/2026-05-12-phase-19-design-and-arch-audit-prep|Today's session]]
- [[phase-16b-every-window-mode|Phase 16.B (router, parallel track)]]
- `design/phase-19-llm-async-precompute.md`

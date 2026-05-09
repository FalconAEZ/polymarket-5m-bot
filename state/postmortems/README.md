---
title: Postmortems
tags: [moc, postmortems]
---

# Postmortems

Incident write-ups. Mandatory for:
- Any kill-switch trip (Phase 6+)
- Any > $3 unexplained loss (Phase 6+)
- Any drawdown breaker trip (Phase 6+, mandatory 24h cooling-off + signed-off postmortem before re-enable)
- Any drift / [[../concepts/3-fix-rule|3-fix-rule]] trigger
- Any phase abort (Phase A had one — see [[../research/bonereaper-study-postmortem]])

## Format

Each postmortem is its own file: `<UTC-date>-<short-slug>.md`.

```yaml
---
date: YYYY-MM-DD
type: <kill-switch | unexplained-loss | drift | abort | other>
phase: <where it happened>
severity: <info | warn | critical>
tags: [postmortem, ...]
---

# YYYY-MM-DD — <headline>

## What happened (timeline)
- HH:MM:SS UTC — first observation
- HH:MM:SS UTC — what was tried
- ...

## Root cause
- ...

## Blast radius
- USD lost / at risk: ...
- Time lost: ...
- Trust impact: ...

## Fix
- Immediate: ...
- Long-term: ...

## Prevention
- ...

## Connections
- Phase: [[../phases/...]]
- Related decision: [[../decisions/README#decision-N|...]]
```

## Current state

- [[2026-05-07-env-req-rtf-key-on-disk]] — Signer privkey landed in `env req.rtf` (mode 644) instead of `.envrc` during Phase 1A task 1.1. Severity: low (no money at risk; Phase 1A is no-money by [[../decisions/README#decision-20|decision #20]]). Operator-side cleanup (`rm` of the rtf file) still pending. Generalized lesson at [[../concepts/secret-hygiene]].
- [[2026-05-09-orphan-fd-decisions]] — Bot's append FDs on `state/decisions/*.jsonl` orphaned by an atomic-rename writer (most likely `resolve_decisions.py` legacy in-place mode) for 8.5h during the dashboard-v3 deploy session. Severity: warn — $0 lost, $0 at risk, dashboard reported wrong numbers (~3× off). Recovered all decisions via `/proc/<pid>/fd/` snapshot; bot resumed cleanly. Three concentric defenses landed in commit `ac80f9b`: DecisionLog inode-stability check + salvage, `resolve_decisions.py` refuses in-place mode, dashboard staleness incident wire (>30 min gap while bot alive). Phase: [[../phases/phase-11-spot-aware|Phase 11.A.X.B]].

The bonereaper-study abort at [[../research/bonereaper-study-postmortem]] is closer to a phase postmortem than an incident postmortem — it lives in `research/` because it's about the *study* outcome, not a runtime failure.

## See also

- [[../runbooks/README|Operational runbooks]] — what to do *during* an incident
- [[../concepts/anti-vibe-rules]] — operating rules that trigger postmortems
- [[../concepts/3-fix-rule]] — when bug-fix loops become incidents
- [[../concepts/kill-switches]] — Phase 6+ guardrails that fire postmortems

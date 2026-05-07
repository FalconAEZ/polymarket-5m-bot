---
title: Phase 0 — Foundations
date-closed: 2026-05-06
status: closed-green
result: GREEN — all 10 gate checks passed
tag: phase-0-pass (commit 3195d2c → README update 56a44ca)
tags: [phase, foundations, closed, green]
---

# Phase 0 — Foundations

## Owner intent

Stand up a clean development environment, confirm every account-level prerequisite, and seed the project skeleton. **No money moves. No keys generated. No production data touched.**

## Gate criteria (all 10 passed)

```
[gate-0.1] python ≥ 3.11 (uv-managed)        → 3.11.15 ✓
[gate-0.2] make verify                        → ruff + mypy --strict + pytest all green
[gate-0.3] GitHub remote                      → FalconAEZ/polymarket-5m-bot ✓
[gate-0.4] agent-skills present               → authentication.md + gasless.md ✓
[gate-0.5] 7 reference repos cloned           → all present in references/ (gitignored)
[gate-0.6] secrets loaded                     → 4/4 (Telegram, Anthropic, Polygon RPC) ✓
[gate-0.7] Telegram smoke message             → delivered, message_id=4
[gate-0.8] Polygon RPC live                   → chain_id 0x89 ✓
[gate-0.9] 17 required project files          → all present ✓
[gate-0.10] no secrets staged                 → clean ✓
```

Full evidence: `runbooks/gate-evidence/phase-0.txt`.

## What landed in this phase

| File | Purpose |
|---|---|
| `pyproject.toml` + `uv.lock` | uv-managed deps, locked |
| `mypy.ini` (strict) + `ruff.toml` + `.importlinter` | static checks |
| `Makefile` | single entry point: `make verify`, `make gate-0`, etc. |
| `.github/workflows/ci.yml` | mirrors local checks in CI |
| `.pre-commit-config.yaml` | local-side hooks (ruff + format + TODO grep + module-header) |
| `.envrc.example` | secret template (gitignored `.envrc` populated by operator) |
| `runbooks/scripts/check_headers.py` | enforces ≥80-char module docstrings |
| `runbooks/gates/phase-0.sh` | gate evidence script |
| `runbooks/contacts.md` | operational channels reference (handles, no secrets) |
| `CLAUDE.md` | project preferences read by every Claude Code session |
| `README.md` + `MASTERPLAN.md` + `RUNBOOK.md` | canonical docs |
| `pdfs/{MASTERPLAN,BUILD_SPEC,REQUIREMENTS,BONEREAPER_STUDY}.pdf` | rendered specs |
| `~/.claude/skills/agent-skills/` | dropped into Claude Code skills dir |
| `references/` (8 repos, gitignored) | mining-only |
| `state/` (gitignored, this vault) | operator notes |

## Open decisions resolved this phase

- **OD-1** Polygon RPC: **resolved** → Alchemy free tier in active use.

## Open decisions still open after Phase 0

- OD-2 trades.db backup target — defer to Phase 5
- OD-3 Anthropic top-up to $150 — defer to before Phase 4
- OD-4 gasless relayer specifics — **moves to Phase 1A** task 1.0
- OD-5 LLM ensemble keep/cut — Phase 3 A/B
- OD-6 hardware wallet purchase — $2k bankroll trigger

## Connections

- Phase before: bootstrap (no formal phase, see [[../sessions/2026-05-06]])
- Phase after: [[phase-1-wallet-auth]]
- Decisions touched: [[../decisions/README#decision-1|#1 (UAE)]], [[../decisions/README#decision-7|#7 (Telegram)]], [[../decisions/README#decision-8|#8 (GitHub)]], [[../decisions/README#decision-15|#15 (UTC)]]
- Concepts: [[../concepts/anti-vibe-rules]] (we now enforce all 10 + the 25 operating rules)
- Memory checkpoint: `memory/checkpoint_phase_0.md`

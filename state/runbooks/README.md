---
title: Operational runbooks
tags: [moc, runbooks, ops]
---

# Operational runbooks

Vault-side index of operational procedures. The actual gate scripts and scripts-with-side-effects live in the project root under `runbooks/`; this folder is for the operator's plain-English playbooks.

## Files in this folder (vault-tracked)

> _As of 2026-05-07: this index plus the entry README is all that's here on the vault side. Operational runbooks live in the project root under `runbooks/` (in git); see below._

Planned vault-side runbooks (will land as the project advances):

- `runbooks/alerts.md` — Telegram alert taxonomy, max-time-to-acknowledge per severity (Phase 5)
- `runbooks/daily.md` — daily operator ritual at 12:00 UTC (Phase 6)
- `runbooks/refit.md` — quarterly weight refit procedure (Phase 7)
- `runbooks/capture-launch.md` — Phase 2 capture launch + tmux recovery (will be written in the Phase 2 dev session)

## Project-root runbooks (NOT in vault)

These live in `runbooks/` (project root, gitignored from this vault folder but tracked in git):

- `runbooks/contacts.md` — operational channels (Telegram, GitHub, Anthropic, Alchemy)
- `runbooks/wallet-ops.md` — Funder/Signer hygiene, sweep policy, four recovery procedures, MetaMask hygiene, pre-send checklist (shipped Phase 1A task 1.6, commit `0631090`; addresses filled in at `1537a18`)
- `runbooks/scripts/check_headers.py` — module-docstring enforcer
- `runbooks/gates/phase-0.sh` — Phase 0 gate (10 checks; ✅ green)
- `runbooks/gates/phase-1a.sh` — Phase 1A gate (10 checks; ✅ green at `1537a18`; walks up to find `.envrc` for git-worktree case)
- `runbooks/gates/phase-1.sh` — Phase 1B gate (deferred to head of Phase 6)
- `runbooks/gate-evidence/phase-0.txt` — captured Phase 0 evidence
- `runbooks/gate-evidence/phase-1a.txt` — captured Phase 1A evidence (2026-05-06T20:17:29Z)
- `runbooks/study/preflight-decision.md` — bonereaper study decision (final ABORT)
- `runbooks/study/quick-audit.html` + `weekly-audit.md` — Phase A reports

## Why two locations?

- **Project-root `runbooks/`** is gate-script + reproducible-evidence territory. Lives in git.
- **Vault `state/runbooks/`** is plain-English playbook territory. Lives only on the laptop (gitignored), so the operator can keep ad-hoc operational notes without them ending up in the public-ish git history.

## See also

- [[../phases/README|Phase ledger]] — what gates have run
- [[../postmortems/README|Postmortems]] — incident write-ups (related but different)
- [[../concepts/kill-switches]] — Phase 6 guardrails that fire alerts
- [[../concepts/anti-vibe-rules]] — the discipline that produces the runbooks

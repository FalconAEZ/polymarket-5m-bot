---
title: Polymarket BTC 5-Min Bot — Vault MOC
date: 2026-05-07
tags: [moc, index, vault-root]
---

# Polymarket BTC 5-Min Bot — Vault Map of Content

> Operator notebook for a real-money trading bot. The canonical specs and execution doc live in the project root; this vault is for the *operator's* layer — phase-by-phase notes, concept maps, postmortems, and connections between everything.

## Project status (live ticker)

| Item | State |
|---|---|
| Bootstrap | ✅ done |
| [[phases/phase-A-bonereaper\|Phase A — Bonereaper study]] | ✅ closed, **ABORT** (52.65% WR vs 60% gate) |
| [[phases/phase-0-foundations\|Phase 0 — Foundations]] | ✅ closed, tag `phase-0-pass` |
| [[phases/phase-1-wallet-auth\|Phase 1A — Wallet & Auth (no-money)]] | ✅ closed, tag `phase-1a-pass` at `1537a18` |
| Phase 1B — Wallet funding + first $5 order | ⏸ deferred to head of Phase 6 per [[decisions/README#decision-20\|decision #20]] |
| [[phases/phase-2-data-plane\|Phase 2 — Read-only data plane]] | ✅ closed |
| Phase 3 — Backtest + LLM A/B | ✅ closed, tag `phase-3-pass`, LLM A/B verdict CUT (latency/cost gates) |
| Phase 4 — Paper trading on live venue | ✅ closed |
| Phase 4.5 — Streamlit ops dashboard | ✅ closed at `c1ff257` |
| Phase 5 — VPS production deploy + alerter + litestream | ✅ closed, tag `phase-5-pass` at `e43b77c` |
| [[phases/phase-11-spot-aware\|Phase 11.A.2 — spot_aware aggressive-mode soak]] | 🟡 **48h gate at 2026-05-10 22:26:15 UTC** (~32h remaining at 2026-05-09 14:30 UTC) |
| Phase 11.A.X.B — Dashboard v3 (FastAPI + React) | ✅ closed 2026-05-09; orphan-FD incident contained + 3-tier defense in depth |
| Phase 11.B+ | ⏳ depends on 11.A.2 gate outcome |

Latest commit (branch `claude/trusting-spence-03c165`): `d32d1d5` — CumulativePnlPanel ships. Six commits ahead of `76e104b` (the prior session tip), pushed to origin.

Bot status: `bot-staging.service` active on VPS (Lightsail eu-west-1, `108.132.51.116:2222`), running `spot_aware` in aggressive mode since 2026-05-08 22:26:15 UTC. Dashboard at `127.0.0.1:8505` via SSH tunnel (`make dash-tunnel`); React bundle `index-D6WMsd2r.js`. **Soak data preserved** through the 8.5h orphan-FD incident on 2026-05-09 — see [[postmortems/2026-05-09-orphan-fd-decisions]].

Funder address: `0x512DA3825E69A8c19d2e0D00b66dd23d3ec95d22`. Signer address: `0x8d9759A73D65aD32cd858eb3AdE46ce56F5F2B4A`. Both public; keys live in age-encrypted backups + (Signer only) gitignored `.envrc`.

Open operator-side cleanup: [[postmortems/2026-05-07-env-req-rtf-key-on-disk|env req.rtf still has the Signer privkey on disk]]; pending `rm`.

**Next session:** `phase-prompts/phase-11.a-gate-2026-05-10.txt` — aggressive-mode 48h gate review. Decide promote / revert / postmortem against the criteria in `runbooks/decisions/aggressive-mode-2026-05-09.md`. Recommended: PR-merge `claude/trusting-spence-03c165` → `main` first so the gate tag lands on main.

## Quick links

### Canonical project docs (in project root, NOT in vault)
- `MASTERPLAN.md` — architectural rationale (the *why*)
- `RUNBOOK.md` — phase-by-phase execution (the *what next*)
- `CLAUDE.md` — project preferences read by every Claude Code session
- `pdfs/BUILD_SPEC.pdf` — visual master spec (24 pp)
- `pdfs/REQUIREMENTS.pdf` — bootstrap shopping list (19 pp)
- `pdfs/BONEREAPER_STUDY.pdf` — research stream (ARCHIVED — see [[phases/phase-A-bonereaper]])

### Memory (cross-session durable state)
- `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/MEMORY.md` — index
- `memory/project_decisions.md` — 20 locked decisions
- `memory/checkpoint_phase_0.md` — Phase 0 close state
- `memory/checkpoint_phase_1a.md` — Phase 1A close state (addresses, OD-4 resolution, tag pointer)

### Vault sub-indexes
- [[phases/README|Phase ledger]] — what's done, in flight, next
- [[concepts/README|Concept glossary]] — window-delta, Tier-3, gasless relayer, etc.
- [[research/README|Research index]] — audits, data sources, methodologies
- [[decisions/README|Decisions index]] — locked decisions, open decision-points
- [[sessions/README|Sessions ledger]] — daily session logs
- [[postmortems/README|Postmortems]] — incident write-ups (empty so far — no incidents)
- [[runbooks/README|Operational runbooks]] — alerts, recovery, daily ritual

## How to use this vault

- **Every phase gate gets a note** under [[phases/README]] linking to its gate-evidence and the next phase's pre-flight.
- **Every locked decision** is mirrored from `memory/project_decisions.md` in [[decisions/README]] with backlinks to the phases / concepts that triggered it.
- **Every concept that the bot or strategy depends on** has its own note under [[concepts/README]] — short (50-100 lines), defines the term, lists where it shows up, links to the canonical source.
- **Every audit / research output** is summarized under [[research/README]] with the methodology in plain English.
- **Every session ends** with a 2-line note in `sessions/<utc-date>.md` (anti-vibe rule #5).
- **Every incident** (kill-switch trip, > $3 unexplained loss, drift) gets a postmortem in `postmortems/`.

## Graph hint

If you open Obsidian's graph view, you should see:
- **Phase nodes** as a chain (A → 0 → 1A → 1B → 2 → 3 → ...).
- **Concept nodes** clustered (signal concepts, risk concepts, infra concepts).
- **Decision nodes** linking to the phase that locked them and the concepts they affect.
- **Research nodes** linking to the audit pipeline that generated them.

Backlinks are how you find "everywhere we touched the gasless relayer" or "every decision related to the LLM ensemble." Use them.

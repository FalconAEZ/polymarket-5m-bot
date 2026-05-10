---
title: Polymarket BTC 5-Min Bot — Vault MOC
date: 2026-05-11
tags: [moc, index, vault-root]
---

# Polymarket BTC 5-Min Bot — Vault Map of Content

> Operator notebook for a real-money trading bot. The canonical specs and execution doc live in the project root; this vault is for the *operator's* layer — phase-by-phase notes, concept maps, postmortems, and connections between everything.

## Project status (live ticker)

| Item | State |
|---|---|
| Bootstrap | ✅ done |
| [[phases/phase-A-bonereaper\|Phase A — Bonereaper study]] | ✅ closed, **ABORT** at 60% gate |
| [[phases/phase-0-foundations\|Phase 0 — Foundations]] | ✅ closed, tag `phase-0-pass` |
| [[phases/phase-1-wallet-auth\|Phase 1A — Wallet & Auth (no-money)]] | ✅ closed, tag `phase-1a-pass` at `1537a18` |
| Phase 1B — Wallet funding + first $5 order | ⏸ deferred to head of Phase 6 per [[decisions/README#decision-20\|decision #20]] |
| [[phases/phase-2-data-plane\|Phase 2 — Data plane]] | ✅ closed |
| Phase 3 — LLM A/B | ✅ closed at `3cd4a70`, tag `phase-3-pass`. Verdict CUT (latency + cost fail decision #16); ensemble retained for Phase 4 re-run |
| Phase 4 + 4.5 — Paper runtime + dashboard | ✅ closed at `c1ff257` |
| [[phases/phase-5-vps\|Phase 5 — VPS + LLM ensemble]] | ✅ closed 2026-05-08, tag `phase-5-pass`. ENSEMBLE_MODE=gate promoted 2026-05-10 16:31:15 UTC after shadow-mode validation. Five defense layers live |
| [[phases/phase-11-spot-aware\|Phase 11.A — SpotAware paper soak]] | ✅ superseded by ensemble experiment |
| Phase 12 — Master plan drafted | ✅ planning artifact 2026-05-10; 36-page PDF, 12-phase optimization roadmap |
| [[phases/phase-13-fill-rate\|Phase 13 — Fill-rate lift]] | 🛑 **NULL result** 2026-05-10. Audit showed 1-2¢ unfilled subset W=46.2% (below bot's 52% WR); 0-1¢ bucket empty. No code shipped. Commit `d4f3fde` |
| [[phases/phase-14-tier-gate\|Phase 14 — Entry-price tier blocklist]] | 🟢 **infra dark-shipped** 2026-05-10 at `b6b3599`. `TIER_GATE_ENABLED=false` default. **VPS deploy DEFERRED** — parallel dashboard track uncommitted on VPS |
| Phase 15 — Regime gate | ⏳ next session. Prompt at `phase-prompts/phase-15-regime-gate-2026-05-12.txt` |
| Phases 16-25 | ⏳ per master plan §4; one phase per session |

**Bot live:** bot-staging.service active since 2026-05-10 16:31:15 UTC on VPS at `c66fc07`. Strategy = ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire. Real edge as of 2026-05-10: 52.0% WR / +$76.79 / 402 settled / 12.5% LLM timeout rate / 62.5% effective fire rate. (Phase 14 dark-shipped but not yet pulled to VPS due to parallel dashboard track.)

Latest commit on `claude/jovial-hermann-7e103f`: `d0fea5c`. Tags: `phase-0-pass`, `phase-1a-pass`, `phase-3-pass`, `phase-5-pass`, `study-A-final`, `study-A-abort`. (Master-plan optimization phases 13-25 don't carry git tags by design — only structural milestones do.)

Funder address: `0x512DA3825E69A8c19d2e0D00b66dd23d3ec95d22`. Signer address: `0x8d9759A73D65aD32cd858eb3AdE46ce56F5F2B4A`. Both public; keys live in age-encrypted backups + (Signer only) gitignored `.envrc`.

Open operator-side cleanup: [[postmortems/2026-05-07-env-req-rtf-key-on-disk|env req.rtf still has the Signer privkey on disk]]; pending `rm`.

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

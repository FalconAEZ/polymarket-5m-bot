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
| Phase 4 + 4.5 — Paper runtime + dashboard | ✅ closed at `c1ff257`. **Streamlit dashboard retired 2026-05-11** in favor of v3 React+FastAPI. |
| [[phases/phase-5-vps\|Phase 5 — VPS + LLM ensemble]] | ✅ closed 2026-05-08, tag `phase-5-pass`. ENSEMBLE_MODE=gate promoted 2026-05-10 16:31:15 UTC after shadow-mode validation. Five defense layers live |
| [[phases/phase-11-spot-aware\|Phase 11.A — SpotAware paper soak]] | ✅ superseded by ensemble experiment |
| Phase 12 — Master plan drafted | ✅ planning artifact 2026-05-10; 36-page PDF, 12-phase optimization roadmap |
| [[phases/phase-13-fill-rate\|Phase 13 — Fill-rate lift]] | 🛑 **NULL result** 2026-05-10. Audit showed 1-2¢ unfilled subset W=46.2% (below bot's 52% WR); 0-1¢ bucket empty. No code shipped. Commit `d4f3fde` |
| [[phases/phase-14-tier-gate\|Phase 14 — Entry-price tier blocklist]] | 🟢 **infra DEPLOYED dark** 2026-05-10 at `b6b3599`. `TIER_GATE_ENABLED=false` default; live on VPS since 21:58:44 UTC bundle restart |
| [[phases/phase-15-regime-gate\|Phase 15 — Regime gate wired to ensemble]] | 🟢 **infra DEPLOYED dark** 2026-05-10 at `fbcd38a`. `REGIME_GATE_ENABLED=false` default; bundled with Phase 14 deploy. Audit found chop MARGINAL (51.4% WR) but +$1725 PnL dominant — operator-approved infra-only ship, abstain set empty |
| [[phases/phase-15.5-pnl-truth-bundle\|Phase 15.5 — PnL truth + 18B + 16 + v3 dashboard recovery]] | ✅ **SHIPPED + LIVE** 2026-05-11. Naive sum +$2,556 → corrected **+$75.26** (entire gap = 41 `settled_correction` records). Phase 18B `meta_outcome` telemetry, Phase 16 scenarios panel + `apply_settled_corrections` wired into v3 dashboard, Streamlit fully deleted, v3 source recovered from `claude/dashboard-pm-truth-fix-7e103f`. Commits `d6f02d1 → f0ee20d` (10 total) |
| **Phase 16.B — every-window mode (signal-driven router)** | 🟡 **RESEARCH PHASE 2026-05-11** — operator-authorized revisit of decision #6 + partial #9. Study at [[research/phase-16b-every-window-study]]; phase prompt at `phase-prompts/phase-16b-every-window-mode-2026-05-11.txt`. **No code shipped — awaiting operator sign-off on §8 questions.** |
| Phase 17 — Position sizing modes (`POSITION_SIZING_MODE`) | ⏳ next master-plan slot. **GATED on operator approval to revisit decision #9** ($5 flat → fractional). Phase 16.B partially relaxes #9 (down-shaping only) — Phase 17 will add upward Kelly. |
| Phase 18 — Kelly sizing | ⏳ revisits decision #9 — operator-gated |
| Phase 19 — LLM async pre-compute (`LLM_PRECOMPUTE_ENABLED`) | ⏳ Phase 18B telemetry now feeding it real attribution data instead of guesses |
| Phases 20-25 | ⏳ per master plan §4; one phase per session |

**Bot live:** `bot-staging.service` active since **2026-05-10 23:50:50 UTC** on VPS at `831c756` (Phase 15.5 bundle). Strategy = `ensemble` + `ENSEMBLE_MODE=gate` + `ENSEMBLE_BASE_STRATEGY=wide_fire`. Both kill-switches dark (`TIER_GATE_ENABLED=false`, `REGIME_GATE_ENABLED=false`). Six defense layers live (background-settle, instant-settle, periodic-orphan-recovery, post-hoc gamma retry, ensemble timeout, regime/tier dark-ship infra ready). 70+ post-restart `ensemble_vote` records carry the new `meta_outcome` field; 97.1% `ok`, 2.9% `invariant_violated` — first attribution data Phase 18B was built to surface.

**Dashboard live:** `dashboard-server.service` active since **2026-05-11 06:25:15 UTC** on VPS at `f0ee20d` (FastAPI + React v3 on `127.0.0.1:8505`). Access via SSH tunnel `-L 8505:127.0.0.1:8505 ops@108.132.51.116` then open `http://127.0.0.1:8505`. New BANKROLL SCENARIOS panel in row D. `decisions_truth_source=polymarket`, `agg.total_pnl_usd=$75.26`.

Latest commit on `claude/jovial-hermann-7e103f`: `f0ee20d` (Phase 15.5 ADDENDUM). Tags: `phase-0-pass`, `phase-1a-pass`, `phase-3-pass`, `phase-5-pass`, `study-A-final`, `study-A-abort`. (Master-plan optimization phases 13-25 don't carry git tags by design — only structural milestones do.)

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

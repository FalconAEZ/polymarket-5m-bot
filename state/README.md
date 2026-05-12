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
| [[phases/phase-16b-every-window-mode\|Phase 16.B — every-window mode (signal-driven router)]] | ⏸ **PAUSED 2026-05-12 by Phase F cut.** 16.B.4 + 16.B.5 had SHIPPED + LIVE on 2026-05-11/12 (`2eb54fd`, `3875d3c`, `7a5b19e`); router shadow ran on `EVERY_WINDOW_SHADOW=true` until Phase F cut commented it out. Router design depends on `W_LLM=0.25` signal which Phase F removed from production. Code intact; revival requires no-LLM router redesign (`W_DET=0.30, W_REG=0.30, W_TIER=0.20, W_KELLY=0.20`). |
| Phase 17 — Position sizing modes (`POSITION_SIZING_MODE`) | ⏳ SUBSUMED by Phase 16.B (paused). |
| Phase 18 — Kelly sizing | ⏳ SUBSUMED by Phase 16.B (paused). |
| Phase 19 — LLM async pre-compute (`LLM_PRECOMPUTE_ENABLED`) | ⏸ **SHELVED 2026-05-12 by Phase F cut.** Design doc complete (`design/phase-19-llm-async-precompute.md`); implementation deferred indefinitely — the 12s inline-await latency that motivated this phase dissolves when LLM exits the fire path. |
| [[phases/phase-F-architecture-audit\|Phase F — Final-stage architecture audit + convergence]] | ✅ **CLOSED 2026-05-12** after 4 intentional restarts (cut → EV_min tighten → v3 source fix → v3→v2 pivot). Final state: STRATEGY=spot_aware_v2 (PHASE-F-4, ActiveEnter 15:42:38 UTC 2026-05-12). Phase F.3 audit superseded by Phase G full study. |
| [[phases/phase-G-edge-discovery\|**Phase G — Full edge-discovery deep dive**]] | ✅ **CLOSED 2026-05-13** analytical-only. 635 fires × 17 dimensions truth-corrected. **Headline: bot has 50.0% WR / −$18.96 net over 633 settled fires = zero edge.** But tier 30-50% × \|Δ\|<5 cell wins (n=83, +$0.65/trade, +$54). Kelly + compounding Monte Carlo: Conservative $1k → $116k median by 90d if 58% backtest WR holds; Downside (50% WR regression) reveals 97% paths hit catastrophic drawdown. **629K PDF on operator Desktop.** Feeds Phase H. |
| [[phases/phase-H-v2_1\|**Phase H — v2.1 implementation**]] | 🟡 **H.1 strategic + H.FINAL engineering spec SHIPPED 2026-05-13.** v2.1 = v2 + 4 filter changes (CH1-CH4: reject Δ=0, reject EV [0.02-0.05), tier-specific Δ floor) + Kelly sizing (CH5-CH6) + multi-fire (CH7-CH8) + BankrollTracker. 22 tests + 14 past-incident defenses specified. H.2 code work next session per `phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt`. H.5 deploy + H.6 7-day soak gate follow. |
| Phase I — Phase 6 readiness review | ⏳ deferred Phase 24 from master plan; gated on Phase H.6 PROMOTE verdict. Pre-blocker: Phase 1B funding flow has never been executed. |

**Bot live:** `bot-staging.service` active since **2026-05-12 15:42:38 UTC** (PHASE-F-4 — honest-pushback pivot v3→v2 after v3 fired 0 in 36 min) on VPS at `af53490`. **Strategy = `spot_aware_v2`** (May 10's proven +$46-day profile; no regime gate; no LLM). The Phase F cut killed ensemble+wide_fire; PHASE-F-4 then chose v2 over v3 because v3's regime gate had only 19-trade backing while v2 had 184-trade May-10 production data. All 5 defense layers operational. 0 Anthropic API calls. First v2 fire at 15:43:23 UTC (45 sec after deploy). Expected v2 profile: ~184 fires/day, ~52% WR, ~$0.25/trade.

**Dashboard live:** `dashboard-server.service` active since **2026-05-11 06:25:15 UTC** on VPS at `f0ee20d` (FastAPI + React v3 on `127.0.0.1:8505`). Access via SSH tunnel `-L 8505:127.0.0.1:8505 ops@108.132.51.116` then open `http://127.0.0.1:8505`. Bankroll snapshot: $1006.01 (+$6.01 vs $1000 start). `decisions_truth_source=polymarket`. NOTE: `feeds:[]` field is empty — cosmetic gap (no feed-snapshot publish path); does NOT affect trading.

Latest commit on `claude/jovial-hermann-7e103f`: `9566f30` (Phase H.2 next-session prompt). Bot on v2 under PHASE-F-4 (since 2026-05-12 15:42:38 UTC). Phase G analytical study complete; Phase H v2.1 implementation specified, code work next session. Tags unchanged: `phase-0-pass`, `phase-1a-pass`, `phase-3-pass`, `phase-5-pass`, `study-A-final`, `study-A-abort`. (Phase F/G/H don't carry git tags by design — only structural milestones do.)

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

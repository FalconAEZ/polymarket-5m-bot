---
title: Locked decisions index
tags: [moc, decisions]
---

# Locked decisions

Mirror + cross-reference of `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`. The memory file is the canonical source; this note exists for vault-side cross-linking with the rest of the project.

> **Rule:** Locked decisions are not relitigated. If a phase task surfaces a real conflict with one of these, flag it as "Decision X needs revisit due to Y" — don't silently override.

## The 20

### #1 — UAE-resident operator
Polymarket-permitted jurisdiction. Decisions #2 (Dublin VPS) flow from this. See [[../phases/README|phase ledger]].

### #2 — Dublin AWS Lightsail eu-west-1
Sub-5ms to Polymarket CLOB; avoids UK eu-west-2 geo-block. Phase 5.

### #3 — NautilusTrader engine + py-clob-client
Production-grade engine + official Polymarket Python client. Phase 3 + Phase 1A.

### #4 — Anthropic API only — no OpenAI fallback
Simpler matrix. The deterministic [[../concepts/tier-3-deterministic|Tier-3]] catches every LLM failure path. Connects to [[../concepts/llm-ensemble|LLM ensemble]].

### #5 — 3 agents + meta-decider (locked at 3)
Orderbook microstructure, oracle-gap, momentum, plus Sonnet meta. The optional 4th `behavioral_mimic` agent is OUT per [[#decision-19|decision #19]]. See [[../concepts/llm-ensemble]].

### #6 — Tier-3 deterministic threshold ≥ 0.6 composite
Window-delta + oracle-gap. See [[../concepts/tier-3-deterministic]].

### #7 — Telegram bot via @BotFather for operator alerts
Push notifications anywhere; replaces Discord. Smoke-verified in Phase 0.

### #8 — GitHub private repo
`FalconAEZ/polymarket-5m-bot`. CI via GitHub Actions.

### #9 — $5 flat per trade for first 100 trades
Pre-Kelly learning budget. See [[../concepts/$5-flat-sizing]].

### #10 — $1,000 starting bankroll
Real capital + meaningful Kelly transitions; HW wallet trigger one rung away. See [[../concepts/funder-signer]].

### #11 — Funder/Signer wallet separation from Phase 1
See [[../concepts/funder-signer]] for the topology.

### #12 — Hardware wallet trigger = $2k bankroll
Phase 7 step 7.1. Not now.

### #13 — Phase 1 order: derive creds → test sign → fund
Locked discipline. NOT relaxed by the [[#decision-20|1A/1B split]] — the split just pauses between "test sign" and "fund."

### #14 — Anthropic budget tiers
$50 (Phases 0-3) → $150 (before Phase 4) → $300 (before Phase 6) → $200/mo sustained. Empirical $0.19-0.58/hour.

### #15 — UTC everywhere
Logs, DB, Obsidian daily notes. No mixing of TZ + window timestamps.

### #16 — LLM-vs-deterministic A/B in Phase 3
Retain ensemble only if uplift ≥ 3 pp over baseline. See [[../concepts/llm-ensemble]] retention rule.

### #17 — Polymarket gasless relayer for order submission
Avoids public-mempool MEV/front-running. See [[../concepts/gasless-relayer]] for the actual mechanics (orders go via standard CLOB, gas only for one-time approvals).

### #18 — Obsidian arch: laptop-only vault, bot writes to `state/` in git
This vault. Single source of truth.

### #19 — Bonereaper cloning research stream: ABORTED 2026-05-06 ⛔
Operator chose option (A): drop the entire study. 7-day audit confirmed 52.65% win-rate (95% CI [52.24%, 53.06%]) — real but slim edge, well below 60% gate. Phases B–G of `pdfs/BONEREAPER_STUDY.pdf` not designed; ensemble stays at 3 agents only. See [[../phases/phase-A-bonereaper]] and [[../research/bonereaper-study-postmortem]].

### #20 — Phase 1 split into 1A (no-money, now) and 1B (funded, pre-live) 🔀 ✅ 1A SHIPPED 2026-05-06
Locked 2026-05-06. 1A ships tasks 1.0, 1.1, 1.2, 1.3, 1.6 + new gate `runbooks/gates/phase-1a.sh` (tag `phase-1a-pass`). 1B ships tasks 1.4, 1.5 + original gate (tag `phase-1-pass`) at the head of Phase 6. [[#decision-13|Decision #13]] preserved (creds → test sign → fund order); we just pause between "test sign" and "fund." OD-4 resolutions captured in `design/gasless.md`: orders via standard CLOB API, skip Builder Program, signature_type=0, funder=Signer's own address. See [[../phases/phase-1-wallet-auth]] and [[../concepts/gasless-relayer]]. **1A closed 2026-05-06 at commit `1537a18`, tag `phase-1a-pass` pushed; Funder=`0x512D…5d22`, Signer=`0x8d97…2B4A`.**

## Open decision-points (resolved as encountered)

| # | Decision | Resolved in / when |
|---|---|---|
| OD-1 | Polygon RPC: Alchemy / Chainstack / QuickNode | ✅ resolved Phase 0 → Alchemy |
| OD-2 | trades.db backup target | defer to Phase 5 |
| OD-3 | Anthropic top-up to Tier 2 | defer to before Phase 4 |
| OD-4 | Gasless relayer specifics | ✅ resolved 2026-05-06 → standard CLOB, skip Builder Program, sig_type=0 (decision #20); shipped & verified end-to-end via `scripts/test_auth.py` against live Polymarket at gate `1537a18` |
| OD-5 | LLM ensemble keep/cut | Phase 3 A/B |
| OD-6 | Hardware wallet purchase | $2k bankroll trigger |

## See also

- `~/.claude/projects/.../memory/project_decisions.md` — canonical source
- [[../phases/README|Phase ledger]] — where decisions get applied
- [[../concepts/README|Concept glossary]] — what the decisions reference

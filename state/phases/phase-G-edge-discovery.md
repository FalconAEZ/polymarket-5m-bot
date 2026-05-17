---
title: Phase G — Full edge-discovery deep dive
tags: [phase, research, edge-discovery, kelly, monte-carlo]
status: CLOSED 2026-05-13 — analytical phase, no bot changes; feeds Phase H
---

# Phase G — Full edge-discovery deep dive

3-4h analytical session that produced the edge inventory + Kelly + Monte Carlo trajectories that drive Phase H. No bot changes; pure research.

## Headline

**The bot has zero edge in its 5-day production universe** (633 settled fires, 50.0% WR, −$18.96 net). **One winning cell exists** that v2 currently REJECTS:

> tier 30-50% × |Δ_bps|<5: n=83, 48.1% WR, **+$0.65/trade, +$54.17 total**

v2's `|Δ|≥5` floor blocks this zone. wide_fire was firing in it pre-Phase-F. We threw out the winning behavior with the LLM ensemble.

## What shipped

| Artifact | Path |
|----------|------|
| Master dataset (635 fires × 17 dims) | `state/research/phase-G-fires-dataset.csv` |
| Structured findings JSON | `state/research/phase-G-analysis.json` |
| Kelly trajectory JSON | `state/research/phase-G-kelly-analysis.json` |
| 8 charts (dark-terminal style) | `state/research/phase-G-charts/*.png` |
| **PHASE_G_EDGE_DISCOVERY.pdf (629K)** | `pdfs/PHASE_G_EDGE_DISCOVERY.pdf` |
| Markdown source | `runbooks/research/phase-G-edge-discovery-2026-05-12.md` |
| Dataset builder | `scripts/build_edge_dataset.py` |
| Single-dim + cross-tab + Monte Carlo | `scripts/analyze_edge_full.py` |
| Chart builder | `scripts/build_phase_g_charts.py` |
| Kelly + compounding | `scripts/analyze_kelly_compounding.py` |
| PDF builder | `pdfs/build_phase_g_edge_discovery_pdf.py` |
| Phase prompt | `phase-prompts/phase-G-full-edge-discovery-2026-05-12.txt` |

## Edges inventoried (full bot history)

**5 confirmed winners** · **6 confirmed losers** · **2 suggestive (deferred)** · **4 architectural improvements** (Kelly, multi-fire, compounding, tier-specific Δ floor).

## Monte Carlo projections (Kelly 0.25× + compounding + multi-fire)

Conservative ($1,006 start, real v_next pool 58.2% WR, 16 fires/day):
- +30d median: $34,851 · +90d median: **$116,115** · P($2k within 90d): 100%

Aspirational ($10,000 start, 55% target WR, 32 fires/day multi-fire):
- +30d median: $82,972 · +90d median: **$300,934** · P($50k): 100%

Downside (50% WR regression):
- +30d median: $2,084 · +90d median: $10,565 · **P(ruin)=97.4%** (Kelly variance signature)

Bet caps $500/$1000 model Polymarket retail liquidity (uncapped Kelly produces physically-impossible $24B trajectories).

## Phase G → Phase H handoff

Phase G's output becomes Phase H's input:
- Winners → CH1-CH4 filter changes in v2.1
- Architectural improvements → CH5-CH8 (Kelly + multi-fire + compounding)
- Downside scenario → motivates Kelly 0.10× start (not 0.25×) + ROLLBACK gate at WR<45%

## Related

- [[../sessions/2026-05-13-phase-G-edge-discovery-and-phase-H-planning|Session note]]
- [[phase-H-v2_1|Phase H — v2.1 implementation]]
- [[phase-F-architecture-audit|Phase F (cut chain that preceded G)]]
- `memory/checkpoint_phase_G.md` (durable summary)

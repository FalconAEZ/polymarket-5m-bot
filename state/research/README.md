---
title: Research index
tags: [moc, research]
---

# Research index

## Active artifacts

- [[phase-16b-every-window-study]] — **Phase 16.B research study** (2026-05-11). Comprehensive signal inventory + counterfactual design for the every-window mode router. Operator-authorized revisit of locked decisions #6 + #9 (partial). Companion phase prompt at `phase-prompts/phase-16b-every-window-mode-2026-05-11.txt`. **Awaiting operator sign-off** on §8 questions before design doc lock.
- [[bonereaper-study-postmortem]] — Phase A's research output. Cloning study aborted; pipeline kept.
- [[audit-pipeline-recipe]] — the reusable per-market enumeration method that produced the 7-day audit.
- [[data-sources-map]] — Polymarket data source taxonomy with caveats and best-use guides.

## Reference data on disk (gitignored, in this vault)

`state/research/bonereaper/` contains the labelled audit dataset:

| File | Rows / Bytes | Description |
|---|---|---|
| `weekly_events_2026-05-06.json` | 2,017 entries | Gamma API responses for every BTC 5m slug in last 7 days |
| `weekly_trades_2026-05-06.json` | 2,015 markets × N trades | Per-market bonereaper trades (combined filter) |
| `subgraph_fills_maker_2026-05-06.json` | ~8k fills | Raw subgraph fills (legacy CTF Exchange, maker side) |
| `subgraph_fills_taker_2026-05-06.json` | ~14k fills | Raw subgraph fills (taker side) |
| `token_to_condition_2026-05-06.json` | 331 token IDs | Subgraph MarketData lookups |
| `markets_2026-05-06.json` | 166 conditions | Gamma API resolutions |
| `labelled_audit.parquet` | 200KB | Phase A intermediate labelled DataFrame |

These are the full backing data for the [[bonereaper-study-postmortem|Phase A postmortem]]. Re-runnable via `uv run python scripts/research/weekly_audit.py` (cache hits same-day).

## Pipeline scripts (in project root, not vault)

- `scripts/research/_api.py` — HTTP adapter for Polymarket Data + Gamma APIs
- `scripts/research/_subgraph.py` — Goldsky orderbook subgraph adapter
- `scripts/research/quick_audit.py` — original 3-hour Data API audit
- `scripts/research/weekly_audit.py` — per-market enumeration audit (the one that got 7 days)
- `runbooks/gates/study-A.sh` — non-destructive gate evidence

## See also

- [[../phases/phase-A-bonereaper|Phase A summary]]
- [[../decisions/README#decision-19|Decision #19 — cloning stream aborted]]
- [[../concepts/polymarket-data-sources]] — the sources the pipeline uses

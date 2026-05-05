# Polymarket BTC 5-Min Bot

> Operator: Hamad (UAE) · Started: 2026-05-04 · Style: phased, design-first, no vibe coding

A real-money trading bot for Polymarket's BTC 5-minute up/down markets, plus a parallel research stream studying a top-performing wallet.

## Documents (read in order)

| Doc | Purpose | When to read |
|---|---|---|
| [`pdfs/REQUIREMENTS.pdf`](pdfs/REQUIREMENTS.pdf) | Bootstrap shopping list — accounts, tools, repos | **First**, before everything |
| [`MASTERPLAN.md`](MASTERPLAN.md) | Architectural rationale (the *why*) | Background |
| [`pdfs/BUILD_SPEC.pdf`](pdfs/BUILD_SPEC.pdf) | Visual master spec for the trading bot | Skim before Phase 0 |
| [`RUNBOOK.md`](RUNBOOK.md) | Phase-by-phase execution source-of-truth | When executing each phase |
| [`pdfs/BONEREAPER_STUDY.pdf`](pdfs/BONEREAPER_STUDY.pdf) | Behavioral study of wallet `0xeebd...eba30` | When starting the research stream |

## Locked decisions

See `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md` — 18 locked items. Do not relitigate.

Highlights: Anthropic API only · 3 agents + meta-decider · Telegram via BotFather · $5 flat per trade for first 100 trades · $1,000 bankroll · Funder/Signer wallet separation from Phase 1 · Polymarket gasless relayer · Obsidian vault on laptop only.

## Status

Pre-Phase 0. Bootstrap in progress. See `state/sessions/` for daily logs.

## Local dev

```bash
make verify   # ruff + mypy --strict + pytest
make gate-0   # Phase 0 gate (after Phase 0 starts)
```

## Anti-vibe rules

See BUILD_SPEC.pdf p. 22-23. Twenty-five operating rules. Pinned above the desk.

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

- Bootstrap: ✅ done.
- Phase A (bonereaper pre-flight): ✅ closed — **ABORT**. 7-day audit measured 52.65% win-rate (95% CI [52.24%, 53.06%]) over 56,972 BTC 5m trades, below the locked 60% gate. Cloning research stream dropped; main-bot plan unaffected. See `runbooks/study/preflight-decision.md`.
- **Phase 0 (Foundations): ✅ closed — gate green at commit `3195d2c`, tag `phase-0-pass`.** All 10 checks pass: Python 3.11.15, `make verify` green, GitHub remote live, agent-skills + 7 reference repos cloned, secrets loaded, Telegram smoke delivered, Polygon RPC chain_id 0x89 confirmed, 17 required project files present.
- Next: operator opens `RUNBOOK.md` Phase 1 (Wallet & Auth).

See `state/sessions/` for daily logs.

## Local dev

```bash
make verify   # ruff + mypy --strict + pytest
make gate-0   # Phase 0 gate (after Phase 0 starts)
```

## Anti-vibe rules

See BUILD_SPEC.pdf p. 22-23. Twenty-five operating rules. Pinned above the desk.

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
- Phase A (bonereaper pre-flight): ✅ closed — **ABORT** (52.65% win-rate vs 60% gate).
- **Phase 0** (Foundations): ✅ tag `phase-0-pass` @ `3195d2c`.
- **Phase 1A** (Wallet & Auth, no funds): ✅ tag `phase-1a-pass` @ `1537a18`.
- **Phase 2** (Capture): ✅ closed; 4 feeds live, capture running 24/7.
- **Phase 3** (Backtest + LLM A/B): ✅ tag `phase-3-pass` @ `3cd4a70`. **OD-5 verdict: CUT** — ensemble fails latency + cost gates per locked decision #16. Phase 4+ runs deterministic-only. Ensemble code retained, gated behind `--enable-ensemble`.
- **Phase 4 dev** (paper runtime): ✅ closed @ `43f64af`. `design/paper.md` + `_paper/{shadow_book,runner,decision_log}.py` + sim-validation harness + run_paper CLI + monitor runbook + gate scaffold. PaperRunner running in background.
- **Phase 4.5** (operations dashboard): ✅ closed @ `c1ff257`. Single-page Streamlit dashboard at `scripts/dashboard.py` + live demo simulator + `.claude/launch.json` for Claude Preview MCP. **274 pytest pass**, mypy --strict on 43 files, lint-imports 3/3 KEPT. Run: `uv run python scripts/demo_live.py & uv run streamlit run scripts/dashboard.py`. See `runbooks/dashboard.md`.
- Next: operator decides between (A) restart 14-day paper run on Windows PC, (B) skip to Phase 5 (VPS), or (C) polish dashboard further. See `~/Desktop/phase-windows-resume-prompt.txt` on the Mac for the migration prompt.

See `state/sessions/` for daily logs.

## Local dev

```bash
make verify   # ruff + mypy --strict + pytest
make gate-0   # Phase 0 gate (after Phase 0 starts)
```

## Anti-vibe rules

See BUILD_SPEC.pdf p. 22-23. Twenty-five operating rules. Pinned above the desk.

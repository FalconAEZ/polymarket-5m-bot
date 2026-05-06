# CLAUDE.md — project preferences for Claude Code

> Read on every Claude Code session. The runbook (`RUNBOOK.md`) is the source of truth for *what to do next*; this file is the durable preferences and rules layer.

## Project at a glance

Polymarket BTC 5-minute up/down trading bot. Real money. Solo build by Hamad (UAE-resident, Polymarket-permitted). Started 2026-05-04.

- **Architecture rationale (the why):** [`MASTERPLAN.md`](./MASTERPLAN.md)
- **Phase-by-phase execution (the what next):** [`RUNBOOK.md`](./RUNBOOK.md)
- **Visual master spec:** [`pdfs/BUILD_SPEC.pdf`](./pdfs/BUILD_SPEC.pdf) (24 pp)
- **Bootstrap doc:** [`pdfs/REQUIREMENTS.pdf`](./pdfs/REQUIREMENTS.pdf) (19 pp)
- **Bonereaper study (ARCHIVED, see decision #19):** [`pdfs/BONEREAPER_STUDY.pdf`](./pdfs/BONEREAPER_STUDY.pdf)
- **Locked decisions:** `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`
- **GitHub:** `https://github.com/FalconAEZ/polymarket-5m-bot` (private)

## Current phase

**Phase 0 — Foundations** (Phase 0 gate evidence will land at `runbooks/gate-evidence/phase-0.txt`; tag `phase-0-pass`).

Update this section on every gate pass. Don't skip phases.

## Locked decisions (do not relitigate)

These 19 decisions are locked. Source of truth: `memory/project_decisions.md`. Highlights — if a session pushes back on any of these, escalate; do not silently override.

1. UAE operator (Polymarket-permitted).
2. Dublin AWS Lightsail eu-west-1 (sub-5ms to CLOB).
3. NautilusTrader engine + py-clob-client.
4. **Anthropic API only** — no OpenAI fallback. Deterministic Tier-3 catches LLM failures.
5. **3 agents + meta-decider** (orderbook, oracle-gap, momentum, plus Sonnet meta).
6. Tier-3 deterministic = window-delta + oracle-gap, threshold ≥ 0.6 composite.
7. **Telegram bot via @BotFather** for operator alerts (no Discord).
8. GitHub private repo.
9. **$5 flat per trade for first 100 trades**, then fractional Kelly.
10. **$1,000 starting bankroll**.
11. Funder/Signer wallet separation from Phase 1.
12. Hardware wallet trigger = $2k bankroll (one rung past start).
13. Phase 1 order: derive creds → test sign → fund.
14. Anthropic budget: $50 → $150 (before Phase 4) → $300 (before Phase 6) → $200/mo sustained.
15. UTC everywhere — logs, DB, Obsidian daily notes.
16. LLM A/B in Phase 3; keep ensemble only if uplift ≥ 3pp over deterministic baseline.
17. **Polymarket gasless relayer** for all order submission (avoids public-mempool MEV).
18. Obsidian vault on laptop only; bot writes to `state/` in git.
19. **Bonereaper cloning study ABORTED 2026-05-06** (52.65% win-rate vs 60% gate). Phases B-G not designed; ensemble stays at 3 agents.

## Anti-vibe-coding rules — enforce without exception

These rules apply to anything touching trading logic, signing, money flow, or async control flow. Pure formatting / docstring / dependency-bump fixes are exempt.

1. **Design doc before code.** Every `src/*.py` is gated by a committed `design/<file>.md` first.
2. **Bug → failing test → fix → green.** Never patch a symptom. Test stays as a regression guard.
3. **3-fix rule.** Three iterations without resolution → stop and write `runbooks/incidents/<date>-<slug>.md`. Get user sign-off before touching code again.
4. **No phase advances** until the gate command exits 0 with output captured to `runbooks/gate-evidence/phase-N.txt` and tagged `phase-N-pass`.
5. **Every src file** ships with a one-paragraph header docstring (≥80 chars). CI rejects absent headers.
6. **Type hints required** on every Python function. `mypy --strict src/` is green from Phase 2 onward.
7. **External calls behind interfaces.** Production code never imports `polymarket_bot._paper`; tests never import `polymarket_bot._live`. Enforced via `import-linter`.
8. **No `TODO` / `FIXME` / `// hack`** in committed code under `src/`, `tests/`, `scripts/`. CI greps and rejects. Use GitHub issues with `icebox` label instead.
9. **Pinned deps + lockfile** committed. `uv.lock` always tracked. No floating versions.
10. **Stochastic inputs injected, not imported** — `Clock`, `LLMClient`, `RpcClient`, `RandomSource` all behind protocols so tests are deterministic.

Operating discipline (`pdfs/BUILD_SPEC.pdf` p. 22-23) extends these with 25 session/decision-logging/recovery rules. Highlights:

- **Session discipline:** one session = one phase task. Stop at 50% context. End with a 2-line note in `state/sessions/<date>.md`.
- **Manual checkpoints:** read every diff before accepting. Run gate commands yourself in your own terminal. Tag green gates by hand.
- **Anti-drift:** `src/` changed but no `design/` change in the same commit → reject. Gate criteria softened without an approved decision doc → revert and escalate.

## Common commands

```bash
make verify           # ruff + mypy --strict + pytest (mirrors CI)
make gate-0           # run Phase 0 gate (similar for gate-1..gate-6)
make study-A          # run study Phase A gate (the bonereaper audit; archived)
uv run pre-commit run --all-files
uv run python -u scripts/research/weekly_audit.py    # reusable wallet-audit pipeline
```

## Where things live

- `src/polymarket_bot/` — bot code (live + paper subpackages, separated by `import-linter`).
- `tests/` — `pytest` test modules.
- `design/` — design docs (rule #1 mandates these before code).
- `scripts/` — research and one-shot scripts (not part of the runtime bot).
- `runbooks/` — operator runbooks, gate scripts, incidents, postmortems, gate evidence.
- `pdfs/` — source-of-record PDFs + their builder scripts.
- `state/` (gitignored) — Obsidian vault root, bot-written notes, research caches.
- `references/` (gitignored) — read-only mining-only reference repos.
- `~/.claude/skills/agent-skills/` — official Polymarket Claude skills (clone of `Polymarket/agent-skills`).
- `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/` — durable cross-session memory.

## When something feels wrong

- **Drift suspected mid-task** → `git log --oneline -20`, then `git reset --hard <last-green-tag>` if needed. Write a postmortem at `runbooks/postmortems/drift-<date>.md`.
- **Open decision blocking progress** → don't decide silently. List the open decision, propose options, ask the user.
- **Same bug, second iteration not green** → on the third attempt, stop. Write `runbooks/incidents/<date>-<slug>.md`.
- **A locked decision feels wrong for what we're trying to do** → flag it as "Decision X needs revisit due to Y" with a written justification. Do not silently override.

## What this file is NOT

- It is not the runbook (that's `RUNBOOK.md`).
- It is not the architecture doc (that's `MASTERPLAN.md`).
- It is not the locked-decisions store (that's `memory/project_decisions.md`).
- It is the durable preferences + rules layer that every session reads.

---
title: Anti-vibe-coding rules
tags: [concept, discipline, rules]
---

# Anti-vibe-coding rules

> The 10 hard rules + 25 operating rules from `pdfs/BUILD_SPEC.pdf` p. 22-23. The discipline that prevents AI-assisted code from becoming a 100-bug firefight.

## The 10 hard rules (CLAUDE.md mirror)

1. **Design doc before code.** Every `src/*.py` is gated by a committed `design/<file>.md` first.
2. **Bug → failing test → fix → green.** Never patch a symptom. Test stays as a regression guard.
3. **3-fix rule.** Three iterations without resolution → stop and write `runbooks/incidents/<date>-<slug>.md`. Sign-off before iteration 4. See [[3-fix-rule]].
4. **No phase advances** until gate command exits 0. See [[gate-discipline]].
5. **Every src file** ships with a one-paragraph header docstring (≥80 chars). CI rejects absent headers.
6. **Type hints required** on every Python function. `mypy --strict src/` green from Phase 2.
7. **External calls behind interfaces.** Production never imports `_paper`; tests never import `_live`. Enforced via `import-linter`.
8. **No `TODO` / `FIXME` / `// hack`** in committed code under `src/`, `tests/`, `scripts/`. CI greps and rejects.
9. **Pinned deps + lockfile** committed. `uv.lock` always tracked.
10. **Stochastic inputs injected, not imported.** `Clock`, `LLMClient`, `RpcClient`, `RandomSource` all behind protocols.

## The 25 operating rules (highlights)

Full list in `pdfs/BUILD_SPEC.pdf` p. 22-23. Top hits:

### Session discipline (rules 1-5)
- One Claude Code session = one phase task. End the session when the task ends.
- Start each session by pasting the next task verbatim from RUNBOOK.md.
- Stop at 50% context use if no gate yet. Don't `/compact` mid-task.
- Cap focused session length at 4 hours.
- End every session with a 2-line note in `state/sessions/<date>.md`.

### Decision logging (rules 6-9)
- Code change → conventional-commits format (`feat:`, `fix:`, `refactor:`).
- Architecture change → memory file edit + commit in same PR.
- Bug → GitHub issue with reproduction, even if fixed in the same hour.
- "Maybe later" → GitHub issue with `icebox` label, never a TODO in code.

### Manual checkpoints (rules 10-13)
- Read every diff Claude proposes before accepting.
- Run gate commands yourself in your own terminal.
- Tag green gates by hand: `git tag phase-N-pass && git push --tags`.
- Before advancing a phase, re-read the previous checkpoint memory file.

### Anti-drift triggers (rules 19-22) ⭐ critical
- **Same bug, two iterations → stop, write `runbooks/incidents/<date>-<slug>.md` before iteration #3.**
- **`src/` changed but no `design/` change in same commit → reject.**
- **Gate criteria softened ("close enough", "we'll fix later", "the test is flaky") without an approved decision doc → revert, escalate.**
- **Any "let me just" or "I'll quickly" from Claude → freeze the conversation, ask why.**

### Recovery (rules 23-25)
- Drift suspected: `git log --oneline -20` first. Understand state before acting.
- Hard-reset to last green gate is your actual reset button: `git reset --hard phase-N-pass`.
- Post-recovery: write `runbooks/postmortems/drift-<date>.md`.

## Real cases from this project

- **Rule #21 (gate softening) held in Phase A.** When the bonereaper 7-day audit measured 52.65% vs the 60% gate, the gate was NOT lowered to fit. See [[phase-A-bonereaper]].
- **Rule #1 (design doc before code) held in Phase A.** `design/research/quick_audit.md` was committed before any audit code.
- **Rule #4 (gate-driven) held in Phase 0.** Phase 0 didn't get tagged until all 10 gate checks passed.
- **The user's discipline check on the 7-day window** ("why dont you check their win rate over 1 week ?") is not formally one of the 25 rules but embodies the spirit — when a measurement window doesn't match the gate window, push back before declaring a verdict.

## See also

- `pdfs/BUILD_SPEC.pdf` p. 22-23 — canonical source
- `CLAUDE.md` (project root) — durable preferences that mirror these rules
- [[3-fix-rule]] — deep dive on the iteration limit
- [[gate-discipline]] — deep dive on phase advancement
- [[../phases/README|Phase ledger]] — where the rules get applied

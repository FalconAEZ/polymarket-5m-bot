# Decision #18 revision — Obsidian vault notes are now git-tracked

> **Status:** revised 2026-05-07 evening, during the Mac → Windows
> migration. The original "laptop only" framing prevented operational
> notes from following the operator across machines. The runtime
> ephemeral state (parquet captures, log files, PID files) stays
> gitignored as before.

## What changed

**Original locked decision #18 (in
`~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`):**

> 18. Obsidian vault on laptop only; bot writes to `state/` in git.

**Revised:**

> 18. Obsidian vault markdown notes (`state/sessions/*.md`,
>     `state/postmortems/*.md`, `state/runbooks/*.md`) are git-tracked
>     so they survive a `git clone` on a new machine. Runtime state
>     (parquet captures, log files, pid files, `state/decisions/*.jsonl`
>     since Phase 4.5, the live `state-demo/`) follows its own rules
>     in `.gitignore`.

## Why

- Operator is migrating from Mac to Windows PC. The Mac's session
  notes contain hand-off context that the Windows session needs.
- These notes are small (markdown), text-only, no secrets.
- The runtime ephemeral state (.parquet, .log, .pid) was the actual
  reason for the original "laptop only" framing — those files ARE
  machine-specific and SHOULD stay out of git. Markdown notes never
  needed to be lumped in with them.

## What's still gitignored

- `state/feeds_health.json` — recreated by capture process per machine
- `state/capture.log`, `state/paper.log` — leak machine paths + are too noisy
- `state/capture.pid`, `state/paper.pid` — obviously machine-specific
- `state-demo/` — entire dir; demo is laptop-only
- `ticks/` — captured market data (parquet, too big)
- `trades.db` and SQLite ancillaries

## Continued tracked

- `state/sessions/*.md` — daily/weekly session hand-off notes
- `state/postmortems/*.md` — incident postmortems
- `state/runbooks/*.md` (and subdirs) — operator-authored procedural docs
- `state/decisions/*.jsonl` — Phase 4.5 decision log (was already tracked)
- `state/token_side_index.json` — bot-written cache; keeping it for now
  since it's small and reusable across machines (operator can override)

## Anti-vibe note

Locked decisions exist to prevent silent drift. This is a deliberate,
documented revision — the file you're reading IS the audit trail. If
a future session wants to revert, they should reference this doc and
explain why.

# `phase-prompts/` — engineered hand-off prompts, one per phase

When a Claude Code session approaches its context limit, the operator
writes a fresh, dense prompt to start the *next* session. These prompts
encode everything the new session needs to pick up cleanly:

- Branch + HEAD anchor
- Locked decisions to respect
- Anti-vibe rules carried forward
- Pre-flight checks
- Specific deliverables for the session
- Hard limits + spend ceilings
- Session boundary conditions (when to stop)

This folder is the audit trail. Each `.txt` was the actual first
message of a Claude Code session that landed a phase or sub-phase.

## What each file is

| File | When written | Used to launch | Result |
|---|---|---|---|
| `phase-1-prompt.txt` | 2026-05-06 | Phase 1A wallet & auth | tag `phase-1a-pass` @ `1537a18` |
| `phase-2-prompt.txt` | 2026-05-07 | Phase 2 capture (4-feed WS archive) | closed; capture ran 24/7 on Mac |
| `phase-2-analysis-prompt.txt` | 2026-05-07 | Phase 2.6 oracle behavior verification | gate green |
| `phase-3.3-prompt.txt` | 2026-05-07 | Phase 3.3 LLM A/B verdict run | tag `phase-3-pass` @ `3cd4a70` (verdict CUT) |
| `phase-4-prompt.txt` | 2026-05-07 | Phase 4 dev (paper runtime + sim validation) | closed @ `43f64af`; 14-day paper run kicked off |
| `phase-windows-resume-prompt.txt` | 2026-05-07 evening | Mac → Windows migration hand-off | superseded by [`RESUME-WINDOWS.md`](../RESUME-WINDOWS.md) at repo root, but kept here as the original artifact |
| `phase-5-prompt.txt` | 2026-05-07 late | Phase 5 VPS lockdown + runtime + latency check (5.1 → 5.4) | 5.1-5.4 GREEN @ `15d8e48` (Lightsail eu-west-1, **actual IP `108.132.51.116`** — the README originally listed `108.130.237.88` which was wrong). Latency gate revised per Option B in `runbooks/incidents/2026-05-07-clob-latency-gate-analysis.md`. |
| `phase-5.5-chunk2-prompt.txt` | 2026-05-07 evening | Phase 5.5 alerter daemon + halt-watcher + Telegram smoke (after Chunk 1 set up grafana-agent + bot-staging) | Phase 5.5 GREEN @ `6713b97` (operator-confirmed e2e Telegram + /halt smoke 19:31 UTC; bot restarted 19:32:54 UTC). |
| `phase-5.7-litestream-prompt.txt` | 2026-05-08 evening | Phase 5.7 close — wire litestream + capture gate evidence + tag `phase-5-pass` (after a 22h+ clean soak with criteria #1-#7 already passing) | _pending_ — at session-write time bot-staging had run 22h39m clean, 0 unhandled exceptions, 0 alerts queued, 0 decisions fired (signal-quiet validated). Optional step 7: start `design/spot_aware_strategy.md`. |

## Naming convention

`phase-<N>[<sub>]-<topic>-prompt.txt` — phase number, optional sub-phase
letter, optional topic descriptor. The Phase-4.5 dashboard work was
ad-hoc (driven by user feedback rather than a pre-written prompt) so
there's no `phase-4.5-prompt.txt`.

## How to use them when picking up a phase

1. Copy the contents of the relevant `.txt`
2. Open Claude Code in the project root
3. Paste as the first message
4. Claude reads the anchored docs (`CLAUDE.md`, `RUNBOOK.md`,
   `memory/MEMORY.md`, etc.) and proceeds with the deliverables

For a brand-new session unrelated to a specific phase, see
[`RESUME-WINDOWS.md`](../RESUME-WINDOWS.md) — the cross-machine pickup
prompt that's not tied to a phase number.

## Why this matters

Anti-vibe rule #1 says "design doc before code". These prompts are the
*session*-level equivalent: the explicit, written brief that prevents
the next session from drifting off-course. Keeping them in git makes
the session-to-session continuity reproducible — anyone can see how
each phase got framed.

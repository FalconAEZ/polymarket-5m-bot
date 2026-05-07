---
title: Phase ledger
tags: [moc, phases]
---

# Phase ledger

Chronological + status. Each phase has its own note when work begins; tags are pinned in git when the gate passes.

## Closed

- [[phase-A-bonereaper]] — research-stream pre-flight audit. **ABORT** at 60% gate. Tag `study-A-final`.
- [[phase-0-foundations]] — toolchain, accounts, repo. **GREEN**. Tag `phase-0-pass`.
- [[phase-1-wallet-auth|Phase 1A — Wallet & Auth (no-money)]] — wallet generation + L2 auth + signing-flow proof. **GREEN**. Tag `phase-1a-pass` at `1537a18`. Cost: $0. Funder=`0x512D…5d22`, Signer=`0x8d97…2B4A`. One incident → [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]].

## In design (next up)

- [[phase-2-data-plane]] — three async feeds (BTC spot, Chainlink BTC/USD oracle on Polygon, Polymarket 5m market) + 7-day capture + thesis-validation gate on Chainlink heartbeat behavior. Prompt staged at `~/Desktop/phase-2-prompt.txt`. Three sub-sessions: dev → 7-day capture → analysis.

## Not started (planned)

| # | Name | Cost (delta) | Touches money? |
|---|---|---|---|
| 3 | Backtest harness + LLM A/B | $15-50 (Anthropic) | No |
| 4 | Paper trading on live venue | $50-195 (Anthropic 24/7) | No (paper) |
| 5 | VPS provisioning (Dublin) | $5/mo recurring | No |
| **1B** | **Wallet funding + first gasless order** | **$5 gas + $50 USDC** | **Yes — first real money** |
| 6 | Live with kill-switches | $1,000 capital + ~$50-195 LLM | Yes — full live |
| 7 | Scale + maker rebates | bankroll-driven | Yes |
| 8 | Hardening (ongoing) | TBD | Yes |

The 1B insertion at the head of Phase 6 is per [[../decisions/README#decision-20|decision #20]]: paper-mode through Phase 4 doesn't need a funded wallet, so funding is deferred until the discipline of paper-mode validation has shown the strategy works.

## Cross-cutting notes

- All gates use `bash runbooks/gates/phase-N.sh` exiting 0; evidence captured to `runbooks/gate-evidence/phase-N.txt`.
- Tags `phase-N-pass` are pushed to GitHub when the gate goes green.
- Memory checkpoint written at `~/.claude/projects/.../memory/checkpoint_phase_N.md` after each gate pass.
- Anti-vibe rule #4 is religious: **no phase advance without the gate command exiting 0 in the operator's terminal.**

## Related

- [[../runbooks/README|Operational runbooks]]
- [[../decisions/README|Locked decisions]]
- `RUNBOOK.md` (project root) — the canonical execution document

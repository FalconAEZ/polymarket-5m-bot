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

## In progress

- [[phase-5-vps]] — VPS provisioning + 24h staging on AWS Lightsail Dublin (`5m-Polymarket-bot`, `108.132.51.116`). **5.1 GREEN** (SSH lockdown, port 2222 key-only, no root, UFW + console firewall). 5.2-5.7 next session: runtime install → CLOB latency gate → systemd units → monitoring (incl. tg-alerter) → Signer key transfer → 24h staging.

## Closed in flight (no tag pushed yet)

- [[phase-2-data-plane]] — Phase 2 dev tasks 2.0-2.4b closed 2026-05-07 evening; capture ran on Mac. Decision #21 reduced the 7-day variance gate based on observed 33s Chainlink heartbeat (vs MASTERPLAN's claimed 60s). Phase 2 dev complete; gate runs after the data accumulates. _(See `state/sessions/2026-05-07-evening.md`.)_
- Phase 3 (LLM A/B) — closed 2026-05-07 at `3cd4a70`, tag `phase-3-pass`. OD-5 verdict: CUT ensemble (latency + cost gates fail decision #16). Spend: $0.405.
- Phase 4 (paper runtime) — closed 2026-05-07 at `43f64af`. 14-day Mac run died on laptop sleep; will restart on VPS as part of Phase 5.7 staging.
- Phase 4.5 (operations dashboard) — closed 2026-05-07 evening at `c1ff257`. Not yet tagged.

## Not started (planned)

| # | Name | Cost (delta) | Touches money? |
|---|---|---|---|
| **1B** | **Wallet funding + first gasless order** | **$5 gas + $50 USDC** | **Yes — first real money** |
| 6 | Live with kill-switches | $1,000 capital + ~$50-195 LLM | Yes — full live |
| 7 | Scale + maker rebates | bankroll-driven | Yes |
| 8 | Hardening / ensemble revisit | TBD | Yes |

(Phase 5 was previously listed as "not started" with $5/mo budget. **Now in progress with $24/mo recurring** — the 2vCPU/4GB plan is needed, the $5 plan would bottleneck on RAM. Locked decision #14's $200/mo sustained-OPEX still covers it comfortably.)

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

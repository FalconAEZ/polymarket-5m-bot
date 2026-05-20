---
date: 2026-05-20
session: phase-S-session-5-edges-shipped
branch: claude/phase-S-market-maker
tags: [session-note, phase-S, edges-shipped, polymarket-docs]
---

# Phase S Session 5 (continued) — 4 audit edges shipped + Polymarket docs digested

## What shipped this session

Five commits ahead of S.5 dev portion:

| Commit | What |
|---|---|
| `09bda7b` | Deep edge audit (527 lines, 9 datasets mined, 3 top edges identified) |
| `eb726ab` | **Edge 1**: per-tier-side blocklist (50-70%×DOWN, 15-30%×UP, 30-50%×UP) |
| `c729b28` | **Edge 2**: late-window 2x size multiplier (last 60s) |
| `44caf8e` | **Edge 3**: pct-bankroll caps + `MM_CAPS_MODE` migration flag |
| `22ccab4` | **Edge 4 prep**: `metadata_getter` merges MMD label into mm-decisions log |

**809 tests passing** (+24 from baseline 785). mypy --strict + ruff + import-linter all green.

## Audit headline numbers (n=21,633 fresh weekly bonereaper fills)

| Cell | $/tr | n | Verdict |
|---|---:|---:|---|
| `<15% × LATE × DOWN` | **+$12.01** | 295 | top cell — $3.5k weekly gross |
| `85-100% × LATE × UP` | +$9.46 | 204 | strong |
| `50-70% × DOWN` (all) | **-$0.76** | 3,366 | **BIGGEST LEAK -$2,563/wk** |
| `15-30% × UP` (all) | -$0.61 | 1,345 | leak -$820/wk |

## Polymarket official docs digested (6 URLs, end-of-session)

Critical findings that informed S.6 prompt:

### Maker fees CONFIRMED zero + Maker Rebates Program exists
> "Makers pay zero fees. Takers absorb small fees that fund the Maker Rebates Program (daily USDC payouts)."

Our backtest math was correct. Plus separate rebate income on top — S.6 P2 verifies whether BTC 5m has `feesEnabled=true`.

### Liquidity Rewards: BTC 5m NOT currently eligible
April 2026 sports/esports only. Formula `S = ((v-s)/v)² × b`, single-sided ÷ 3.0, daily midnight UTC payout, $1 minimum. "Additional categories will be added soon" — monitor.

### CTF split/merge/redeem — MMB has a CRITICAL GAP
Currently `PayoutResolver` computes realized PnL on paper. **But USDC.e doesn't auto-appear in Funder** — we have to invoke `redeemPositions()` on the CTF contract after window resolves. Without this MMB's internal bankroll counter says "+$X" but the wallet stays flat.

**S.6 hard requirement (Edge E2):** add post-resolution redemption step.

### Three approvals (not one) for full functionality
- pUSD → CTF (for splits — we don't split currently)
- CTF → Exchange (we have this — USDC.e → CTF Exchange)
- CTF → Neg-Risk Exchange (irrelevant — BTC 5m is standard CTF)

For S.5 first deploy, only the second matters. The other two come if we ever add split mechanics.

### WebSocket subscriptions recommended over polling
Our `_book_loop_one_token` polls at 1s. WS would reduce book staleness to <50ms. Candidate **Edge E1** for S.6 if Day-7 passes.

### pUSD vs USDC.e naming question
Polymarket inventory docs use `pUSD` (`0xC011a7E1...`). S.1.1 uses USDC.e (`0x2791Bca1...`). **S.6 P1 verifies** before live deploy.

## Branch state at session end

```
22ccab4 (HEAD) feat(phase-S): Edge 4 prep — metadata_getter
44caf8e         feat(phase-S): Edge 3 — pct-bankroll caps + MM_CAPS_MODE flag
c729b28         feat(phase-S): Edge 2 — late-window size multiplier
eb726ab         feat(phase-S): Edge 1 — per-tier-side blocklist
09bda7b         docs(phase-S): deep edge audit — 3 top edges
0d23d77         feat(phase-S): G11 empirical probes + OPERATOR_HANDOFF_PHASE_S
... [earlier S.1-S.5 dev commits] ...
9516f39         (base) fix(dashboard): honor PMB_STARTING_BANKROLL
```

Pushed to origin. VPS pulled. bot-mm.service installed but disabled. Halt sentinel in place.

## What's NEXT

[phase-prompts/phase-S-session-6-deploy-and-soak.md](../../phase-prompts/phase-S-session-6-deploy-and-soak.md) — full 6-phase plan:

- **Phase 6A** pre-deploy verification (Polymarket docs follow-ups, allowance, G11 probes)
- **Phase 6B** first-fire (operator-supervised, 5 minute hands-on watch)
- **Phase 6C** Day-1 soak (24h hands-off)
- **Phase 6D** Day-7 audit + S.5 → S.6 gate
- **Phase 6E** new edges (WS book updates, redeemPositions, rebates accounting)

## Realistic expected outcome at Day-7

| Scenario | Day-7 PnL | % weekly on $1k |
|---|---:|---:|
| Most likely | +$30 to +$200 | 3-20% |
| Best case | +$400-$700 | 40-70% |
| Marginal (extend soak) | -$30 to +$30 | ~breakeven |
| Failure (postmortem) | < -$50 | gate fail |

10x bonereaper rate ($110/wk) achievable in the likely range. 100% weekly is best-case ONLY.

After Day-7 PASS + `MM_CAPS_MODE=pct_bankroll` flip + 3 weeks compounding → enters "10x bonereaper per week" territory per audit §5.

## Context note

Session ended at ~89% context, prompting the comprehensive next-session prompt + this vault note. All deliverables committed before close.

# Relaunch brief — Polymarket, July 2026

> Companion to [runbooks/postmortems/2026-07-23-saga-postmortem.md](runbooks/postmortems/2026-07-23-saga-postmortem.md).
> Research compiled 2026-07-23 from three parallel deep-research passes (platform timeline, strategy
> landscape, small-bankroll claims). Sources dated + linked inline. Nothing here is financial advice —
> Claude is not a licensed advisor; this is engineering and probability work on your own system.

## 1. The honest answer on "$300 → $10k in 1 week"

That is a 33× return. The documented ways it has happened on Polymarket:

- **All-in compounding streaks** — ascetic0x ($12→$104k, Nov 2025–Jan 2026, BTC 15-min markets,
  16 consecutive doubles ≈ 0.0015% probability at coin-flip odds; partially verified). Mayuravarma
  ($5k→$3.8M in a month on sports favorites — then **lost all $3.8M in one week** and deleted his
  account; fully verified on-chain, both directions).
- **Marketing fabrications** — WSJ (June 2026): ~70% of 1,105 reviewed influencer "win" videos were
  staged on clone websites (e.g. `poiymarket.com`), creators paid $2–3k/month; $900k of claimed
  wins would actually have lost $166k. The "$300→$400k AI agent" Medium story: zero receipts, author
  sells RPC infrastructure.
- **Base rates** (Dune on-chain study, Apr 2026): **84.1% of 2.5M wallets are net losers; 0.32% ever
  made $10k lifetime**; most winner profit accrues to a tiny set of automated market-making
  accounts. Academic work (222M trades): *forecasting accuracy alone yields negative returns —
  execution quality is the edge.*

The math for 33×-in-a-week without a fabricated screenshot: ~5 consecutive all-in doubles. At a
genuine 60% edge per double (better than anything this project ever measured live), P(success) ≈
7.8%, P(ruin) ≈ 92%. At the ~52% this market actually gave your bots, ≈ 3.6%. **Your own saga
already ran this experiment three times** — Kelly/multifire compounding was, in your own audit's
words, "the mechanism behind every wipeout." A $300 stake pursuing 33×/week is a lottery ticket,
and the losses cluster exactly like May 25–26 did.

What realistic success looks like instead: verified small operators grind **1–3% of deployed volume**
in niches (ColdMath: $74k profit on $4.69M volume = 1.58% margin; weather-model laddering). Growth
comes from compounding a *positive* edge slowly with a drawdown floor — the thing decision #9/#10
originally encoded.

## 2. What actually works on Polymarket in mid-2026 (evidence-ranked)

| # | Strategy family | Verdict for you |
|---|---|---|
| 1 | **Maker-side fast markets** — two-sided quoting, 20% taker-fee rebates + liquidity rewards; where the 55–62% bot volume lives | The surviving fast-market edge. Your **MMB is already built and gate-passed** (parked at `origin/claude/phase-S-market-maker`). Needs re-validation against Fee V2 + CLOB V2 and an adverse-selection model. Professional game; $300 is too small to matter — viable from ~$1k+ as a learning deployment. |
| 2 | **Niche data markets** (weather et al.) — model-driven laddering of 3–10¢ longshots against slow repricing after NOAA/GFS/ECMWF runs | Best-documented *retail-scale* edge of 2026 (verified wallets: automatedAItradingbot ~$88.5k since Jan 2025; gopfan2 ~$2M lifetime). Objective resolution, low competition, real grind economics. Fits your build-audit-iterate machine. |
| 3 | **NegRisk / combinatorial arb** — buy all outcomes when Σ < $1, conversion inconsistencies | Verified ~$40M historical bot profit (arXiv); 2026 NBA study confirms mispricings persist but are "strictly retail scale." Low capacity, fits small bankroll, execution-heavy. |
| 4 | **Cross-platform arb** (Kalshi↔Polymarket, perps hedging) | Mechanically real (0.5–2% spreads) but **Kalshi is US-KYC — not accessible from UAE**. Skip. |
| 5 | **News-latency, whale-copying, points farming** | No independently verified 2026 P&L for news bots (all vendor marketing); copy-trading tools verified but copier profitability isn't (plus the Polycule copy-bot hack, −$230k); airdrop farming now collapses into #1 (fees made churn negative-EV; token confirmed, no snapshot date). |
| 6 | **Taker-directional 5-min BTC** (what you played) | **Dead at your tier, by your own measurements**: fees ~3.5% of notional at 50¢, <150ms repricing (0/13 gaps), breakeven WR ≈72% at your entry mix, bots are your counterparties. The Jan 2026 fee was designed to kill this. Do not relaunch it. |

Platform facts that constrain any relaunch: taker fees on all crypto markets (coefficient ~0.07,
peak at 50¢, →0 at extremes; makers pay none and receive 20% rebates); resolution = Chainlink Data
Streams + Automation; **CLOB V2 hard cutover Apr 28** (pUSD collateral, new order struct — V1
`py-clob-client` archived 05-25, all old order code must migrate); rate limits now 200 orders/s
sustained; Polymarket is standing up an in-house MM desk (CoinDesk, Dec 2025).

## 3. If you relaunch: the governance that survives contact with drawdown

Your Hermes vault already contains the right rules (`vault/_Audits/2026-05-26/200-restart-playbook.md`).
Promote them from "playbook we ignored" to hard, mechanical gates:

1. **Bankroll**: start ≤ $500; the bot halts (not you) at −25%; floor recomputes only on deposits.
2. **Sizing**: flat bets ≤ 5% of bankroll until **n≥300 live settles**. Kelly (≤0.10×) unlocks only
   after live WR + $/trade + max-DD gates pass on that sample — the Phase 5 gate you wrote on
   June 2 and never got to use.
3. **Profit ladder**: auto-withdraw 50% of gains at +50%, +100%, +200%. A peak you didn't bank is
   variance, not profit — May 25 is the proof.
4. **Change control**: max 2 restarts/day; zero intraday config edits; strategy/sizing changes need
   ≥5 days of soak; observability and bug fixes ship freely. One strategy at a time.
5. **The 5 anti-patterns stay armed** (`feedback_operator_anti_patterns_2026_05_26.md`) — the
   assistant's job is to surface them *before* executing, per your own standing feedback. Decision
   #24-style blanket overrides get a 24h cooling-off before taking effect.
6. **Settlement truth**: the bot's win/loss source must be the venue's oracle (Chainlink/Gamma),
   never a proxy feed. Regression test pinned to the May 26 bug.

## 4. The upgraded prompt

Your original ask, rebuilt. Paste this (or `cat` this section) into a fresh Claude Code session in
this directory. It front-loads ground truth, forces evidence over recollection, scopes one mission
per session, and encodes the guardrails above.

```text
ROLE
You are my quant/engineering partner on the Polymarket project. Rigor over speed; evidence over
vibes; push back honestly when I ask for things my own data contradicts (this is standing,
written feedback — feedback_honest_pushback.md).

GROUND TRUTH — read before doing anything
1. runbooks/postmortems/2026-07-23-saga-postmortem.md   (what actually happened, money truth table)
2. RELAUNCH_BRIEF_2026-07-23.md                          (strategy landscape July 2026 + guardrails)
3. ~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/MEMORY.md   (96-file archive index;
   locked decisions #1–24, anti-patterns, every checkpoint)
4. Repos: ~/Desktop/recovered-polymarket-bots/{polymarket-5m-bot, polymarket-hermes-bot}
   — key branches: claude/phase-S-market-maker (built MMB), claude/phase-T-directional-revival
   (soak audit PDF), feature/aggressive-override-2026-05-26 (June forensics + verdict docs).
Established verdicts are closed unless NEW MEASUREMENT reopens them: taker-directional BTC 5m is
dead at our tier (sub-second-latency-verdict.md); Kelly/multifire is leverage, not edge.

MISSION — exactly ONE per session, stated back to me before work starts
  A. WALLET AUDIT: reconstruct the real-money ledger from on-chain/API data (data-api activity,
     positions, value; UI export). Deliver: final net P&L, residual balance, unredeemed positions.
  B. STRATEGY RE-VALIDATION: take ONE strategy family from the brief (MMB re-validation on Fee V2 +
     CLOB V2 / weather laddering / NegRisk arb), design-doc first, then paper-only harness with the
     same audit pipeline we already built. Deliver: go/no-go against a pre-registered gate.
  C. RELAUNCH ENGINEERING: only after a B-mission gate passes — migrate execution to the V2 stack
     (pUSD, new order struct, current SDK), wire the runner-level daily-loss guard (L.5) BEFORE
     first live order, Telegram alerts, halt sentinel.

EVIDENCE RULES
- Every numeric claim carries a source (file path, API call, or dated URL). Real-money vs paper is
  labeled on every figure. UTC everywhere. If data is missing, say "unknown" — never interpolate.

GUARDRAILS (hard; surface conflicts, don't silently comply)
- No live order without: passing gate evidence file + funded-wallet verification + L.5 guard active
  + my explicit written go in that session.
- Sizing: flat ≤5% bankroll; Kelly locked behind the n≥300 live gate. No multifire. No stop-loss
  overlays on hold-to-resolution strategies (June 2 evidence).
- Auto-halt at −25% bankroll; profit ladder 50% off at +50/+100/+200%.
- Max 2 restarts/day; no intraday config edits; strategy changes need ≥5 days soak.
- If I ask to loosen filters mid-drawdown, disable loss limits, or "make it feel alive": quote
  anti-pattern #1/#2 back to me, require a written override, and apply a 24h cooling-off.
- You are not a licensed financial advisor; sizing and deposit decisions are mine alone.

ANTI-GOALS
- No plan whose success case is "33x in a week." No reopening closed verdicts without new
  measurement. No second bot while one is live. No trading logic outside the design-doc→test→gate
  pipeline.

DELIVERABLE FORMAT
End every session with: (1) what changed (files/commits), (2) what the evidence now says, (3) the
single next mission, (4) a 2-line note in state/sessions/<date>.md.
```

## 5. Locked-decision conflicts to resolve (flagging, not overriding — per CLAUDE.md)

- A $300 restart conflicts with decision **#10** ($1,000 starting bankroll). Options: revise #10
  with a written decision doc, or fund to $500+ and start at playbook scale.
- The 33×/week goal conflicts with **#9** ($5 flat first 100 trades) and with the lapsed **#24**'s
  own postmortem. Recommend formally retiring #24.
- Decision **#2/#3** (Dublin VPS, NautilusTrader/py-clob-client) need refresh regardless: VPS is
  down/possibly deleted, and the V1 client was archived 2026-05-25 → any relaunch is a V2 migration.

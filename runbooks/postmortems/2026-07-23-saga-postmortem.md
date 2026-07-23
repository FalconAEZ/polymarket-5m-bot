# Postmortem — the full Polymarket saga (2026-05-04 → 2026-06-02+)

> Written 2026-07-23 by Claude Code (forensic session), from: the old memory archive at
> `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/` (96 files, survives to this day),
> both GitHub repos (`FalconAEZ/polymarket-5m-bot`, pushed 2026-05-23; `FalconAEZ/polymarket-hermes-bot`,
> pushed 2026-06-02), the Hermes vault audit docs on branch `feature/aggressive-override-2026-05-26`,
> and Polymarket's public data API. Both repos re-cloned to `~/Desktop/recovered-polymarket-bots/`.

## The single most important correction

**The $1.5k–2k peak on May 25 was not this repo's bot.** It was **Hermes** — a second bot built
2026-05-24 in `~/Desktop/PolyMarket-Hermes/` (now deleted locally, recovered from GitHub) after the
0xRicker thread, with the anti-vibe-coding rules explicitly dropped by operator override.

- The **5m bot (this repo) never traded real money.** Everything it "lost" (Phase K's $2,235→$1,095,
  Phase T's $7,365→$323) was **staging/paper bankroll replay**. Real dollars: $0.
- **Hermes traded real money**: $363 → ~$1,600 intraday peak (2026-05-25 ~17:00 UTC) → **$3.42**
  (2026-05-26 12:36 UTC). That is the "$1.5k we lost."
- June 2 revival: $1,006.13 live → aggressive-mode losses → $721.62 clean redeploy → tail unknown
  (no records after ~2026-06-03; VPS now unreachable).

## Money truth table

| Cycle | Dates | Start → Peak → End | Real? | Evidence |
|---|---|---|---|---|
| 5m bot, Phase K soak | 05-14→16 | $1,000 → $2,235 → $1,095 | Paper (replay) | `checkpoint_phase_K.md` |
| 5m bot, Phase T soak | 05-20→23 | $3,000 → $7,365 → $323 → $803 | Paper (staging) | `checkpoint_phase_T_session_1_close.md`, PHASE_T_LIVE_SOAK_AUDIT.pdf (in repo branch `claude/phase-T-directional-revival`) |
| Hermes run 1 | 05-25→26 | $363 → ~$1,600 → **$3.42** (−99.06%) | **REAL** | `project_hermes_first_run_postmortem_2026_05_26.md` |
| Hermes run 2 (decision #24 override) | 05-26→~28 | $277 → floor trip **$67.15** | **REAL** | `checkpoint_hermes_tfi_live.md`, `project_decisions.md` #24 |
| Hermes run 3 (tfi + aggressive) | 06-02 | $1,006 → $929 → ~$600 exit call → $721.62 clean redeploy → **unknown tail** | **REAL** | `checkpoint_hermes_tfi_live.md` (all four dated updates) |

On-chain lifetime marker as of 2026-06-02: **$6,351 total redeemed, net −$859** for the May wallet
cycle (`project_hermes_tfi_edge_arena.md`). Documented realized damage across cycles ≈ **−$850 to
−$1,150 real dollars** plus the unknown post-June-2 tail. The "lost $1.5k" framing counts the
unrealized May 25 peak — real pain, but the cash loss is smaller, and that distinction matters for
sizing the next attempt.

## Timeline (compressed)

- **05-04 → 05-13** — 5m bot built with full discipline. Phase G deep audit (05-13, n=635 paper
  fires): **50.0% WR, −$18.96 — zero edge.** This result never changed; everything after was
  variance around it.
- **05-14 → 05-17** — Kelly 0.15× + bankroll replay = 2.3× sizing. Paper bankroll $1k→$2,235→$1,095
  (max DD −$1,294 in 18h). Halted 05-17 at $673. Phase N forensic. Full revert (Phase P).
- **05-20 → 05-23** — Phase T "directional revival" at $3k paper: 1,226 fires, **WR 60.5%, net
  −$2,938** ($/trade −$2.40 — *winning often ≠ making money*; q-asymmetry + fees). CHOPPY regime
  alone bled −$3,708; a daily-loss guard existed in code but wasn't wired for the running strategy.
- **05-24** — Operator override: pivot to Hermes stack from the 0xRicker thread; anti-vibe rules
  dropped for the new repo. Claude's pushback (build audit-first, keep discipline) was overridden —
  documented in `checkpoint_phase_UVW_design.md`.
- **05-25** — Hermes live at 13:35 UTC with $363. Intraday peak ~$1,600. 11 restarts. On-chain day-1
  net +$570.
- **05-25 → 05-26** — Collapse to $3.42 in ~22h: 320 trades, 32+ restarts, 31 .env edits, 60+ manual
  halts; the daily-loss kill was disabled at 12:19 UTC; $258 → $3.42 in the final 17 minutes.
- **05-26** — Decision #24: written operator override suspending the 5 anti-patterns and decision
  #19, "full bankroll loss possible within 24h" acknowledged; $277 restart; floor $138.50; floor
  later tripped at $67.15 → override lapsed.
- **06-01** — Honest forensics on the repo: (a) the live bot had been firing at p≈0.50 — a
  **structurally inverted phantom edge** (`vault/_Audits/2026-06-01/full-history-unified.md`);
  (b) **latency probe: 0/13 exploitable gaps, books repriced <150ms** —
  `vault/_Audits/2026-06-01/sub-second-latency-verdict.md` ends: *"This market is efficient against
  us. STOP pursuing BTC 5m directional/lag trading."*
- **06-02** — The one real positive: 7-arm paper arena found the **TFI flow-gate aligned strategy**
  (76% paper WR, best return/drawdown; live check 71.9% ≈ paper — no fill haircut). Flipped live
  with $1,006. Then an aggressive override (Kelly + multifire + stop-loss, dissent logged) lost
  −$70 in 20 min; protective halt; operator resumed; full-exit call at ~$600; corrected verdict:
  **the signal was fine — the stop-loss/multifire overlay caused the loss; but even clean it's
  ~breakeven, because avg win +$7.86 vs avg loss −$20.58 ⇒ breakeven WR ≈ 72.4%.** Clean redeploy
  on $721.62. Records end ~06-03.

## Root causes, ranked (what lost the money)

1. **No durable edge in the chosen game.** BTC 5-min up/down is the most bot-saturated arena on
   Polymarket (bots = 55–62% of fast-market volume, Dune study Apr 2026). Taker fees (live on 5-min
   from its Feb 2026 launch; crypto coefficient 0.07 ⇒ **~3.5% of notional at 50¢ odds**) are
   engineered to kill exactly the taker-directional style both bots played. Your own measurements
   agree: Phase G 50.0% WR; 7-day bonereaper audit 52.65% vs 60% gate; June latency probe 0/13 gaps.
   At your entry-price mix the arithmetic needed ~72% WR to break even; best sustained real result
   was ~66–72%. Thin-to-negative, before variance.
2. **The outcome-detection bug** (Hermes run 1, ~55% of that loss): win/loss judged by Binance
   close-vs-open while Polymarket settles on **Chainlink Data Streams**. The bot logged phantom WINs
   (e.g. +$2,616 logged vs −$222 on-chain), and every config decision that day was tuned on poisoned
   data. Fix shipped 05-26 12:10 UTC — after the bankroll was gone.
3. **Leverage stacked at the worst moments.** Kelly sizing, multifire/DCA stacking, and (June) a
   stop-loss overlay that whipsawed winners. Every single wipeout in the saga has one of these in
   the room: Phase K DD (Kelly 0.15×+replay), Phase T (−$2.40/tr at 60.5% WR), Hermes run 1
   (multifire into reversals), June 2 aggressive arm (−$464 attribution; paper aggro arm −$8,397).
   The arena's conclusion was exact: **"Kelly = leverage, not edge; the mechanism behind every
   wipeout."**
4. **Operator process collapse under drawdown** — documented as 5 anti-patterns
   (`feedback_operator_anti_patterns_2026_05_26.md`): "feels dead → loosen filters," restart storms
   that reset loss-limit accounting (32+ in 36h), disabling the daily-loss kill during the final
   bleed, manual lifetime.json resets, sample-of-1 confidence (9 features shipped on 1 day of data,
   5 reverted same session). Decision #24 then made the removal of safety rails official.
5. **Competitive regime shift as context, not cause.** Checked hard for the May 20–June 10 window:
   **no fee, oracle, tick, or rewards change**. What did change: CLOB V2 shakeout (V1 py-clob-client
   archived 05-25), three matching-engine restarts (05-20/22/29), June 1 rate limits raised to
   200/s sustained, and a copycat influx after the April Bonereaper teardown went public — all
   raising the bar for latency-tier players while volumes softened.

## What capped the upside (why you didn't win more)

- **Wrong side of the fee flow.** You paid taker fees into the pool; 20% of them were being recycled
  to makers. Your own Phase S market-maker bot (MMB) — built, tested, backtest gate PASSED
  (+$1,586 sim over 7d) — was **parked on 2026-05-20 and never deployed**
  (`origin/claude/phase-S-market-maker` @ 8fe6007).
- **No profit-taking ladder.** The $200-restart playbook (in the Hermes vault) mandated taking 50%
  off at +50%/+100%/+200%. At +340% intraday on May 25, nothing was banked. Same pattern in Phase T
  paper ($7,365 peak, ended $803) — peaks were never converted to a higher floor.
- **The validated finding was abandoned at the exact moment it validated.** The TFI-aligned arm was
  the only strategy that matched paper→live (71.9% vs 72.3%). It got 6 settles and +$20.96 of live
  runway before being buried under the aggressive overlay the same day.
- **Attention went to the crowded market.** The niches where verified small operators actually grind
  profits (weather/data markets, NegRisk arb, maker rewards) were never explored; 100% of effort
  went to the market with the most professional competition.

## What went right (keep these)

The discipline machine itself: design-docs, gates, honest audits that found the truth every time
(Phase G, Phase N, the June forensics), the memory system (it's why this postmortem exists), the
MMD CHOPPY-abstain finding (counterfactual +$770 vs −$2,938), the L.5 daily-loss guard design, the
latency-probe methodology, and pushback that was recorded even when overridden.

## Open action items (operator)

1. **Check the live wallet for residual funds.** The June Safe (`0x16510D…16cEA` in notes) may still
   hold USDC + unredeemed positions — the June 2 note says the ~$600 withdrawal was **never
   confirmed executed**, and a $721.62 clean redeploy with a $500 floor was the last known state.
   Log in at polymarket.com (email login) → portfolio. The planned D-002 Safe (`0x0596Cfb3…aEF`)
   shows **$0 and zero history** on the public API — the live account was a different one.
2. **Check AWS Lightsail billing.** The Dublin VPS no longer answers on 108.132.51.116:2222 — but
   unreachable ≠ deleted. If the instance still exists, it may still be billing monthly. Delete it
   (and any Litestream S3 bucket) if the project stays closed.
3. **Treat old keys as burned.** D-002 already flagged old VPS images as possible key exposure;
   `~/secrets/polymarket-5m/{funder,signer}.age` are for the abandoned empty wallets. Never reuse.
4. Local recovery is done: both repos at `~/Desktop/recovered-polymarket-bots/` (all branches: the
   Phase T audit PDF, the MMB, and the June Hermes forensics are in the branches, not main).

# Phase S — Session 6 prompt — VPS deploy + first-fire + soak + new edges

**Authored:** 2026-05-20 (end of Session 5 dev at 89% context).
**Branch:** `claude/phase-S-market-maker` @ `22ccab4`.
**Pre-conditions:** all 4 audit edges shipped + tested + pushed. VPS at `22ccab4`. Bot-mm.service installed + DISABLED. Halt sentinel in place.
**Risk class:** **FIRST REAL MONEY.** Live deploy in this session if pre-flight passes. Operator-supervised first fire.
**Bankroll:** $1,000 (decision #10 baseline; operator confirmed start-with-$1k 2026-05-20).

---

## What you're stepping into

10 commits ahead of base `9516f39`. Phase S has 4 implemented edges from the 2026-05-20 audit:

1. **Per-tier-side blocklist** — eliminates ~$3.7k weekly leak at bonereaper scale
2. **Late-window size multiplier** (2x in last 60s) — captures 0-30s × DOWN at +$12.09/tr
3. **Pct-bankroll caps schema** with `MM_CAPS_MODE` flag (defaults to `fixed_usd` for backward-compat first deploy)
4. **MMD label in decision log** (Edge 4 prep — metadata_getter wired for Day-7 audit)

809 tests passing. Mypy strict + ruff + import-linter all clean.

**Required reading (before any action):**
1. [runbooks/research/mmb-deep-edge-audit-2026-05-20.md](../runbooks/research/mmb-deep-edge-audit-2026-05-20.md) — empirical basis for all 4 edges
2. [state/sessions/2026-05-20-phase-S-session-5-edges-shipped.md](../state/sessions/2026-05-20-phase-S-session-5-edges-shipped.md) — what happened last session
3. [runbooks/OPERATOR_HANDOFF_PHASE_S.md](../runbooks/OPERATOR_HANDOFF_PHASE_S.md) — operator pre-deploy steps
4. [scripts/run_mm_live.py](../scripts/run_mm_live.py) — live entrypoint with all 4 preflight gates
5. [memory/checkpoint_phase_S_session_5.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_5.md) — what's locked

---

## §1. Polymarket-official MM intel (2026-05-20 web fetch)

Six docs scraped from `docs.polymarket.com/market-makers/*` + `/market-data/*` at end of S.5. Findings beyond what S.1.1 captured:

### 1.1 Fee structure — CONFIRMED zero maker, with REBATES

> "Makers pay zero fees. Takers absorb small fees that fund the **Maker Rebates Program** (daily USDC payouts). Geopolitical and world events markets are entirely fee-free. Fee-enabled markets flag `feesEnabled: true`."

**Implication for MMB:** our backtest math (zero maker fee assumption) was CORRECT. PLUS there's a separate **Maker Rebates Program** that pays daily USDC to makers on fee-enabled markets. Funded by taker fees, not the same as liquidity rewards.

**S.6 action:** check BTC 5m markets for `feesEnabled` flag at start of session. If true, MMB earns rebates AS WELL AS spread capture — backtest +$1,586/wk understates real PnL. If false, BTC 5m is fully fee-free and rebates don't apply.

Source: https://docs.polymarket.com/market-makers/trading

### 1.2 Liquidity Rewards — NOT eligible for BTC 5m (yet)

> "April 2026 sports and esports markets explicitly. BTC 5-minute directional markets aren't mentioned and likely fall outside current reward pools, though 'additional categories will be added soon.'"

Formula: `S(v,s) = ((v-s)/v)² · b`, sampled every minute, single-sided ÷ 3.0, outside [0.10, 0.90] midpoint requires two-sided. Distributed daily at midnight UTC, $1 minimum payout.

**Implication for MMB:** no liquidity rewards on BTC 5m TODAY. **But monitor: if BTC 5m enters the rewards program, MMB's two-sided ladder design picks up rewards automatically + the formula favors tight spreads.** Could materially boost EV.

**S.6 action:** add a daily check on `/sampling-markets` endpoint to detect when BTC 5m enters the rewards program. Alert via Telegram if found.

Source: https://docs.polymarket.com/market-makers/liquidity-rewards

### 1.3 CTF split/merge/redeem — MMB needs `redeemPositions` post-window-close

> "Each winning token is worth $1 — losing tokens redeem for $0... The workflow involves canceling open orders, awaiting resolution completion, **redeeming payouts**, and merging remaining token pairs."

> "Split converts pUSD into equal amounts of YES and NO tokens — creating the inventory you need to quote both sides."

**Implication for MMB — CRITICAL GAP:** MMB's current design holds shares to window resolution + the `PayoutResolver` computes realized PnL on paper. **But the actual USDC.e doesn't automatically appear in the Funder wallet** — we have to invoke `redeemPositions()` on the CTF contract to withdraw winning shares as USDC. Without this, MMB's bankroll counter says "+$X" but the wallet stays at the same balance.

**S.6 hard requirement:** add a post-resolution redemption step. After a window resolves with held shares, call `mergePositions` (if both sides held) or `redeemPositions` (if only winning side held) via py-clob-client's relayer interface. Verify USDC.e balance increases.

**Alternative consideration:** Polymarket also mentions "Split converts pUSD into equal amounts of YES and NO tokens". MMB currently BUYS shares from takers; we don't split. But understanding the inventory mechanics helps with the "both sides held" case at window resolution.

Source: https://docs.polymarket.com/market-makers/inventory

### 1.4 Approval flow — possibly 3 approvals, not 1

> "Three separate token approvals required (pUSD→CTF, CTF→Exchange, CTF→Neg-Risk Exchange)"

**Implication:** our `mm_set_allowance.py` only addresses USDC.e → CTF Exchange. There may be 2 more approvals needed:
- pUSD → CTF (for split operations, if we ever split)
- CTF → Neg-Risk Exchange (irrelevant for BTC 5m which is standard CTF per S.1.1 Q5)

**S.6 action:** verify on the live `getBalanceAllowance` query whether MMB needs the other 2 approvals. For S.5 the USDC.e → CTF Exchange approval is what's needed (we're only placing maker BUY orders on standard CTF Exchange; no splits, no neg-risk).

Source: https://docs.polymarket.com/market-makers/getting-started

### 1.5 WebSocket channels — replace book-polling with WS

> "Best practice emphasizes responsiveness: 'Cancel stale quotes immediately when market conditions change.' Use WebSocket subscriptions for real-time market data rather than polling REST endpoints."

CLOB market channel: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
CLOB user channel: `wss://ws-subscriptions-clob.polymarket.com/ws/user`

**Implication:** our current 1s polling (`scripts/run_mm_live.py:DEFAULT_BOOK_POLL_S`) is sub-optimal for the LATE-window 30-60s placement window where bonereaper's edge concentrates. WS would reduce book-staleness from 500ms avg to <50ms.

**S.6 candidate edge (not in audit): WebSocket subscription for book updates.** Replaces the polling loop in `_book_loop_one_token`. Estimated edge contribution: +20-30% on Edge 2's LATE-window multiplier (faster cancel-replace = better queue position when book moves).

Source: https://docs.polymarket.com/market-makers/getting-started + agent-skills `websocket.md`

### 1.6 pUSD vs USDC.e — naming check

Polymarket docs reference `pUSD` (their wrapped USDC token) in inventory operations. Our Phase 1A docs reference USDC.e (`0x2791Bca1...`). Contract addresses:
- USDC.e: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (what S.1.1 uses)
- pUSD: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` (per Polymarket inventory docs)

These might be the SAME thing labeled differently in different docs, OR pUSD might be a Polymarket-specific wrapper of USDC.e. **S.6 verify before live deploy.**

---

## §2. Session 6 phased plan

### Phase 6A — pre-deploy verification (60-90 min)

P1. Verify pUSD vs USDC.e (§1.6). Read `~/.claude/skills/agent-skills/SKILL.md` Contract Addresses + cross-check py-clob-client source for which token it actually approves.

P2. Investigate Maker Rebates Program (§1.1). Look for:
- A `getRebates(user)` or `getFees(user)` endpoint in py-clob-client.
- Whether BTC 5m markets have `feesEnabled=true` in the Gamma response.
- If rebates apply: what's the typical rebate rate (bps)?

P3. Update USDC.e → CTF Exchange allowance via `scripts/mm_set_allowance.py --apply` if not yet set. Verify `state/mm-allowance.json` shows ≥$10k.

P4. Run G11 empirical probes via `scripts/research/mmb_g11_probes.py --mode {fee,cancel-latency,rate-limit}`. Three short runbook addenda. Costs ~$5 in test orders + a few minutes of $0 cancel-replace probing.

P5. If P4's fee probe shows non-zero realized cost, recalibrate `J7Priors.bet_size` math (subtract fee from p_win edge) + ship as a separate commit BEFORE flipping bot-mm.service to live.

### Phase 6B — first-fire (operator-supervised)

P6. Set env vars on VPS (`PK_SIGNER`, `POLY_FUNDER`, CLOB L2 creds, `MM_LIVE_CONFIRM=yes`).

P7. Edit `/etc/systemd/system/bot-mm.service` ExecStart to point at `scripts/run_mm_live.py`.

P8. Remove `state/halt.sentinel`. `sudo systemctl start bot-mm.service`.

P9. **Watch first 5 minutes hands-on.** Tail journal + Telegram + dashboard. Expect:
- ladder placement events in `state/mm-decisions/<UTC>.jsonl` within 10 seconds
- first fill (if any) triggers `mm_first_fill_confirmed_alert` to Telegram
- heartbeat task posts every 5s; no misses in logs

P10. If anything looks wrong: `echo '{"reason":"first_fire_concern"}' > state/halt.sentinel` to immediately stop placement, then `systemctl stop bot-mm.service`.

### Phase 6C — Day-1 soak (24h, hands-off)

P11. At T+24h: `uv run python scripts/research/mmb_soak_audit.py --days 1`.
- PnL > $0: good. Optionally flip `MM_CAPS_MODE=pct_bankroll` for compounding.
- PnL between -$30 and $0: marginal. Extend 24h.
- PnL < -$30 (which would trip $50/day cap before reaching this): investigate halt sentinel + postmortem.

P12. **Edge 4 evaluation (preliminary, post-Day-1):** group fills by `mmd_label` in the decision log. If MMD getter was wired (Phase P pattern), compute per-label $/tr. Otherwise this analysis lands at Day-7.

### Phase 6D — Day-7 soak audit (S.5 → S.6 promotion gate)

P13. At T+7d: `uv run python scripts/research/mmb_soak_audit.py --days 7 --gate`.

Gate criteria from the audit:
- Cumulative 7d PnL > $0 → PROMOTE to S.6 (scale-up caps)
- No incidents: 0 unrecovered heartbeat misses, 0 halt-sentinel trips
- Fill-rate sane (in [0, 1])

P14. If PASS → schedule S.6 (this prompt covers up to S.6 promotion gate):
- Flip `MM_CAPS_MODE=pct_bankroll` (already-shipped Edge 3 schema)
- Raise initial pct values per audit §4 (max_inventory_per_token_pct 2.5% → 5%; max_gross_exposure_per_window_pct 5% → 10%)
- Continue soak through week 2

P15. If FAIL → STOP. Write `runbooks/postmortems/2026-05-XX-mmb-s5-failure.md`. Likely diagnosis from §2 candidate edges that didn't ship: WS book updates (faster cancels), redeemPositions wiring (was bankroll actually growing?), or queue position genuinely too back-of-line at $1k bankroll.

### Phase 6E — new edges (deferred to post-Day-7 if Day-7 PASSes)

E1. **WebSocket book updates** (§1.5) — replace `_book_loop_one_token` polling with WS subscription. Reduces book staleness from 500ms avg to <50ms. Expected +20-30% on Edge 2's LATE-window contribution.

E2. **redeemPositions wiring** (§1.3) — post-window-close redemption. **HARD requirement if Day-1 shows MMB winning but USDC.e balance not growing.** Verify shares are being converted to USDC.

E3. **Maker Rebates accounting** (§1.1) — if BTC 5m has feesEnabled=true, add rebate income to the bankroll replay logic. Possibly worth $0.025-$0.10 per fill which adds up.

E4. **Liquidity Rewards monitor** (§1.2) — daily check whether BTC 5m enters rewards. If it does, the two-sided MMB ladder design earns rewards on top of spread capture.

---

## §3. Don't-do rules (operator + design)

- Do NOT re-enable `bot-staging.service` (directional bot stays archived).
- Do NOT change strategy logic in `market_maker.py` / `j7_priors.py` during Day-1 or Day-7 soak. Issues surface in audit; redesign happens between soaks.
- Do NOT raise caps mid-soak. The `MM_CAPS_MODE=pct_bankroll` flip is the only mid-soak knob, and only after Day-1 PASSes.
- Do NOT scale bankroll past $2k without HW wallet wiring (decision #12).
- Do NOT skip the redeemPositions implementation if Day-1 shows accounting drift (bot says +$X but wallet doesn't grow).
- Do NOT submit live orders outside the G11 probes ($5 each) + the bot itself.

---

## §4. Closeout artifacts (post-Day-7)

If Day-7 PASSes:
1. `state/sessions/2026-05-XX-phase-S-session-6-close.md` (template: previous close notes).
2. `memory/checkpoint_phase_S_session_6.md`.
3. `MEMORY.md` index entry.
4. `state/phases/phase-S-market-maker.md` — mark S.5 CLOSED with live numbers, S.6 next.
5. `phase-prompts/phase-S-session-7-scaleup.md` (S.6 scale-up + edge E1/E2/E3 implementation).

If Day-7 FAILs:
1. `runbooks/postmortems/2026-05-XX-mmb-s5-failure.md` (root-cause analysis).
2. Decide: pivot strategy class, soak longer, or shelve Phase S.
3. Memory checkpoint reflecting the failure mode.

---

## §5. Key references for the agent picking this up

- Branch HEAD: `22ccab4` on `claude/phase-S-market-maker`
- VPS HEAD: same, services dormant
- Audit: [runbooks/research/mmb-deep-edge-audit-2026-05-20.md](../runbooks/research/mmb-deep-edge-audit-2026-05-20.md)
- Polymarket MM docs: https://docs.polymarket.com/market-makers/overview
- Liquidity Rewards: https://docs.polymarket.com/market-makers/liquidity-rewards
- Trading: https://docs.polymarket.com/market-makers/trading
- Inventory: https://docs.polymarket.com/market-makers/inventory
- Getting started: https://docs.polymarket.com/market-makers/getting-started
- Market data: https://docs.polymarket.com/market-data/overview
- agent-skills (cloned): `~/.claude/skills/agent-skills/`
- 809 tests baseline; full suite: `uv run pytest -q`
- Live entrypoint: `scripts/run_mm_live.py` — refuses to start unless 4 preflight gates pass
- Day-N audit: `scripts/research/mmb_soak_audit.py [--days N] [--gate]`
- G11 probes: `scripts/research/mmb_g11_probes.py --mode {fee,cancel-latency,rate-limit}`
- Allowance: `scripts/mm_set_allowance.py [--apply]`

## §6. Honest expectation framing

**Realistic Day-7 outcome on $1k bankroll with edges 1+2 active + conservative caps (fixed_usd mode):**

- PnL: +$30 to +$200 (3-20% weekly) — most likely range
- Best case: +$400-$700 (40-70% weekly) if queue position is better than feared
- Worst case (still passing): -$30 to +$30 (around break-even, soak extended)
- Failure (gate-fail): cumulative < -$50 or any incident requiring halt

10x bonereaper rate ($110/week) is achievable at $1k bankroll within these numbers. 100% weekly ($1,000) is best-case + only if everything works (queue position lift, late-window capture, no incidents). Don't bet on best-case; budget for realistic.

After Day-7 PASS + pct-caps flip + ~3 weeks of compounding, bankroll trajectory enters the territory where "10x bonereaper PER WEEK" becomes plausible (audit §5 projections).

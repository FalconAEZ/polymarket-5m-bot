# 2026-05-09 — Local Chainlink resolver disagrees with Polymarket on ~33% of windows

## TL;DR

Our `actual_resolution()` resolver in `src/polymarket_bot/resolver.py` uses
locally-captured Chainlink AnswerUpdated samples (`open_oracle`,
`close_oracle`) to score whether each window resolved UP or DOWN. **For
3 of the first 9 settled decisions (33%), our local result disagreed with
Polymarket's official resolution.** Until we wire Chainlink Streams (the
pull-based feed Polymarket itself uses), every settled trade's `pnl_usd`
on the local ledger is unreliable.

Operator caught it: bet DOWN on window `1778275800`, BTC actually went
DOWN per Polymarket, our dashboard said LOST. The trade was actually a
+$449.54 winner ($5 stake on DOWN at $0.011 entry → 454.5 shares × $1
payout).

## Root cause

Our oracle feed listens for `AnswerUpdated` events from the on-chain
Chainlink BTC/USD aggregator. That feed is **push-based with a 1-2 minute
heartbeat plus a deviation trigger** — values land sparsely. Snapshot:

```
window 1778275800 (UTC 21:30:00 → 21:35:00):
  decision time:  21:30:00.235  oracle_last = 80160.53298
  settle time:    21:35:00.015  close_oracle = 80189.26882
  → close > open → our resolver returns UP
```

But Polymarket uses **Chainlink Streams** (the pull-based, sub-second feed
at `data.chain.link/streams/btc-usd`) at the *exact* T (21:30:00) and
T+300 (21:35:00) timestamps. Our `oracle_last` at "decision time" is the
last AnswerUpdated event we observed — which could be from any time in
the prior 1-2 minutes, NOT from 21:30:00 exactly. Same for close.

For window 1778275800 specifically, Polymarket's two snapshots showed a
DOWN move while our drifted samples showed an UP move. ~30s of clock
drift on a small move = wrong sign on the resolution.

## Affected data

3 of the first 9 settled aggressive-mode decisions (2026-05-08):

| Window | Side | Oracle said | Polymarket truth | PnL was | PnL is |
|---|---|---|---|---:|---:|
| 1778272200 | DOWN | DOWN | UP | $0.00 (no fill) | $0.00 |
| 1778275500 | DOWN | DOWN | UP | +$2.92 | -$5.00 |
| 1778275800 | DOWN | UP | DOWN | -$5.00 | **+$449.54** |
| 1778276400 | DOWN | DOWN | UP | $0.00 (no fill) | $0.00 |

Net dashboard impact: cumulative PnL was reported as ~ -$12 (oracle
truth); actual is **+$434.54** (Polymarket truth). Bankroll: $1,434.54.

## Fix (this session — dashboard scope)

`scripts/resolve_decisions.py` post-processes the JSONL ledger after
each VPS sync, querying Gamma for each settled window's authoritative
outcome and rewriting `resolution` + `pnl_usd`. Records get a new field
`resolution_source: "polymarket"` and the original oracle reading is
preserved in `resolution_oracle_local` for audit.

Wired into `runbooks/scripts/sync_staging.sh` so every dashboard refresh
sees the corrected data automatically. Idempotent — safe to call
repeatedly. First run on each file creates a `.bak` of the unmodified
original; subsequent runs only modify changed records.

## What this does NOT fix (deferred)

- **The live bot's in-memory ledger** still uses oracle truth at fire time.
  The `state/decisions/<UTC>.jsonl` files on the VPS get overwritten with
  oracle-truth at settle time before sync_staging.sh re-resolves them.
  Live trading (Phase 6) will need a different mechanism — either query
  Gamma at settle time inline, or switch to Chainlink Streams as the
  oracle source. Either is a real design + impl effort.
- **The bot's internal `_RunState.settled_fill` and any code path that
  acts on `resolution` at runtime** (alerting, kill-switch logic) still
  use oracle truth. None of these are currently load-bearing for paper
  mode, but become load-bearing in Phase 6.
- **Phase 5.7 gate evidence** — the audit script reads VPS data, not the
  re-resolved laptop view. The 24h-clean-uptime gate (criterion #7)
  still passes on its own merits (zero exceptions), but per-trade PnL
  numbers in any future gate audit need to use the re-resolved data.

## Why this matters

PnL is the gate. If our PnL is wrong by ±$5 per windows where we
fired, and 33% of windows have wrong sign, the entire 7-day paper-soak
gate (`runbooks/decisions/aggressive-mode-2026-05-09.md`) is unreliable
without this fix. The aggressive-mode trip wires (PnL ≥ -$50 in 24h, WR
≥ 47% on 100+ settled) all depend on accurate resolution.

The single 1778275800 winner alone (+$449.54) flipped a "we're losing"
read to "we're up significantly." That's the difference between
"aggressive mode is failing as predicted" and "aggressive mode found
edge." Without this fix, we'd halt the experiment for the wrong reason.

## How we found it

Operator manually cross-checked window 1778275800 against the public
Polymarket UI and saw the discrepancy. Filed at 2026-05-09 ~01:30 UTC.
Diagnosis took ~5 min once we had the Gamma response in hand
(`outcomePrices: ["0", "1"]` → DOWN won).

## Lessons

1. **Local-oracle-as-truth was a 5-min-bot-design assumption that
   doesn't survive contact with Polymarket's actual resolver.** The
   masterplan called for "Chainlink BTC/USD on Polygon" as the oracle —
   technically correct, but Polymarket reads from Chainlink Streams
   (off-chain pull feed), not the on-chain Aggregator. They produce
   subtly different prices at any moment.
2. **A 33% disagreement rate is huge.** Even before this session's
   numbers, replay-calibration data from 2026-05-08 should have shown
   this if we'd cross-checked against Polymarket. We didn't, because
   the deterministic strategy fired zero in replay so there was nothing
   to disagree about.
3. **Gamma is the right truth source for now.** Free, public, no auth,
   close-of-window resolution available within ~1-2 minutes. Slightly
   delayed but accurate. Good enough for paper-soak gating.
4. **For Phase 6 (real money), settlement-truth must come from
   Chainlink Streams or Gamma at settle time, not from local oracle
   samples.** Add to phase 6 prereq list.

## Files touched

```
NEW  scripts/resolve_decisions.py
MOD  runbooks/scripts/sync_staging.sh    (run resolve after rsync)
NEW  runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md  (this doc)
```

## See also

- `src/polymarket_bot/resolver.py::actual_resolution` — the wrong code
  (still in place, used at fire-time on the VPS).
- `src/polymarket_bot/_paper/runner.py::_settle_current_window` — the
  caller of the wrong code.
- `runbooks/decisions/aggressive-mode-2026-05-09.md` — gate criteria
  whose validity depends on correct resolution.
- `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` — used
  Polymarket's resolved trade data, NOT local oracle, so its win-rate
  numbers (51.7% net WR, +30.9pp aligned-vs-contrarian gap) are
  unaffected by this bug.

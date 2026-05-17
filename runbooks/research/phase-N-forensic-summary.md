# Phase N forensic — Session 1 operator briefing

**Generated 2026-05-17 14:35Z. Investigation-only. Bot stays halted.**

## TL;DR

The peak-to-floor swing of -$1,562 is dominated by ONE failed cell —
tier 30-50% × |Δbps|≥5 (the "surviving winner" from Phase L) — flipping
from a 60.7% WR profit-engine to a 46.5% WR bleeder right at the
2026-05-15 15:40Z peak. Tier 70-85% Path A is a slower but persistent
secondary bleed (-$368 over 5 days). Today's tier 30-50% losses ($-30)
are real but small relative to the broader pattern. Two of the five
new M.* layers (M.2 v0, M.5) had too little activation time to evaluate;
M.1a v1 shows the suggestive (n=23 vs n=58) inversion of "we abstained
the winners and fired the losers" on the small annotated subset.

## What the data confirms

| anchor                              | data | matches prompt? |
|-------------------------------------|------|-----------------|
| Peak cum-PnL                        | +$1,235.41 at 2026-05-15 15:40:00Z | ✓ exact |
| Floor cum-PnL                       | -$326.79 at 2026-05-17 12:38:36Z   | ✓ exact ($673 = $1,000 + cum) |
| 5 M.* layers live at halt           | confirmed                          | ✓ |
| Bot inactive + halt sentinel reason | `operator-cooldown`                 | ✓ |
| 100% strategy=spot_aware_v2_1       | 755/755 fires                       | ✓ Kelly 0.15× + replay throughout |
| Path A block_up working             | 0 / 237 tier 70-85% are UP-side     | ✓ |
| Phase J.1.5 CH3 fold working        | 0 CH3 fires post-peak               | ✓ |

## Headline findings

### Finding 1 — SURV cell (tier 30-50% × |Δ|≥5) is the dominant bleeder

|                | n   | WR     | $/tr     | PnL      |
|----------------|-----|--------|----------|----------|
| SURV pre-peak  | 112 | 60.7%  | +$12.78  | +$1,431  |
| SURV post-peak | 228 | 46.5%  | -$5.09   | -$1,161  |
| **Swing**      |     | -14.2pp | -$17.87 | **-$2,592** |

This single cell flipped at peak. The peak-to-floor swing of -$1,562 is
mostly inside this slice (rest of the bot is roughly flat). H5
("Path A break-even WR collapsed") was the prompt's framing; the data
says it's the SURV cell that collapsed, and Path A is a separate slower
bleed.

### Finding 2 — Tier 70-85% Path A is a separate persistent bleeder

- n=237, WR=74.3% (looks high), $/tr=-$1.55, PnL=-$368 over 5 days
- 100% are DOWN-side (H.2.12 block_up works); break-even ≈ 1 - avg_ask
  ≈ ~77.5% on this slice — bot's 74.3% is structurally below
- M.5 was designed to catch exactly this; need to verify M.5 ever
  activated (cold-start n<20 hypothesis B.5 from prompt; Session 2)

### Finding 3 — M.1a v1 inversion suspicion (small-n caveat)

On the M.1a-annotated subset only (n=83 of 755):

| regime label | n  | WR    | $/tr    | PnL     | M.1a v1 action |
|--------------|----|-------|---------|---------|----------------|
| chop         | 23 | 60.9% | +$1.33  | +$30.57 | **ABSTAIN** ⚠ |
| mixed        | 58 | 44.8% | -$5.11  | -$296.28 | FIRE |
| trending     | 2  | 50.0% | -$19.97 | -$39.94 | FIRE |

If labels are accurate, M.1a v1 — active since Sun 11:26Z — was
abstaining the (small-n) winning cell and letting the losing cell
through. This is exactly the kind of feature-misclassification the
operator's H3 hypothesis predicted. **n is too small to be conclusive;
N.5 regime-classifier-validity test is the falsifier.**

### Finding 4 — M.5 + M.2 v0 effectively un-evaluable from this data

- M.5 was live Sun 11:45Z → 12:43Z (58 minutes). Path A activations
  in that window need its own pass.
- M.2 v0 was live Sun 11:58Z → 12:43Z (45 minutes). Logged 3 fires,
  all labeled `too_thin`. No bullish/bearish/balanced labels appeared.
  Either (a) the book truly was too thin for 45 min during the halt
  spiral, (b) the classifier is biased toward too_thin under stress,
  or (c) only 3 fires had imbalance-eligible book depth. Can't tell.

### Finding 5 — Per-UTC-hour pattern shifted

Worst-loss tier-30-50% hours over 5 days:

|   hour | n  | WR     | PnL      |
|-------:|----|--------|----------|
| 05 UTC | 14 | 35.7%  | -$266    |
| 06 UTC | 16 | 37.5%  | -$251    |
| 17 UTC | 20 | 20.0%  | -$259    |
| 21 UTC | 28 | 28.6%  | -$516    |
| 23 UTC | 30 | 33.3%  | -$288    |
| 00 UTC | 23 | 34.8%  | -$168    |

J.2 hour-blocklist currently blocks 22/23/00 UTC × tier 70-85%. None of
the above tier-30-50%-bleed hours are blocked. **Candidate J.2 extension
for Phase O: block tier 30-50% × {05, 06, 17, 21, 23, 00} UTC.**

## Hypothesis attribution (preliminary, pending Session 2-4)

| prompt hypothesis | preliminary verdict | confidence |
|------|------|------|
| H1 regime shift bot can't detect | likely contributing — SURV cell flip is consistent with a regime shift at peak | medium-low (no spot-tick data) |
| H2 tier 30-50% structural break | **partly confirmed** — SURV slice collapsed; CH3 is contained by J.1.5 fold | medium |
| H3 features fighting each other | **suggestive inversion in M.1a v1** (small-n); M.5 cold-start hypothesis pending | medium |
| H4 Kelly 0.15× variance amplifier | this is what magnified the SURV collapse into a -$1.5k swing; not the cause | high (Kelly is mechanical) |
| H5 Path A break-even WR collapsed | confirmed for tier 70-85% Path A; not the dominant driver | medium |
| H6 spot/Polymarket basis broke | un-testable from this data (no implied-prob history) | n/a |
| H7 time-of-day shifted | **confirmed** — bleed hours are 05, 06, 17, 21, 23, 00 UTC on tier 30-50% | medium-high |
| H8 multiple compounding | **most likely** — SURV cell flip + Kelly amp + hour-of-day mix + maybe M.1a inversion | high |

## Recommendation for Session 2

Don't ship anything yet. Falsify the strongest findings first:

1. **Audit whether M.5 ever activated** during its 58-min live window
   (re-compute compute_path_a_metrics on full 5 days; check for
   n_settled ≥ 20 at any point).
2. **Compute a proxy regime for ALL 755 fires** (not just the 83
   M.1a-annotated subset) using fire-time spot vs window-open delta,
   then re-run per-regime WR. If the chop>mixed WR inversion holds on
   n=755, M.1a v1 needs to be DISABLED before resume.
3. **Decompose SURV-cell post-peak** into per-day, per-side, per-hour,
   per-Δbps sub-slices to localize what broke.

After Session 2, the candidate Phase O fixes will be one of:
- (a) Re-enable J.2 with broader hour-block (covers H7 finding)
- (b) Disable M.1a v1 entirely until inversion is falsified
- (c) Kelly demotion 0.15× → 0.10× (variance-only fix)
- (d) Strategy class flip to spot_aware_v2 vanilla (decision #9 reset)

Recommendation order is data-dependent on Session 2 results.

## What we still don't know

- Whether the SURV cell flip was driven by a regime shift the bot
  classifier missed (needs spot-tick history we don't have).
- Whether M.5 ever crossed its activation threshold (Session 2 task).
- Whether M.2 v0's "too_thin only" labels reflect classifier bias or
  market reality during the 45-min halt-spiral window.
- Whether removing all M.* layers (vanilla v2) would have bled less
  (Session 3 counterfactual).

## Limits — repeat from prompt N-P2 / N-P3

- 45-h bleed sample is small. Findings are SUGGESTIVE.
- No persistent spot tick capture; regime analysis is bounded.
- M.1a annotation covers 83/755 fires; M.2 covers 3/755. Effect-size
  estimates on annotated subsets are honest small-n.

## Next session

Operator picks 2-3 of: A (M.* feature audit), B (SURV decomposition),
C (counterfactuals), D (hour-of-day forensic). Recommendation: A + B
to falsify the strongest findings before chasing remediation.

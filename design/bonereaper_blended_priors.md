# Bonereaper-blended priors (Phase J.7 — sketch)

**Status:** DESIGN SKETCH (§1-3 only) · 2026-05-13.
**Full design:** locked in Session 4 of Phase J.
**Implementation target:** Session 5 of Phase J (estimated +14 calendar
days after Session 1 kickoff).
**Source-of-truth prompt:** phase-prompts/phase-J-edge-exploitation-2026-05-13.txt §J.7.

## 1.  Why revisit bonereaper now

### 1.1  The $700k milestone

Polymarket wallet `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`
(bonereaper) crossed **$700,000 cumulative PnL** on 2026-05-13 per
operator report. The wallet is one of the most-profitable observable
trading wallets on the 5-min BTC up/down markets. Empirical proof that
edge exists at scale on the EXACT market class our bot trades.

### 1.2  Locked-decision #19 was the wrong gate

Decision #19 aborted the bonereaper cloning study 2026-05-06 based on
the Phase A 7-day pre-flight: 52.65% direct WR over 56,972 BTC 5m
trades, below the 60% gate. The PDF abort note correctly read this as
"too low for direct-copy to break even after lag + fees".

But the abort gate measured **direct win-rate** (a mix of aligned + 
contrarian trades). The 30-day spot-vs-book audit
(`runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md`, n=306,966)
showed:

| Alignment | Trades | WR | Notional | Gross PnL | $/trade |
|---|---|---|---|---|---|
| aligned (spot-Δ aligned with side) | 101,962 | **67.4%** | $7.96M | +$83,054 | +$0.81 |
| contrarian (spot-Δ opposed) | 117,040 | 36.4% | $2.08M | +$67,310 | +$0.58 |
| flat (\|Δ\| < 5 bps) | 87,964 | 53.9% | $2.09M | +$84,499 | +$0.96 |

**The aligned-vs-contrarian WR gap is +31 percentage points.** This is
the canonical proof that spot-Δ alignment IS an edge at large sample.
Direct WR of 52.65% conflates the two; aligned-only is the edge measure.

The decision-#19 abort remains correct for the DIRECT-COPY strategy
class (mirror their orders). What it does NOT close is using their
30-day aligned-WR table as a **Bayesian prior anchor** in our own
strategy. That is a different deployment class with different risks.

### 1.3  Per-tier aligned WR (the J.7 prior table)

From the same 306,966-trade audit:

| tier      | trades | WR (aligned) | $/trade aligned |
|-----------|--------|--------------|-----------------|
| <15%      | 722    | 13.7%        | +$8.83          |
| 15-30%    | 3,167  | 25.0%        | +$0.11          |
| 30-50%    | 14,802 | 45.4%        | +$1.17          |
| 50-70%    | 39,681 | 63.1%        | +$0.95          |
| 70-85%    | 28,674 | 78.0%        | +$0.40          |
| 85-100%   | 14,916 | 91.7%        | +$0.65          |

This is the table J.7 ships as a Bayesian prior anchor. The per-(tier,
side) granularity also exists in the raw data — Session 5 will refresh
with the most-recent 30 days and produce a (tier, |Δ| bucket, side)
keyed table.

## 2.  What this is NOT

### 2.1  NOT auto-clone

We do not mirror bonereaper's orders. The original BONEREAPER_STUDY.pdf
§0 enumerated six reasons direct copy-trading fails:

1. **Confirmation lag:** 1-2s on Polygon kills 300s-market edges.
2. **Sample-of-one risk:** their behavior could shift overnight.
3. **No diagnostic** when behavior shifts.
4. **Adversarial trapping** by visible wallets.
5. **Survivorship bias** in multi-wallet portfolios.
6. **Cost-basis mismatch** between their fills and ours.

All six still apply. We're not direct-copying.

### 2.2  NOT re-opening locked-decision #19

Decision #19 closed the bonereaper cloning study at the Phase A pre-
flight gate. J.7 does not re-open that decision. The bonereaper data
becomes a **prior anchor input** to our existing v2.1 + adaptive priors
strategy class. The locked decision was correct for the strategy class
it gated (direct-copy); J.7 is a different strategy class.

If Session 5's empirical measurement shows the bonereaper-blended
prior produces clean WR uplift in shadow soak (≥3pp over J.3-only at
n≥100), Session 5 promotes the blend to gate mode. If not, J.7 stays
dark and we accept the J.3-only Realistic outcome.

### 2.3  NOT a real-money trigger

Real-money go is locked to Phase 10 / Phase K and requires the 30-day
mid-gate at Session 8. J.7 is a paper-mode prior anchor. Live $$$ is
explicitly out of scope for Phase J.

## 3.  Architecture (sketch)

### 3.1  Data refresh pipeline

```
scripts/research/refresh_bonereaper_30d.py
  ├── Polygon subgraph query (Goldsky / Polymarket subgraph):
  │   pull every fill on the 5m BTC up/down markets executed
  │   FROM the wallet 0xeebde7a0e019a63e6b476eb425505b7b3e6eba30
  │   in the last 30 days
  │
  ├── Polymarket Gamma API:
  │   resolve each fill's market metadata (window_ts, resolution)
  │
  ├── BTC spot tick join (Binance Trades feed archive):
  │   for each fill, join with spot price at fill timestamp;
  │   compute Δ_bps = 10000 * (S_fill - S_window_open) / S_window_open
  │
  ├── Alignment classify:
  │   alignment = "aligned" if (side=UP and Δ>0) or (side=DOWN and Δ<0)
  │             = "contrarian" if (side=UP and Δ<0) or (side=DOWN and Δ>0)
  │             = "flat" if abs(Δ_bps) < 5
  │
  ├── Per-cell aggregation:
  │   for each (tier, abs_delta_bucket, side, alignment):
  │     trades, wins, pnl, notional
  │
  └── Output: state/research/bonereaper/aligned_priors_30d.json
      schema: {
        "generated_at": "<ISO-UTC>",
        "lookback_days": 30,
        "n_trades": <int>,
        "per_cell": {
          "<tier>:<abs_delta_bucket_str>:<side>:<alignment>": {
            "n": <int>,
            "wins": <int>,
            "wr": <float>,
            "pnl_per_trade": <float>,
          }
        }
      }
```

### 3.2  Bayesian-blended priors (extends J.3's AdaptivePriors)

The J.3 `AdaptivePriors` formula is extended with a third weight:

```
p_win_blended(tier, |Δ|_bucket, side) =
    (w_static × p_static + w_bonereaper × p_bonereaper + w_rolling × p_rolling)
    /
    (w_static + w_bonereaper + w_rolling)

where:
  w_static     = 50    (Phase G anchor; same as J.3)
  w_bonereaper = 100   (HIGH; their n is 1000x ours so anchor weight is stronger)
  w_rolling    = min(N_observed, 100)
```

At N_observed=0, the blend becomes:

```
p_win = (50 × p_static + 100 × p_bonereaper) / 150
      = 0.333 × p_static + 0.667 × p_bonereaper
```

This pulls the prior STRONGLY toward bonereaper's measured aligned WR
even on the first fire — which is exactly the leverage we want from
having 306,966 trades of evidence.

At N_observed=100, the blend becomes:

```
p_win = (50 × p_static + 100 × p_bonereaper + 100 × p_rolling) / 250
      = 0.20 × p_static + 0.40 × p_bonereaper + 0.40 × p_rolling
```

Rolling and bonereaper share dominance with 40% each, while static
keeps a 20% anchor. The bonereaper component prevents the rolling
estimator from drifting toward a non-aligned local pattern (e.g., if
our adversarial counterparties exploit our recent fires, rolling-only
would over-correct; bonereaper anchors back to the 30-day truth).

### 3.3  Module sketch

```python
# src/polymarket_bot/strategies/bonereaper_priors.py

class BonereaperPriors:
    """Loads the 30-day aligned-WR table from disk and exposes
    per-(tier, |Δ|_bucket, side) p_win values. Read-only after
    construction; refresh handled by scripts/research/refresh_bonereaper_30d.py
    + a systemd timer (e.g., daily 04:00 UTC).
    """
    def __init__(self, table_path: Path) -> None:
        with table_path.open() as f:
            data = json.load(f)
        self._per_cell = data["per_cell"]
        self._generated_at = data["generated_at"]
        self._n_trades = data["n_trades"]

    def lookup(
        self, *, tier: str, abs_delta_bucket: tuple[float, float], side: str
    ) -> float | None:
        # alignment is implicit — bonereaper data is filtered to aligned only
        key = f"{tier}:{_bucket_str(abs_delta_bucket)}:{side}:aligned"
        cell = self._per_cell.get(key)
        return cell["wr"] if cell and cell["n"] >= 10 else None
```

### 3.4  Env-vars (sketch)

```
SPOT_AWARE_BONEREAPER_PRIORS_ENABLED   = false  (DARK SHIP first)
SPOT_AWARE_BONEREAPER_W                = 100
SPOT_AWARE_BONEREAPER_TABLE_PATH       = state/research/bonereaper/aligned_priors_30d.json
SPOT_AWARE_BONEREAPER_REFRESH_INTERVAL_H = 24  (cron / systemd timer)
```

### 3.5  Promote gate

shadow-WR (bonereaper-blended subset) ≥ J.3-only-WR + 3pp on n ≥ 100
→ env-flip enable → bonereaper becomes primary priors source; J.3
rolling stays as secondary correction layer.

## 4.  Risks (preview)

### R1: Edge non-transferability

Bonereaper's 67.4% aligned WR may not transfer. Their edge could be
fill-quality (maker rebates × capital scale) rather than signal. Our
infra (1ms RTT to PM, $1k bankroll) limits how much of fill-quality
edge we can replicate. The aligned-WR table is a hard CEILING; expect
transfer 5-10pp lower in practice. Still worth +3-5pp WR.

### R2: Adversarial visibility

The wallet is public. If our blended priors mirror their alignment
table, sophisticated counterparties could exploit OUR predictability.
Mitigation: J.7 priors influence p_win, not order placement directly —
our fires still depend on local spot-Δ + EV + Kelly + cap=2. The
adversarial surface is no different from any priors-aware strategy.

### R3: 30-day staleness

The table refreshes daily but represents a 30-day rolling window.
Regime shifts within 30 days are smoothed out. J.5 vol-regime overlay
+ J.3 rolling-priors are the two layers handling shorter-timeframe
drift; J.7 anchors at the 30-day truth.

## 5.  Cross-references (full design in Session 4)

- Phase G PDF §6.2 — winning cell context
- design/adaptive_priors.md (J.3) — the per-cell rolling layer
- runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md — source data
- runbooks/research/bonereaper-microstructure-30d-2026-05-08.md — fill quality context
- pdfs/PHASE_J_EDGE_EXPLOITATION.pdf — Phase J overall plan
- memory/bonereaper_study.md — locked-decision #19 abort context
- BONEREAPER_STUDY.pdf — original aborted study

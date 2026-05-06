# Design — `scripts/research/quick_audit.py` (Phase A)

> Purpose: pre-flight audit of Polymarket wallet **bonereaper** (`0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`).
> Decides whether the full Phase B-G research stream is worth building.
> Writes a quick-look report and a pass/fail decision file. **No code in `src/` from this script** — it is research scaffolding under `scripts/research/`.

---

## 1. Inputs

| Source | Endpoint | Auth | Use |
|---|---|---|---|
| Polymarket Data API | `https://data-api.polymarket.com/trades?user=<addr>&limit=500&offset=N` | None | Per-trade history (paginated) |
| Polymarket Gamma API | `https://gamma-api.polymarket.com/events?slug=<slug>` | None | Per-market resolution + metadata |

Both APIs are public read-only. No keys involved. Polygon RPC is **not** used in this script — Phase A is purely off the public APIs.

## 2. Filtering rule

Only **closed BTC 5-min markets** count toward the gate metrics. Filter:
- `slug.startswith("btc-updown-5m-")` (exact prefix; ETH and 15-min markets excluded)
- Market must be `closed: true` AND have non-empty `outcomePrices` (i.e., resolved)

Out-of-scope but still tabulated for the report:
- ETH-updown 5m and 15m markets — counted, win-rate computed, **not** part of the gate
- Daily/longer-form markets — counted only as "other" volume

## 3. Win/loss per trade

For each filtered closed trade where bonereaper bought outcome O at price P with size S:

```
outcome_won  = (outcome == "Up"  and outcomePrices[0] == "1") or
               (outcome == "Down" and outcomePrices[1] == "1")
gross_pnl    = ((1.0 - P) * S) if outcome_won else (-P * S)
fee_paid     = 0  # assume fees baked into fill price; refine in Phase D
net_pnl      = gross_pnl - fee_paid
is_win       = (net_pnl > 0)
```

Polymarket V2 has a documented `feeSchedule` (≈ 7.2 bps taker, see one closed BTC 5m response). For Phase A this is approximated as already baked into `price`. Phase D refines.

## 4. Metrics computed

For BTC 5-min trades only (the gate metrics):
1. **Total trades** observable on BTC-5m
2. **Total volume** (sum of `price * size`)
3. **30-day rolling win-rate** (last 30 calendar days from `now`)
4. **90-day rolling win-rate**
5. **Trade frequency** — trades/day median/p90 over observable window
6. **Average size** + size distribution
7. **UP/DOWN balance** (counts of each side)
8. **Time-of-day heatmap** (UTC hour bucket × win/loss)
9. **Volume MoM trend** (current 30 days vs prior 30 days; the >40% drop check)
10. **Behavior-shift markers** — date(s) where rolling 7-day win-rate or daily volume shifts > 2σ

For the **report only** (not in the gate decision):
- Same metrics on ETH 5m and ETH 15m subsets
- "Other" totals (everything not BTC-5m / ETH-5m / ETH-15m)

## 5. Pagination strategy

- Pull all trades via Data API in pages of 500.
- Stop when an empty page is returned OR when oldest trade in page is > 120 days old (we only need 90 days for the gate; cushion).
- Polite rate limit: 0.2s sleep between pages. No retry — failures crash with a clear error.
- Cache raw responses to `state/research/bonereaper/raw_trades_<utc-date>.json` so re-runs don't re-fetch.

For market resolution lookup:
- Distinct slugs from filtered trades → query Gamma API per slug (concurrent, max 8 in flight).
- Cache resolution responses to `state/research/bonereaper/markets_<utc-date>.json`.

## 6. Outputs

| Path | Purpose |
|---|---|
| `runbooks/study/quick-audit.html` | Self-contained HTML report with embedded matplotlib PNGs (base64) — open in any browser |
| `runbooks/study/preflight-decision.md` | Plain-language pass/fail with measured numbers |
| `state/research/bonereaper/raw_trades_<date>.json` | Cached API response |
| `state/research/bonereaper/markets_<date>.json` | Cached market metadata |
| `state/research/bonereaper/labelled_audit.parquet` | Per-trade labelled dataset (subset of Phase D output) |

`runbooks/gate-evidence/study-A.txt` is the gate command output (see §8).

## 7. Pass/fail logic — the abort gate

Per BONEREAPER_STUDY.pdf p. 9:

```
GATE = (
    rolling_30d_winrate_btc5m >= 0.60
    AND total_btc5m_trades_observable >= 500
    AND volume_30d_change_pct > -0.40   # not more than 40% MoM drop
)
```

If `GATE == True`: write `preflight-decision.md` with PROCEED + measured numbers; exit 0.
If `GATE == False`: write `preflight-decision.md` with ABORT + which criteria failed + measured numbers; exit 1. Phase B is not designed.

## 8. Gate command

`bash runbooks/gates/study-A.sh` runs:
1. `make verify` (project lint/type/test still green)
2. `uv run python scripts/research/quick_audit.py` exit 0
3. Confirm output files exist
4. Tee combined output to `runbooks/gate-evidence/study-A.txt`

## 9. Risks / known gaps for Phase A

- **Fee approximation.** Net P&L treats fees as zero; tightens in Phase D.
- **Survivorship bias.** Bonereaper may be one wallet of a multi-wallet operator. Phase E adversarial check addresses; Phase A does not.
- **Pagination limit.** Data API may cap at 500/page. We probe; if more pages, we paginate.
- **Behavior-shift detection** is crude (2σ) — sufficient for an abort gate, refined in Phase E.
- **Out-of-sample drift.** Past 90 days may not represent the next 30 days. Edge-decay monitor (Phase I) is the long-term fix; Phase A only confirms historical existence of edge.

## 10. Anti-vibe rules followed

- Design doc committed before code (this file).
- Type hints + module docstring required by `runbooks/scripts/check_headers.py`.
- All HTTP calls behind a small `_api.py` adapter so unit tests can mock.
- Failure exits with non-zero status — no silent continuation.
- Caching keyed by UTC date → re-runs same day are deterministic.
- No `TODO`/`FIXME` markers; gaps tracked here in §9.

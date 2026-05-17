# Design — M.2 v0 Orderbook Imbalance Shadow-Log (Phase M Session 7)

> Purpose: at fire-decision time, compute the orderbook imbalance of the
> bot's chosen side (`bid_size_top / ask_size_top` of the UP or DOWN token)
> and ANNOTATE the fire rationale with the result. Bot firing behavior is
> UNCHANGED in v0. After 3-5 days, audit per-imbalance-class WR + $/tr
> to decide M.2 v1 (active gate or independent fire path).
>
> **Anti-vibe rule #1**: this doc lands before code in
> `src/polymarket_bot/strategies/spot_aware_v2_1.py`.
>
> **Anchors**:
> - `phase-prompts/phase-M-pre-live-edge-stacking-2026-05-16.txt` §C.M.2
> - `design/M.1a-flat-vs-trend-shadow-log.md` (parallel pattern: v0 shadow → audit → v1 active)
> - `design/M.5-path-a-regime-wrapper.md` (parallel surgical strategy patch)
> - Phase J.4 spec (orderbook imbalance — designed but never shipped before)

## 1. The hypothesis

When the top-of-book on the bot's side has `bid_size / ask_size > THRESHOLD`,
there are more limit-buyers waiting than limit-sellers — bullish for that
token. The token's price tends to drift UP (more buying pressure).

For the bot:
- Firing UP-token: want UP-token's bid > ask × THRESHOLD (= bullish for UP-token = price up = we win)
- Firing DOWN-token: want DOWN-token's bid > ask × THRESHOLD (= bullish for DOWN-token = price up = we win, since DOWN-token rising means the bot bet correctly)

Phase J.4 spec hypothesised THRESHOLD = 2.0. Empirically untested.

## 2. The labels (computed per fire-decision)

For the BookUpdate of the bot's chosen side at fire-time:

```
if (bid_size_top + ask_size_top) * book.best_ask < MIN_TOP_SIZE_USD:
    label = "too_thin"
elif ask_size_top <= 0:
    label = "no_ask"
elif bid_size_top / ask_size_top > THRESHOLD:
    label = "bullish"          # bid stack dominates; price expected to rise
elif ask_size_top / bid_size_top > THRESHOLD:
    label = "bearish"          # ask stack dominates; price expected to fall
else:
    label = "balanced"
```

Plus a special case:
```
if no BookUpdate has arrived for bot's side at fire-time:
    label = "no_book"          # shouldn't happen in practice; defensive
```

## 3. Hypothesis to validate (audit after 5 days)

Per-label WR + $/tr:

| label | n? | WR | $/tr |
|---|---|---|---|
| bullish | TBD | ≥ baseline +5pp? | ≥ baseline +$1? |
| bearish | TBD | ≤ baseline -5pp? | ≤ baseline -$1? |
| balanced | TBD | ≈ baseline | ≈ baseline |
| too_thin | TBD | high variance? | ? |
| no_ask | TBD | rare; should ≈ baseline | ? |

**M.2 v1 promote criteria:**
- "bearish" $/tr ≤ baseline − $1.00 (95% Wilson CI) AND n_bearish ≥ 50 → abstain-on-bearish
- "bullish" $/tr ≥ baseline + $1.00 → unchanged firing (continue stacking)
- If both: differential gate (abstain bearish; fire bullish with possibly elevated Kelly)

## 4. Public surface (v0 — shadow only)

### 4.1 Strategy changes in `spot_aware_v2_1.py`

Two new constructor kwargs:
```python
imbalance_shadow_enabled: bool = False,
imbalance_threshold: float = 2.0,
imbalance_min_top_size_usd: float = 50.0,
```

Two new pieces of state (parallel to existing `_best_ask_for_side`):
```python
self._bid_size_for_side: dict[Side, float] = {}
self._ask_size_for_side: dict[Side, float] = {}
self._best_bid_for_side: dict[Side, float] = {}
```

In `on_event` when BookUpdate arrives, populate these dicts alongside `_best_ask_for_side` (which is v2's responsibility — we add parallel tracking without breaking v2's existing flow).

Actually v2's `_on_book` already sees the BookUpdate. We can override `_on_book` in v2.1 to capture additional fields. Or — simpler — read `_best_ask_for_side`'s parallel via a stored last-BookUpdate-per-side reference.

**Chosen approach**: override `on_event` so that when we see a BookUpdate, we additionally store `_last_book_for_side[event.side] = event` BEFORE delegating to super().

In `_maybe_fire` after `side_guess` is computed:
```python
imbalance_label: str | None = None
if self._imbalance_shadow_enabled:
    book = self._last_book_for_side.get(side_guess)
    imbalance_label = _compute_imbalance_label(
        book, self._imbalance_threshold, self._imbalance_min_top_size_usd
    )
```

At rationale-construction time (just before the existing `regime=` annotation):
```python
if imbalance_label is not None:
    new_rationale = f"{new_rationale} imbalance={imbalance_label}"
```

### 4.2 Helper function (in strategy module)

```python
def _compute_imbalance_label(
    book: BookUpdate | None,
    threshold: float,
    min_top_size_usd: float,
) -> str:
    if book is None:
        return "no_book"
    bid_size = book.bid_size_top or 0.0
    ask_size = book.ask_size_top or 0.0
    # Top-of-book USD = (bid_size + ask_size) × midprice (approx with best_ask)
    if (bid_size + ask_size) * (book.best_ask or 0.0) < min_top_size_usd:
        return "too_thin"
    if ask_size <= 0:
        return "no_ask"
    ratio = bid_size / ask_size
    if ratio > threshold:
        return "bullish"
    if 1.0 / ratio > threshold:
        return "bearish"
    return "balanced"
```

## 5. Wiring (`scripts/run_paper.py`)

Three new env vars:
| name | default | role |
|---|---|---|
| `ORDERBOOK_IMBALANCE_SHADOW_ENABLED` | `false` | DARK ship master switch |
| `ORDERBOOK_IMBALANCE_THRESHOLD` | `2.0` | bid/ask ratio threshold |
| `ORDERBOOK_MIN_TOP_SIZE_USD` | `50.0` | filter thin books |

Logged at startup as INFO/WARNING (WARNING when enabled).

## 6. Tests (target ≥7 in `tests/strategies/test_spot_aware_v2_1.py`)

| # | test | scenario |
|---|---|---|
| 1 | `test_m2_shadow_disabled_no_rationale_change` | env off → rationale has no `imbalance=` |
| 2 | `test_m2_shadow_bullish_label` | bid_size=300, ask_size=100, threshold=2.0 → `imbalance=bullish` |
| 3 | `test_m2_shadow_bearish_label` | bid_size=100, ask_size=300 → `imbalance=bearish` |
| 4 | `test_m2_shadow_balanced_label` | bid=100, ask=120 → `imbalance=balanced` |
| 5 | `test_m2_shadow_too_thin_label` | bid+ask × ask < min_size_usd → `imbalance=too_thin` |
| 6 | `test_m2_shadow_no_book_label` | bot fires before any BookUpdate arrives → `imbalance=no_book` (defensive) |
| 7 | `test_m2_shadow_does_not_change_fire_decision` | with imbalance=bearish (would be drag), fire still happens (no abstain in v0) |

## 7. Promote gate (M.2 v0 → M.2 v1)

After 3-5 days of v0 production with `ORDERBOOK_IMBALANCE_SHADOW_ENABLED=true`:

1. Run `scripts/research/audit_imbalance_shadow.py` (future) — per-label rollup
2. If `bearish` $/tr is meaningfully worse than baseline AND n_bearish ≥ 50:
   ship M.2 v1 with `imbalance_abstain_labels={"bearish"}` (mirrors M.1a v1's CSV abstain set)
3. If `bullish` is meaningfully better, leave firing unchanged but note the alpha
4. If no signal: log finding, shelve M.2

## 8. Rollback

`env-flip ORDERBOOK_IMBALANCE_SHADOW_ENABLED=true → false` + restart. 30s.

## 9. Honest pushback

- **P1** — `bid_size_top / ask_size_top` is TOP-OF-BOOK only. Deeper book context (level 2 depth) would be more informative. Phase J.4 v0 only has top-of-book per the data plane. Future: M.2.b consumes L2 depth.

- **P2** — Threshold 2.0 is a hypothesis from Phase J.4 spec, unvalidated. May need tuning per the audit. v0 logs the RATIO too (not just label) so we can re-classify retrospectively at any threshold.

- **P3** — Imbalance can be FAKE (spoofing). Polymarket has CTF-redeemed orders; less spoofing than Binance, but still possible. v0 logs imbalance and observes; doesn't assume causation.

- **P4** — The bot's own pending limit orders may bias the book. If we have a $50 bid sitting at 0.40, the book at 0.40 looks more bid-loaded than the market actually is. Mitigation: deduct our own bid/ask from book sizes. v0 ignores this (orderbook is computed at fire-decision time BEFORE our order goes in, so it's clean for that fire).

- **P5** — The imbalance signal is ORTHOGONAL to spot-Δ (which is price-direction) and regime (which is volatility-regime). All three can stack — M.1a v1 + M.5 + M.2 v1 could combine into a 3-gate filter. Or they could be redundant. v0's audit answers this via independence test: `|corr(spot_delta, imbalance)| < 0.5` required for "independent edge".

- **P6** — Adding imbalance state-tracking increases per-event compute (writing to two more dicts). Negligible in absolute terms (~5 µs per BookUpdate). Profiling would catch any drift.

## 10. Out of scope (v1+)

- L2 depth-weighted imbalance (M.2.b)
- Imbalance momentum (Δ(bid/ask) over a 30s window)
- Combined imbalance × regime × spot-Δ gate (M.4 territory)

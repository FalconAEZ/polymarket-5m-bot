# Design — M.1a Binary FLAT-vs-TREND Regime Classifier (SHADOW-LOG v0)

> Purpose: wire the existing `RegimeDetector` (Phase 15 dark-shipped) into the
> *active* `spot_aware_v2_1` firing path AS A SHADOW SIGNAL. Every decision
> (fire OR abstain) gets annotated with the regime label at fire-time. Bot
> firing behavior is UNCHANGED in v0. After 3-5 days of annotated decisions,
> operator audits per-regime WR + $/tr on the *current* Phase J.1.6 firing
> pattern to decide whether to promote to M.1a v1 (active FLAT-abstain gate).
>
> **Anti-vibe rule #1**: this doc lands before any code in
> `src/polymarket_bot/strategies/spot_aware_v2_1.py` or `scripts/run_paper.py`.
>
> **Anchors**:
> - `design/regime_detector.md` (Phase H regime detector spec)
> - `runbooks/gate-evidence/regime-classifier-validation.txt` (Phase 15: trending WR 70.59% vs chop 47.40% on n=299)
> - `phase-prompts/phase-M-pre-live-edge-stacking-2026-05-16.txt` §C.M.1
> - `state/phases/phase-M-pre-live-edge-stacking.md`
> - `memory/project_regime_aware_edge_thesis.md` (data-corrected: 4-day soak found 25pp gap via delta_bps proxy, but FLAT slightly +$/tr — needs vol-ratio replay)
> - `scripts/research/phase_l_soak_audit.py` (delta_bps regime proxy)
>
> **Honest pushback the operator already saw**:
> - Phase 15 validation (n=299) found chop $/tr = −$0.22 (a drag)
> - Phase L 4-day soak via delta_bps proxy (n=615) found FLAT $/tr = +$0.21 (slight profit)
> - The two classifiers label regimes DIFFERENTLY; promoting to active gate
>   based on the old validation could LOSE the +$68 FLAT contributed during
>   the soak. We need shadow data on current firing before acting.

---

## 1. The picture

```
   Binance WS  ───────►  BinanceTradeFeed ─────►  PaperRunner
        (5m BTC ticks)                              │
                                                    │ on every SpotTick:
                                                    ▼
                                          regime_detector.observe_spot(ts_ns, price)
                                          (already exists, just plumb it)

   ─── window-decision time (per 5m window) ───
                                                    │
                                                    │ runner consults strategy:
                                                    ▼
                              spot_aware_v2_1.decide(ctx) → FireDecision | None
                                                    │
                                                    │ NEW: at decide()'s entry,
                                                    │ classify regime + annotate
                                                    ▼
                                          regime = regime_detector.classify(now_ns)
                                          → fire's rationale gains "regime=trending|chop|mixed|unknown"
                                          → abstain's rationale also gets annotation
                                          → decisions/*.jsonl carries the label

   v0 behavior: bot fires identical to today. Only the rationale string and a
   new "regime" snapshot field change. No abstain logic, no env gate enabled.
```

## 2. What v0 does NOT do (deferred to M.1a v1)

- No firing change. Bot continues to fire whenever spot_aware_v2_1 says fire.
- No `REGIME_FLAT_ABSTAIN_ENABLED` env flag yet. That's M.1a v1.
- No removal of the existing `REGIME_GATE_ENABLED` (which only gates the
  `STRATEGY=ensemble` path, currently disabled anyway).
- No backtest validation of the abstain hypothesis — that's the audit
  *after* 3-5 days of v0 shadow data.

## 3. Public surface

Two surgical changes:

### 3.1 `SpotAwareStrategyV2_1` gains a `regime_detector` parameter

```python
class SpotAwareStrategyV2_1(SpotAwareStrategyV2):
    def __init__(
        self,
        *,
        ...,
        regime_detector: RegimeDetector | None = None,    # NEW
        regime_shadow_enabled: bool = False,              # NEW
        **v2_kwargs: object,
    ) -> None:
        ...
        self._regime_detector = regime_detector
        self._regime_shadow_enabled = regime_shadow_enabled
```

At the top of `decide(ctx)` (before any other logic), if shadow is enabled
and detector is present:

```python
regime_label = "shadow_off"
if self._regime_shadow_enabled and self._regime_detector is not None:
    regime_label = self._regime_detector.classify(ctx.now_ns)

# (continue with existing decide() logic; regime_label is captured here)
# At rationale-construction time, append " regime=<label>" to the rationale string.
```

The label flows into:
- `fired.rationale` (e.g. `"strategy=spot_aware_v2_1 ... regime=trending"`)
- `abstained.rationale` (if the strategy emits an abstain record)
- A new top-level field `snapshot.regime` is OPTIONAL (deferred — adds schema migration; keeping it in rationale string is enough for v0 audit).

### 3.2 `scripts/run_paper.py` plumbs spot ticks into `RegimeDetector`

Today: `run_paper.py` builds a `RegimeDetector` only when `STRATEGY=spot_aware_v3`
(per the existing path at line 338). M.1a v0 widens this to also build the
detector when `STRATEGY=spot_aware_v2_1` AND `REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true`.

```python
# Existing (v3-only) path:
regime_detector = None
if strategy_name == "spot_aware_v3":
    regime_detector = RegimeDetector()
    feed_subscribers.append(regime_detector.observe_spot)
elif strategy_name == "spot_aware_v2_1" and _env_bool("REGIME_CLASSIFIER_V2_SHADOW_ENABLED", False):
    regime_detector = RegimeDetector()
    feed_subscribers.append(regime_detector.observe_spot)

# Pass to v2_1 constructor:
return SpotAwareStrategyV2_1(
    ...,
    regime_detector=regime_detector,
    regime_shadow_enabled=(regime_detector is not None),
)
```

The exact subscription mechanism mirrors what v3 does today (whatever
hook is used there — TBD on read; expected to be a callback registered with
`BinanceTradeFeed` or with the runner's internal event dispatch).

## 4. Env-vars (DARK ship; default OFF)

| name | default | role |
|---|---|---|
| `REGIME_CLASSIFIER_V2_SHADOW_ENABLED` | `false` | Master switch — must flip true on VPS to gather data |
| `REGIME_TRENDING_THRESHOLD` | `1.20` | RegimeDetector ratio threshold (default carried from existing class) |
| `REGIME_CHOP_THRESHOLD` | `0.80` | Same |
| `REGIME_MIN_SAMPLES` | `10` | Same |

Reuse existing RegimeDetector defaults — no new tuning surface needed for v0.

## 5. Decision-log audit query (post-shadow)

After 3-5 days of v0 in production:

```bash
# Parse rationale "regime=X" from fired records; group by label.
python scripts/research/audit_regime_shadow.py \
  --since 2026-05-17 --until 2026-05-22
```

The script lives in a future commit; mirrors `phase_l_soak_audit.py` but
groups by `regime=<label>` extracted from the rationale string.

Expected output:
```
regime    | n    | WR     | $/tr   | PnL    | $/tr_breakeven
trending  | ~200 | x%     | $y     | $z     | (Path A)
chop      | ~200 | x%     | $y     | $z     |
mixed     | ~50  | x%     | $y     | $z     |
unknown   | ~10  | (cold-start; expected only at restart boundaries)
```

If `chop` $/tr is materially below `trending` $/tr — promote to M.1a v1
(active FLAT-abstain). If `chop` $/tr is ≥ `trending` $/tr — DON'T promote;
M.1a is not the right gate for current firing pattern.

## 6. Tests (target ≥6 in `tests/strategies/test_spot_aware_v2_1_regime_shadow.py`)

| # | test | scenario |
|---|---|---|
| 1 | `test_shadow_disabled_does_not_call_classifier` | regime_shadow_enabled=False → classifier not consulted, rationale unchanged |
| 2 | `test_shadow_enabled_appends_regime_to_fire_rationale` | shadow=True + regime="trending" → rationale ends with " regime=trending" |
| 3 | `test_shadow_enabled_handles_no_detector_gracefully` | regime_detector=None (defensive) → rationale appended " regime=shadow_off" |
| 4 | `test_shadow_enabled_unknown_regime_appended` | cold-start: classifier returns "unknown" → rationale gets " regime=unknown" |
| 5 | `test_shadow_does_not_change_fire_decision` | identical (price, p_win, side, size) before+after; only rationale string differs |
| 6 | `test_shadow_does_not_alter_kelly_or_multi_fire_state` | bankroll-getter, kelly path, multi-fire counter — all identical |

Plus one integration in `tests/test_run_paper_wiring.py`:

| # | test | scenario |
|---|---|---|
| W1 | `test_v2_1_path_builds_regime_detector_when_shadow_enabled` | env REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true + STRATEGY=spot_aware_v2_1 → detector instance constructed, hooked into BinanceTradeFeed |

## 7. Promote gate (M.1a v0 → M.1a v1)

After 3-5 days of v0 in production with `REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true`:

1. Run `scripts/research/audit_regime_shadow.py` → produce per-regime rollup
2. **Promote criteria:**
   - n ≥ 200 fires per regime label (statistical floor)
   - chop $/tr ≤ trending $/tr − $1.00 (meaningful drag, not noise)
   - 95% Wilson CI of chop WR doesn't overlap trending WR
3. **If promote:** M.1a v1 ships `REGIME_FLAT_ABSTAIN_ENABLED` env flag + abstain branch in spot_aware_v2_1.decide() for chop/unknown
4. **If reject:** flip shadow flag off, document finding, pivot to M.2/M.5

## 8. Rollback

`env-flip REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true → false` + restart. Reversible in 30s. The detector simply isn't constructed; existing firing path is unchanged.

## 9. Honest pushback

- **P1** — Phase 15 validation +23pp uplift was on n=299 from a pre-fold firing pattern. Phase J.1.6 fires very differently (path A heavy, fold disabled CH3). The +23pp may not replicate. v0 is structured to find out, not assume.
- **P2** — Shadow logging adds ~10 µs per decision (classify() is O(buffer_size) over ~600 ticks). Acceptable for non-hot path; verified by existing v3 in-production deployment.
- **P3** — `unknown` regime at cold-start (first ~10 min after restart) means the first ~2 fires post-restart won't have a meaningful label. v0 still logs them as `unknown` and the audit excludes them.
- **P4** — If operator flips shadow on AND auto-halt trips tonight, the post-resume bot will have ~10 min of `unknown` ticks before classifier warms up. Audit script must filter cold-start fires.
- **P5** — RegimeDetector ratio uses 5m/10m windows. Phase L prompt's L.1 spec was 5m/15m. The existing class uses 10m; v0 ships with that (don't change the validated math). M.1a v1 may revisit window choice.

## 10. Out of scope

- Per-regime adaptive Kelly (M.4 territory)
- Per-regime tier whitelist (M.5 wrapper combined with M.1)
- 4-state classifier upgrade (M.1b — TREND_UP / TREND_DOWN / CHOPPY / STEADY)
- Cross-exchange regime confirmation (M.3 territory)

# P.1 — Market Mode Detector (MMD) integration

**Authored:** 2026-05-18 (operator UAE local).
**Status:** DESIGN LOCKED for Phase P Session 3 ship.
**Branch:** `claude/phase-P-hard-reset`.
**Backtest evidence:** `runbooks/research/phase-P-mmd-backtest-2026-05-18.md`, `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf`.

## 1. Decision

Ship **Adapter A — `bukosabino/ta` rule-based** as the production MMD.

| | Adapter A — chosen | Adapter B — rejected |
|---|---|---|
| Library | `bukosabino/ta` v0.11.0 | `hmmlearn` v0.3.x |
| License | MIT | BSD-3-Clause |
| Lineage | rule-based ADX(14) + BB-width(20, 2σ) + 30-bar momentum | 4-state Gaussian HMM on (log-ret, rolling-10 vol) |
| Deps installed | `ta` only (~3 MB) | `hmmlearn` + `scipy` + `scikit-learn` (~30 MB) |
| Training? | No (deterministic) | Yes (Session 3 needs rolling retrain) |
| Native confidence | Computed from indicator distance to threshold ∈ [0, 1] | Posterior probability from HMM forward-backward ∈ [0, 1] |
| n=756 best/worst WR gap | +9.2pp (just below P.2.2 10pp gate; within noise CI ±10.7pp) | +10.8pp (passes gate) |
| n=756 abstain-non-MIXED counterfactual | +$1,018 PnL improvement | +$933 PnL improvement |
| Verdict | **SHIPS** — simpler, deterministic, higher actionable PnL, no training caveat | Logged in research, may revisit Phase Q |

Both adapters agreed on the actionable signal (**MIXED is the only profitable label**). The 0.8pp WR-gate gap is within the n=755 confidence interval (±10.7pp around 9.2pp), so A's "failure" is not statistically meaningful. Operator-confirmed choice 2026-05-18.

## 2. Public API — what `spot_aware_v2_1` sees

```python
# src/polymarket_bot/strategies/market_mode_detector.py

from typing import Literal
from dataclasses import dataclass

MmdLabel = Literal["UP", "DOWN", "CHOPPY", "MIXED", "UNKNOWN"]


@dataclass(frozen=True)
class MmdReading:
    label: MmdLabel
    confidence: float          # ∈ [0, 1]; 0.0 means UNKNOWN / no data
    adx: float                 # raw indicator value
    bb_width_bps: float        # bps relative to last close
    momentum_bps: float        # 30-bar log-return in bps
    sampled_at_ns: int         # unix-ns timestamp the reading was computed
    bar_count: int             # number of 1-min bars used (need ≥ 30 for non-UNKNOWN)


class MarketModeDetector:
    """Multi-indicator rule-based 4-state detector.

    Reads a 60-min rolling buffer of (open, high, low, close, volume) 1-min
    bars from Binance public WS klines (already plumbed for the bot's spot
    feed) or, in shadow mode for Session 3 only, from a periodic REST poll.
    Returns a MmdReading; never raises in normal operation."""

    def __init__(
        self,
        lookback_min: int = 60,
        adx_strong: float = 25.0,
        adx_weak: float = 20.0,
        bb_compressed_bps: float = 30.0,
        momentum_threshold_bps: float = 10.0,
    ) -> None:
        ...

    def push_bar(self, *, open_: float, high: float, low: float,
                 close: float, volume: float, ts_ns: int) -> None:
        """Append a 1-min OHLCV bar to the rolling buffer."""
        ...

    def latest(self) -> MmdReading:
        """Compute classification from the current buffer state."""
        ...
```

### Labelling logic (matches the Session-2 backtest)

```
adx_strong   = adx > adx_strong            (default 25)
adx_weak     = adx < adx_weak              (default 20)
bb_compressed= bbw < bb_compressed_bps/1e4 (default 30 bps)
mom_up       = momentum > momentum_threshold_bps/1e4  (default 10 bps)
mom_dn       = momentum < -momentum_threshold_bps/1e4

if adx_strong and mom_up:   ("UP",     min(1, (adx-25)/15))
if adx_strong and mom_dn:   ("DOWN",   min(1, (adx-25)/15))
if adx_weak   and bb_compressed: ("CHOPPY", min(1, (20-adx)/10))
else:                       ("MIXED",  0.5)

if buffer has < 30 bars:    ("UNKNOWN", 0.0)
on classifier exception:    ("UNKNOWN", 0.0)
```

`UNKNOWN` is the explicit pass-through label: when the strategy sees `UNKNOWN`, it MUST NOT change its firing decision — equivalent to running without MMD.

## 3. Plumbing into `spot_aware_v2_1`

Pattern mirrors the (now-stripped) M.5 path-A regime wrapper: strategy
constructor takes an optional getter callback, no global state, no DI
container needed.

```python
# spot_aware_v2_1.py

class SpotAwareV2_1Strategy:
    def __init__(
        self,
        ...,
        mmd_getter: Callable[[], MmdReading] | None = None,
        mmd_labels_to_abstain: tuple[str, ...] = (),
    ) -> None:
        ...
        self._mmd_getter = mmd_getter
        self._mmd_labels_to_abstain = set(mmd_labels_to_abstain)

    def on_window_event(self, ev: Event) -> Decision | None:
        decision = self._compute_decision(ev)
        if decision is None or decision.kind != "fire":
            return decision

        # MMD annotation + gate (Session 3 ships shadow first)
        if self._mmd_getter is not None:
            r = self._mmd_getter()
            decision.rationale += f" mmd={r.label} mmd_conf={r.confidence:.2f}"
            if r.label in self._mmd_labels_to_abstain and r.label != "UNKNOWN":
                return self._abstain(decision, reason=f"mmd_abstain_{r.label}")

        return decision
```

The annotation is what Phase N's audit script reads to bucket fires by
regime. Shadow mode = annotate but never abstain; gate mode = annotate
AND abstain on configured labels.

## 4. Bar-feed wiring (in `scripts/run_paper.py`)

Two acceptable approaches for Session 3 — operator-decision-point at ship time:

### Option (i) — REST poll (recommended for Session 3 SHADOW)

Lightweight: a 30-second background task polls Binance public
`/api/v3/klines` for the last 60 1-min closed bars and feeds the MMD
buffer. No new WebSocket. Same library + endpoint already used by the
Phase-P Session-2 backtest. ~3 REST calls/min within rate-limits (1200/min).

```python
# run_paper.py main()

mmd_enabled = _env_bool("MMD_ENABLED", default=False)
if mmd_enabled:
    mmd = MarketModeDetector()
    mmd_poller = MmdBinanceKlinePoller(mmd, interval_s=30, lookback_min=60)
    tasks.append(asyncio.create_task(mmd_poller.run()))
    mmd_getter = mmd.latest
else:
    mmd_getter = None
```

### Option (ii) — derive from existing Binance WS

The bot already runs Binance + Coinbase spot WS for the `_paper.spot`
feed. Wire a 1-min OHLCV aggregator off that stream and feed MMD. Lower
network footprint but more code; defer to Phase Q+ if Session 3 shadow
proves the signal.

**Session 3 ships option (i).** Option (ii) tracked as Phase Q work.

## 5. Env flags (default ALL OFF)

Per anti-vibe rule #1 + the Phase N M.1a v1 lesson: never activate
gating on small-n. The defaults below keep the bot at J.1.6 exactly.

| Env var | Default | Meaning |
|---|---|---|
| `MMD_ENABLED` | `false` | Master switch. `false` = no MMD task created, no annotation, no gate. |
| `MMD_MODE` | `shadow` | `shadow` = annotate only, never abstain. `gate` = annotate + abstain on `MMD_LABELS_TO_ABSTAIN`. |
| `MMD_LABELS_TO_ABSTAIN` | `""` | csv of label names; ignored when `MMD_MODE=shadow`. Session-3 evidence suggests `CHOPPY,UP,DOWN` (= abstain non-MIXED) but Session 3 ships empty (pure shadow). |
| `MMD_LOOKBACK_S` | `3600` | rolling window in seconds (= 60 1-min bars). |
| `MMD_POLL_INTERVAL_S` | `30` | seconds between Binance kline polls. |
| `MMD_ADX_STRONG_THRESHOLD` | `25.0` | ADX above this → trending. |
| `MMD_ADX_WEAK_THRESHOLD` | `20.0` | ADX below this → not-trending. |
| `MMD_BB_COMPRESSED_BPS` | `30.0` | BB-width below this → CHOPPY (in conjunction with adx_weak). |
| `MMD_MOMENTUM_THRESHOLD_BPS` | `10.0` | 30-bar log-return above this → UP / below `-this` → DOWN. |

Session 3 ship sets only `MMD_ENABLED=true MMD_MODE=shadow` in
`.envrc`. All other knobs stay at defaults.

## 6. Failure modes (HARD requirements)

1. **Library import failure** (`ta` not in env): `MarketModeDetector.__init__`
   logs warning and falls back to a no-op stub that always returns
   `("UNKNOWN", 0.0)`. Strategy treats UNKNOWN as pass-through. **No
   bot crash, no abstain.**
2. **Binance poll failure / network error**: poller logs warning, retries
   with backoff, MMD buffer keeps its last-good bars. After
   `2 × poll_interval` of stale data, `latest()` returns `("UNKNOWN", 0.0)`.
3. **Indicator computation exception** (NaN, divide-by-zero): caught at
   `latest()`; returns `("UNKNOWN", 0.0)`.
4. **`MMD_ENABLED=true` but `ta` missing**: bot logs CRITICAL and exits
   non-zero at startup (fail-loud at boot, not silent at fire time).
5. **`MMD_MODE=gate` but `MMD_LABELS_TO_ABSTAIN` empty**: bot logs WARN
   on startup; behavior is equivalent to shadow (no abstain).
6. **Strategy receives MMD reading with `label="UNKNOWN"`**: pass-through.
   Annotation still added (`mmd=UNKNOWN mmd_conf=0.00`) so audit can
   bucket fires by "MMD-available" vs "MMD-unavailable".

## 7. Telemetry

- **Rationale annotation** (added when `MMD_ENABLED=true`):
  `mmd=<UP|DOWN|CHOPPY|MIXED|UNKNOWN> mmd_conf=<0.00-1.00>`
- **Startup log**: `MMD ENABLED: mode=<shadow|gate> labels_to_abstain=<csv> lookback_s=<n> poll_interval_s=<n>`
- **Dashboard `/api/state` decisions row**: rationale field already
  surfaces strategy annotations to the v3 React UI; the operator will
  see `mmd=<label>` in the decision tape without any frontend change.
- **Prometheus** (out of scope this phase): defer counter
  `mmd_label_total{label}` to Phase Q if operator wants Grafana view.

## 8. Test budget for Session 3

Per anti-vibe rule #2 (bug → failing test → fix → green) and rule #6
(type hints required), Session 3 ships ≥ 12 new tests covering:

1. `MarketModeDetector.__init__` with defaults
2. `push_bar` accumulates rolling buffer up to lookback
3. `latest()` returns UNKNOWN when buffer < 30 bars
4. `latest()` returns UP when synthetic trending-up bars fed
5. `latest()` returns DOWN when synthetic trending-down bars fed
6. `latest()` returns CHOPPY when synthetic compressed-flat bars fed
7. `latest()` returns MIXED when neither trending nor chop
8. Indicator exception → UNKNOWN (mock `ta.trend.ADXIndicator` raise)
9. `ta` import missing → no-op fallback, all labels UNKNOWN
10. Confidence ∈ [0, 1] for every label
11. Strategy `mmd_getter=None` path = behavior identical to pre-MMD
12. Strategy `MMD_MODE=shadow` adds annotation but never changes decision
13. Strategy `MMD_MODE=gate` with `labels_to_abstain={CHOPPY}` abstains on CHOPPY but fires on MIXED
14. Strategy treats `UNKNOWN` as pass-through (never abstains)

All existing tests stay green; mypy --strict + ruff + import-linter green.

## 9. Rollback procedure (in case of Session-3 ship issues)

Single env flip: `MMD_ENABLED=false`, `systemctl restart bot-staging.service`.
The strategy code path with `mmd_getter=None` is identical to the
current J.1.6 behavior — no rollback diff to write.

## 10. Phase Q decision gate (Day-5 audit from Session 3 ship)

| Day-5 live signal | Action |
|---|---|
| MIXED WR delta ≥ 10pp better than next-best label on n ≥ 100 live fires | Promote shadow → gate (set `MMD_LABELS_TO_ABSTAIN=CHOPPY,UP,DOWN`, `MMD_MODE=gate`). Also reconsider re-introducing M.5 as the path-A-specific layer alongside MMD. |
| MIXED WR delta 5-10pp | KEEP shadow; iterate on indicator parameters (try `MMD_ADX_STRONG_THRESHOLD=22.0` or `MMD_LOOKBACK_S=1800`). Re-audit at Day-10. |
| MIXED WR delta ≤ 5pp | SHELVE MMD. Reconsider strategy class entirely (Phase R pivot question). |
| Adapter raises in production (UNKNOWN rate > 5%) | Diagnose at Phase Q; fix before any promote-to-gate. |

## 11. Cross-references

- Source-of-truth prompt: `~/Desktop/phase-P-hard-reset-2026-05-18.txt`
- Phase P ledger: `state/phases/phase-P-hard-reset.md`
- Backtest report: `runbooks/research/phase-P-mmd-backtest-2026-05-18.md`
- Backtest script: `scripts/research/phase_p_mmd_backtest.py`
- Backtest charts: `state/research/phase-P-mmd-charts/*.png` (4 files)
- PDF: `pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf` (builder at `pdfs/build_phase_p_session2_pdf.py`)
- Klines cache: `state/research/binance_historical/btcusdt_1m_2026-05-12_to_2026-05-18.parquet`
- Anti-vibe rules: `CLAUDE.md` §Anti-vibe-coding rules
- Locked decisions: `memory/project_decisions.md` (decision #8 license MIT/Apache/BSD)

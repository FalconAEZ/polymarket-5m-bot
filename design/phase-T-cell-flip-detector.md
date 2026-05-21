# design/phase-T-cell-flip-detector — SURV-style cell-flip abstain

**Phase:** T (directional revival), Improvement #2 — **the actual killer** per Phase N forensic.
**Author:** 2026-05-21.
**Status:** locked (design only; this commit ships design + scaffolding hook, NOT the implementation — implementation is the next commit in a fresh session).
**Anti-vibe rule #1:** this doc precedes the src/ change.

---

## §1. Why this is the highest-priority improvement

From [runbooks/research/phase-N-forensic-summary.md:31-42](../runbooks/research/phase-N-forensic-summary.md):

> The peak-to-floor swing of −$1,562 is **dominated by ONE failed cell** — tier 30-50% × |Δbps|≥5 (the SURV cell from Phase L) flipping from a 60.7% WR profit-engine to a 46.5% WR bleeder right at the 2026-05-15 15:40Z peak.

| Period | n | WR | $/tr | PnL |
|---|---:|---:|---:|---:|
| SURV pre-peak | 112 | 60.7% | +$12.78 | +$1,431 |
| SURV post-peak | 228 | 46.5% | −$5.09 | −$1,161 |
| **Swing** | +116 | **−14.2pp** | **−$17.87** | **−$2,592** |

**A static blocklist (Improvement #1) can't catch this** — the SURV cell was PROFITABLE before the flip; blocking it pre-emptively would have lost the +$1,431. The only mechanism that catches a regime shift mid-flight is a *rolling* per-cell WR signal with an abstain trigger.

Expected lift from this improvement (per Phase N M.5 activation simulator §4 of the forensic): **$800-$1,000 of the $1,562 swing prevented** if detector activates within 10-15 fires of the regime shift. This dwarfs Improvement #1's ~$1,748 over 5 days because it addresses the *catastrophic-tail* event, not just steady-state hour bleeds.

## §2. The detector — pure logic

```python
@dataclass(slots=True)
class CellFlipDetector:
    """Stateless detector. Given recent fires for a cell + the current
    fill price, decide whether the cell should abstain because rolling
    WR has dropped below break-even by more than a tolerance.

    Break-even for a binary 0/1 settlement at fill_price p is exactly p:
    a fire wins +(1-p) and loses -p, expected = WR*(1-p) - (1-WR)*p =
    WR - p. So EV > 0 iff WR > p (= break_even). The detector abstains
    when rolling_wr < (break_even - abstain_threshold_pp/100), giving
    a `abstain_threshold_pp` margin for noise.
    """

    window_size: int = 20         # rolling N fires per cell
    abstain_threshold_pp: float = 5.0  # abstain if rolling_wr < BE - 5pp
    min_samples: int = 10         # don't abstain below this n (noise floor)

    def should_abstain(
        self,
        *,
        fill_price: float,
        recent_wins: Sequence[bool],
    ) -> tuple[bool, str]:
        """Return (abstain, reason). Reason is empty when not abstaining
        (caller logs it into the rationale string when abstain=True)."""
        n = len(recent_wins)
        if n < self.min_samples:
            return (False, "")
        window = recent_wins[-self.window_size:]
        rolling_wr = sum(window) / len(window)
        break_even = fill_price
        threshold = break_even - self.abstain_threshold_pp / 100.0
        if rolling_wr < threshold:
            return (True, f"cell_flip:rolling_wr={rolling_wr:.3f}<be={break_even:.3f}-{self.abstain_threshold_pp:.0f}pp")
        return (False, "")
```

Pure logic, no I/O, no time dependency. Trivially testable.

## §3. Cell-key formula

The audit's "SURV cell" = tier `30-50%` × `|Δbps| ≥ 5`. The Phase N forensic uses two |Δbps| buckets per tier:
- `lo` : `|Δbps| < 5`
- `hi` : `|Δbps| ≥ 5`

Cell-key = `f"{tier}|{bucket}"` where bucket ∈ {`lo`, `hi`}. Examples: `30-50%|hi` (= SURV), `30-50%|lo` (= CH3 cell), `70-85%|hi` (= Path A).

This matches the audit granularity exactly. Finer-grained buckets (e.g. 5 |Δ| bins per tier) would split the n too thin for rolling-20 to work; coarser (just tier) would lump CH3 and SURV together which is wrong.

At fire time, the strategy already computes both `tier` and `d_bps` ([spot_aware_v2_1.py:407-420](../src/polymarket_bot/strategies/spot_aware_v2_1.py)). The cell-key extraction is one line:
```python
cell_key = f"{tier}|{'hi' if abs(d_bps) >= 5 else 'lo'}"
```

## §4. State management — where does the rolling history live?

**Decision:** the history lives in a new `CellFireHistory` tracker class, owned by `PaperRunner`, **not** the strategy. Mirrors how `BankrollTracker` works at [runner.py:174](../src/polymarket_bot/_paper/runner.py) — single source of truth, strategy reads via callback.

### Why not in the strategy

- Strategies are recreated on restart with fresh state. Without persistence the rolling window resets every time.
- The runner already has the settle pipeline ([runner.py:944](../src/polymarket_bot/_paper/runner.py) `self._bankroll.apply_settle(pnl)`). Adding `self._cell_history.apply_settle(cell_key, won)` one line below is the minimal-surface change.
- The strategy's job is to make a decision given context; tracking outcomes is an orthogonal concern.

### Persistence — Phase T scope

The `BankrollTracker` uses a startup replay from the decision log ([runner.py:266](../src/polymarket_bot/_paper/runner.py)). `CellFireHistory` does the same: on init, walks `state/decisions/<today>.jsonl` filtering `settled` records, extracts cell-key from each, and seeds the per-cell deques. Cell-key must therefore be **persisted into the decision-log JSONL** at fire time so the replay can recover it.

This means **Improvement #2 ships in two parts**:
1. **Part A (this commit, design only):** the design doc + scaffolding. Future implementation work locked in.
2. **Part B (next commit, fresh session):** the actual code — `CellFlipDetector` class, `CellFireHistory` tracker, decision-log schema bump to include `cell_key`, runner integration, strategy hook, tests.

Splitting forces clean review and avoids cramming a non-trivial change into the tail of an already-long session.

## §5. Integration point — where in the strategy

`SpotAwareStrategyV2_1._maybe_fire()` already has a gate chain at [spot_aware_v2_1.py:390-405](../src/polymarket_bot/strategies/spot_aware_v2_1.py):
1. J.2 hour-blocklist (Phase T #1 just landed)
2. H.2.12 path-A side block
3. (super() flow: CH1-CH4 + Kelly)

Cell-flip detector slots in **after** J.2 + H.2.12 but **before** super() — same pattern. Pseudocode:

```python
# Phase T Improvement #2 — cell-flip detector
if self._cell_flip_detector is not None and self._recent_wins_getter is not None:
    cell_key = f"{tier}|{'hi' if abs(d_bps) >= 5 else 'lo'}"
    fill_price = ask_guess
    recent_wins = self._recent_wins_getter(cell_key)
    abstain, reason = self._cell_flip_detector.should_abstain(
        fill_price=fill_price,
        recent_wins=recent_wins,
    )
    if abstain:
        LOG.info("cell-flip abstain: cell=%s %s", cell_key, reason)
        return None
```

Empty `_recent_wins_getter` → returns `[]` → `n < min_samples` → never abstains. **Same shipping pattern as Improvement #1: structure first, value (= operator wiring the runner-side tracker) second.** Zero behavior change at default config.

## §6. Tests required (for Part B implementation)

### Unit tests for `CellFlipDetector` (pure logic, ~6 tests):
1. `test_below_min_samples_never_abstains` — n=5, all losses, no abstain
2. `test_above_break_even_no_abstain` — n=20, WR=70%, fill_price=0.50 → no
3. `test_below_break_even_within_threshold_no_abstain` — n=20, WR=46%, fill_price=0.50, threshold=5pp → 46% > 45% threshold, no abstain
4. `test_below_break_even_beyond_threshold_abstains` — n=20, WR=40%, fill_price=0.50, threshold=5pp → 40% < 45%, abstain
5. `test_rolling_window_drops_old_data` — n=30 with first 10 losses + last 20 wins; window=20 → uses only the 20 wins → no abstain
6. `test_reason_string_machine_parseable` — abstain case produces reason matching regex `cell_flip:rolling_wr=\d\.\d+<be=\d\.\d+`

### Integration test reproducing SURV flip (~1 test):
7. `test_v2_1_cell_flip_catches_surv_regression` — drive the strategy through a synthetic sequence:
    - 50 fires on cell `30-50%|hi` with WR=60% (priming)
    - Then a window of 20 fires with WR=40% (the flip)
    - Assert: at some point within the 20-fire flip window, fires start abstaining
    - Assert: when the cell recovers (WR climbs back), abstain releases

### Backtest validation (separate script, optional Part B+):
- Replay Phase N forensic data through the detector; verify that the detector activates between fire #445 (peak) and ~#460 (within 10-15 fires per the F3 spec), preventing $800-$1,000 of the post-peak bleed.

## §7. Decision-log schema bump

Decision-log JSONL records currently include `tier`, `d_bps`, etc. but no explicit `cell_key`. To enable replay on restart:

```python
# When recording a fire:
record = {
    ..., "cell_key": f"{tier}|{'hi' if abs(d_bps) >= 5 else 'lo'}",
}
# When recording a settle:
# The runner already knows the settled decision_id; lookup its cell_key
# from the fire record (or denormalize: include cell_key in the settle
# record too — cheaper to store than to JOIN at replay).
```

Schema bump is BACKWARDS COMPATIBLE: existing records without `cell_key` are ignored at replay (treated as no prior history for that cell). New records include it.

## §8. What this commit (Part A) ships

Just this design doc. **No src/ change. No tests.** The implementation is intentionally deferred to a fresh session because:

- The change touches 3 files (strategy, runner, decision_log schema) + adds 1 file (cell_flip_detector module).
- The backtest validation (§6) needs raw Phase N fire data + the simulator harness — non-trivial setup.
- Context-length discipline per CLAUDE.md operating rule: "one session = one phase task; stop at 50% context."

Splitting Part A (design) from Part B (implementation) is the same pattern as the Phase T prompt §4 explicitly called out:
> 7. **Start Improvement #2** (cell-flip detector) — design doc first per anti-vibe-coding rule #1, then code

## §9. Acceptance for Part A (this commit)

- Design doc committed to `design/phase-T-cell-flip-detector.md`
- Linked from `phase-prompts/phase-T-directional-revival-2026-05-20.md` §3 #2
- Memory checkpoint noting that Part A is locked and Part B is queued for the next session

## §10. Acceptance for Part B (next commit / next session)

- New module `src/polymarket_bot/strategies/cell_flip_detector.py` with `CellFlipDetector` dataclass
- New tracker `CellFireHistory` (probably inside `src/polymarket_bot/_paper/runner.py` or a new module), apply_settle method + replay from decision log
- Decision-log schema includes `cell_key` on fire + settle records
- Runner wires `cell_history.apply_settle(cell_key, won)` after `bankroll.apply_settle(pnl)`
- `SpotAwareStrategyV2_1` gains `cell_flip_detector` + `recent_wins_getter` constructor params, default None
- `scripts/run_paper.py` wires from env vars `CELL_FLIP_WINDOW_SIZE`, `CELL_FLIP_ABSTAIN_THRESHOLD_PP`, `CELL_FLIP_MIN_SAMPLES` (all defaulting to detector class defaults; detector disabled if all unset, opt-in via `CELL_FLIP_ENABLED=true`)
- All 7 new tests pass + 680 existing tests still pass
- mypy --strict clean
- ruff + import-linter clean

## §11. Out-of-scope (future improvements)

- **Per-side cell-flip detection** — currently buckets are `tier|lo`/`tier|hi`, side-agnostic. Could extend to `tier|side|hi` once we have Phase N-style data with side breakouts; for now Phase N forensic was per-tier-bucket (sides combined).
- **Adaptive window-size** — `window_size=20` is a constant. Could be tier-dependent (low-frequency tiers need larger windows). Defer to post-validation.
- **Cell-flip → MMD label correlation** — when a cell flips, does MMD label change too? Would inform whether MMD gate-mode promotion (Improvement #3) can replace some of the cell-flip logic.
- **Recovery hysteresis** — currently the detector flips back to firing as soon as rolling_wr climbs above threshold. Could add an "abstain for N fires after exit" hysteresis to avoid flapping at the threshold edge. Defer until live data shows flapping.

## §12. Related

- [phase-prompts/phase-T-directional-revival-2026-05-20.md](../phase-prompts/phase-T-directional-revival-2026-05-20.md) §3 Improvement #2
- [design/phase-T-hour-blocklist-v2.md](phase-T-hour-blocklist-v2.md) — Improvement #1 (just landed in commit `228703a`)
- [runbooks/research/phase-N-forensic-summary.md](../runbooks/research/phase-N-forensic-summary.md) F1 + F3
- `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` (22pp standalone) — full SURV-cell flip evidence
- `memory/checkpoint_phase_N.md` — Phase N session summary
- `memory/checkpoint_phase_M.md` — what M.5 was designed to catch (single-cell scope; cell-flip detector generalizes it)

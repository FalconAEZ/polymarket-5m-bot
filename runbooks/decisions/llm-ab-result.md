# OD-5 — Phase 3 LLM A/B verdict (measured)

**Date:** 2026-05-07 (UTC)
**Branch:** claude/bold-galileo-2d56ca
**HEAD at decision:** 0ef2fbe (pre-3.3 work) → next commit lands 3.3a/b/c + this verdict
**Locked decisions under test:** #14 (budget), #16 (LLM uplift gate)
**Operator approval:** received in chat (balance $45 ≥ $35 cap; explicit "go").

---

## VERDICT: CUT

VERDICT: CUT

The LLM ensemble is **CUT**. The deterministic strategy
(`window-delta + oracle-gap`, fires at composite ≥ 0.6pp inside TTL ∈
[10s, 30s]) is the Phase 4 / Phase 6 baseline. The ensemble code stays in
the tree (`src/polymarket_bot/strategies/ensemble.py`,
`src/polymarket_bot/agents/`, ~75 unit tests + the Phase 3.3a integration
test), wired into `scripts/run_ab.py` behind `--enable-ensemble` so
Phase 4 paper data can re-run the A/B without rebuilding the harness.

**spend_usd: 0.404506**

## The locked decision #16 criterion

Per locked decision #16 + the 3.3-prompt's full triple gate:
**LLM kept iff (win-rate uplift ≥ 3pp) AND (p99 decision latency ≤ 4s)
AND ($/decision ≤ $0.01).** All three must clear.

## Measured numbers (28 windows, 2026-05-06 capture)

| Metric | Pass A — deterministic@0.6pp | Pass B — ensemble@0.6pp | Gate |
|---|---|---|---|
| n_windows | 28 | 28 | — |
| n_fired | 0 | 26 | — |
| n_filled | 0 | 15 | — |
| n_won | 0 | 9 | — |
| win_rate | 0.0 (no fills) | **0.600** (9/15) | uplift undefined |
| total_pnl_usd | 0.0 | **-6.158** | informational |
| avg_pnl_usd_per_filled | 0.0 | **-0.411** | informational |
| elapsed_s (full pass) | 21.26 | 260.91 | — |
| elapsed_s / window | 0.76 | **9.32** | **>4s — FAIL** |
| Anthropic spend | $0.000 | **$0.405** | well under $30 hard cap |
| $/decision (fired) | n/a | **$0.0156** | **>$0.01 — FAIL** |
| API calls | 0 | 112 (84 Haiku + 28 Sonnet) | — |

### Gate-by-gate

1. **Win-rate uplift ≥ 3pp** — UNDEFINED. Deterministic produced 0 fills
   on this dataset (composite never crossed 0.6pp during a window where a
   subsequent BookUpdate would also fall inside TTL), so the "win_rate" is
   0/0 and any uplift number is meaningless. The 60% headline on the
   ensemble side is over n=15 fills — far below statistical significance.
2. **p99 decision latency ≤ 4s** — FAIL. Average per-window elapsed in the
   ensemble pass was **9.32s**, dominated by the Sonnet meta call (it runs
   serially after the specialist fan-out). p99 is necessarily higher than
   the average.
3. **$/decision ≤ $0.01** — FAIL. Per fired decision the ensemble cost
   **$0.0156**. Per window (including non-fires) it cost **$0.0145**. Both
   are above the cap.

Two of the three gates fail outright; the third is undefined on the
available data. **CUT** is the locked-decision-correct outcome.

## What the run also surfaced

These are diagnostics for whoever re-opens this in Phase 4 — not bugs to
fix in this session.

- **Cache miss-rate is 100% on the specialist Haiku calls.** Budget report
  shows `cache_creation_input_tokens: 0` and `cache_read_input_tokens: 0`
  for `claude-haiku-4-5`. The cache_blocks helper marks the static prompt
  with `cache_control: ephemeral`, but the prompt may not clear the
  Haiku-4.5 minimum cacheable prefix (4096 tokens). If the prompt is even
  slightly under 4096 tokens it will silently not cache. Sonnet meta cache
  works fine: 58644 cache_read tokens vs 2172 cache_creation. Investigate
  Haiku prompt length and `cache_blocks` placement before re-running.
- **`rationale` 240-char limit gets violated occasionally.** One specialist
  call's output failed pydantic validation because the model returned a
  rationale > 240 chars. The Tier-3 fallback handled it correctly (the
  vote was dropped, ensemble continued), but if the rate is high it eats
  into effective cache hits. Either tighten the prompt's length budget or
  raise `AgentVote.rationale.max_length`.
- **Negative P&L despite 60% win-rate.** -$6.16 across 15 fills means
  fees + spread are larger than the win-margin on this size. With $5 flat
  sizing (decision #9) and ~$0.04/$0.04 spreads at the 0.5/0.5 fair, win
  margin is razor-thin. Phase 4 should re-baseline this against more
  liquid windows.

## Three pre-flight failures + cost

The first two ensemble runs in this session 400'd on every API call —
Anthropic's structured-output API enforces a strict subset of JSON Schema
and pydantic emits keys it rejects (`additionalProperties` not set,
`minimum`/`maximum` on numbers, `maxLength` on strings, `title`,
`default`). Fixed in two iterations:

1. Run 1: `_strict_object_schema` injected `additionalProperties: false`
   on every object subschema. **Spend: $0** (400s aren't billed).
2. Run 2: same helper extended to strip every keyword in the official
   "Not supported" list (numerical, string, array constraints + `title`,
   `default`). **Spend: $0.**
3. Run 3 (this verdict): clean. 112 API calls succeeded (1 schema-validation
   failure on a too-long rationale, dropped via Tier-3 — see above).

Regression test in
`tests/agents/test_anthropic_client.py::test_schema_sent_to_anthropic_has_additional_properties_false`
walks the sent schema and asserts neither `additionalProperties` nor any
unsupported keyword appears. 223 pytest pass.

## Cumulative Anthropic spend (this session)

- Pre-session balance (operator-confirmed): $45
- Spend during 3.3 work: **$0.404506** (one successful ensemble pass)
- Cumulative against decision #14 Phase-3 cap ($50): **$0.40 / $50.00**
- spend_usd: 0.404506

## What "re-open" looks like in Phase 4

When Phase 4 paper trading produces a fuller dataset (≥ 7 days of
non-overlapping 5m windows with non-zero fill rate on the deterministic
side), this verdict can be revisited by:

1. Resolving the diagnostics above (Haiku cache miss-rate; rationale
   length; P&L vs fees).
2. Running `scripts/run_ab.py --dates <range> --enable-ensemble
   --hard-limit-usd 30.0` against the new dataset.
3. Capturing output to `runbooks/gate-evidence/phase-3.3-llm-ab-rev<N>.txt`.
4. Replacing the VERDICT block at the top of this file with the new
   verdict (KEPT or re-CUT) and the supporting numbers.

The ensemble code does not need to be rewritten for this — only the
verdict file changes.

## Cross-refs

- Locked decisions: #5 (3+meta shape), #6 (Tier-3 fallback), #14 (budget
  $50 → $150 → $300 → $200/mo), #16 (this A/B's pass condition), #21
  (33s heartbeat thesis revision).
- Design: `design/agents.md` (ensemble), `design/backtest.md`
  (replay/fills/runner).
- Evidence:
  - `runbooks/gate-evidence/phase-3.3-deterministic-ab.txt` (smoke pass)
  - `runbooks/gate-evidence/phase-3.3-llm-ab.txt` (this run, full output)
- Memory checkpoint to be written: `checkpoint_phase_3.md` after gate
  passes.

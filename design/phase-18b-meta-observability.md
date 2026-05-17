# Phase 18B — Meta-decide outcome telemetry

Status: locked — anti-vibe #1 design-doc-before-code.
Author: Phase 15.5 session, 2026-05-11.
Implements: `phase-prompts/phase-18b-meta-observability-2026-05-13.txt`.

## Problem (one paragraph)

On the 2026-05-10 gate-mode + shadow data (n=226 ensemble votes), 22.1% of
calls returned `meta=None`. 8.8% are accounted for by the explicit
`gate_llm_timeout_s` timeout (it logs `"timeout_s"`). The remaining 13.3%
(30 calls — every one had 3 agreeing specialist votes) had no journal trail
of why `_meta.decide()` returned `None`. The downstream effect is that
gate-mode fell back to base-candidate firing for those 30 windows without
us being able to attribute the cause — API error vs refusal vs schema
failure vs invariant violation. Phase 19 (async LLM pre-compute) can't be
designed without that attribution: a 30%-refusal world wants prompt
re-engineering, a 30%-API-error world wants a retry layer.

## Scope

Purely additive observability. Zero behavior change:
- The fallback policy (`meta is None → fire base candidate`) stays.
- The gate-mode timeout stays.
- The specialist-vote minimum (`MIN_VOTES_FOR_META`) stays.
- The `_meta.decide()` callers all behave identically — same `None` /
  `MetaDecision` dispatch.

The only change is: **every call now also returns a `MetaOutcome` tag**
that gets written into the `ensemble_vote` JSONL record as the new
`meta_outcome` field.

## The `MetaOutcome` enum

`Literal` type, defined in `polymarket_bot.agents.protocol`:

| Tag | Emitted by | Meaning |
|---|---|---|
| `"ok"` | adapter / meta | Parse succeeded and the schema-invariant passed. Useful for sanity ratio. |
| `"api_error"` | adapter | `anthropic.APIError` raised — network, 5xx, rate limit (Anthropic SDK exception). No tokens charged. |
| `"refusal"` | adapter | `stop_reason == "refusal"`. Claude said no. |
| `"no_text"` | adapter | Response had no text content block. |
| `"validation_failed"` | adapter | Pydantic `ValidationError` after the string-truncation recovery also failed. |
| `"invariant_violated"` | meta | Parse succeeded but the post-Pydantic invariant (`FIRE requires side`, `ABSTAIN forbids side`) was violated. |
| `"exception"` | wrapper | `_meta.decide()` raised. Should be rare. |
| `"no_meta_call"` | wrapper | Fewer than `MIN_VOTES_FOR_META` valid specialist votes — meta was never invoked. |
| `"timeout"` | wrapper | `asyncio.wait_for` cancelled the meta call at `gate_llm_timeout_s`. |

The first 6 tags can be attributed to the LLM round-trip. `"exception"` is
a code bug. `"no_meta_call"` and `"timeout"` are operational.

## Propagation path

```
AnthropicAdapter.parse() -> (parsed, usage, outcome)
        ↓
MetaDecider.decide() -> (decision, outcome)              # adds 'invariant_violated' branch
        ↓
EnsembleWrapper._run_ensemble() -> (votes, decision, outcome)  # adds 'no_meta_call' + 'exception' branches
        ↓
EnsembleWrapper._log_ensemble_event(...) writes "meta_outcome": outcome to ensemble_vote JSONL
        |
        +- timeout path overrides with outcome="timeout" before logging
```

## Why a string Literal, not an enum

`MetaOutcome = Literal["ok", "api_error", ...]`. The values are written as
plain JSON strings into the ensemble log. A `StrEnum` would also work but
costs a `.value` lookup at every emit site. The Literal is checked by mypy
in every return path, gives autocomplete in IDEs, and serialises trivially
via `json.dumps`.

## Test-under-load (`feedback_test_under_load`)

Risk: the new tag is computed inside every `_run_ensemble` call (~1× per
fire window, 5min cadence). Each computation is O(1) string-comparison.
The hot-path cost is irrelevant. No new I/O, no new awaits. Confirmed by
inspection — no regression test needed.

## Test plan

1. **`tests/agents/test_anthropic_client.py`** — add 5 new assertions, one
   per `outcome` value the adapter can produce (`ok` / `api_error` /
   `refusal` / `no_text` / `validation_failed`). Update the existing 9
   tests to unpack the new 3-tuple shape.
2. **`tests/agents/test_meta.py`** — assert outcome is propagated from the
   adapter, and add 2 new tests asserting `"invariant_violated"` for the
   two invariant branches (`FIRE without side`, `ABSTAIN with side`).
3. **`tests/strategies/test_ensemble_wrapper.py`** — assert the
   `ensemble_vote` JSONL record now carries a `meta_outcome` field and
   that the value is correct for: (a) happy path → `"ok"`, (b) `meta=None`
   fallback → `"validation_failed"` (or whatever the adapter said), (c)
   timeout → `"timeout"`, (d) too-few-votes → `"no_meta_call"`.
4. **`tests/agents/conftest.py`** — `FakeAdapter` extended to accept a
   3-tuple response and return it. To minimise churn in existing 2-tuple
   call sites, the fake also accepts 2-tuples and auto-tags
   `"ok"` (if parsed not None) or `"validation_failed"` (if None) so the
   existing 10 test sites need only be updated where they want to assert
   on the outcome.

## What this phase explicitly does NOT do

- Does NOT change the fallback policy. `meta=None` still fires base in
  gate-mode.
- Does NOT change the timeout. `gate_llm_timeout_s` unchanged.
- Does NOT add a retry layer for API errors. That's Phase 19 territory.
- Does NOT add a histogram aggregator for `meta_outcome` over time. The
  audit script that consumes this field is out of scope; the field landing
  is enough.
- Does NOT touch the `agents/budget.py` accounting (per
  `feedback_test_under_load` discipline, only one concern per change).

## Gate

`uv run ruff check src/ tests/ scripts/ && uv run mypy --strict src/ &&
uv run pytest -q && uv run lint-imports`. All four green before commit.

## Commit message

`feat(phase-18b): meta_outcome telemetry on ensemble_vote log`

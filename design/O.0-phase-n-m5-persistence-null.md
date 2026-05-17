# O.0 — Phase N PDF correction: M.5 persistence is a NULL result

**Status:** NULL (no code) — 2026-05-17
**Predecessor:** `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` §5.3 + §7.1 step 2

## Finding

`pdfs/PHASE_N_FORENSIC_AUDIT.pdf` §5.3 stated:

> M.5's effective live time is bounded by the gap between its last
> restart and the next. The realistic-restart simulator [...] shows
> +$330 net win [vs idealized +$352].

This was based on a faulty assumption in the M.5 simulator
(`scripts/research/phase_n_forensic_audit.py::simulate_m5`'s
`reset_on_gap_min` mode), which modelled M.5 as if it held its
rolling Path-A state in memory and lost it on each bot restart.

## Reality

`src/polymarket_bot/strategies/path_a_wr_metrics.py::compute_path_a_metrics`
reads `state/decisions/*.jsonl` on every call. The 60s TTL cache in
`scripts/run_paper.py:535-566` does not introduce any restart
sensitivity beyond the 60-second freshness window. **There is no
in-memory rolling state to lose on restart.**

Confirmation: see `path_a_wr_metrics.py:75-83` (day file iteration on
every call) and `path_a_wr_metrics.py:135-182` (deque built fresh per
call from the file contents).

## Consequence

- The M.5 counterfactual is **+$352** (the idealized figure), not the
  bracketed +$330-$352.
- **No `state/m5_path_a_state.json` persistence file is required.**
- Phase O Session 1 plan step 4 (ship M.5 persistence) is dropped.
- The Phase N PDF text in §5.3 / §7.1 step 2 remains as-shipped to
  reflect the audit-time understanding; this design doc is the
  correction-of-record.

## Action

None on the bot side. The simulator's `reset_on_gap_min` mode is
preserved in the script as a what-if (modelling a hypothetical
non-persistent M.5) but is no longer relevant to the live deploy.

## Lesson

Honest-pushback note for future forensics: when reviewing a counterfactual
simulator, ALWAYS verify the simulator's state model matches the actual
implementation. The +$22 gap between idealized and realistic was the
warning sign that the simulator assumption diverged from production.

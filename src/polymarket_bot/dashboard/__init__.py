"""Operations dashboard — single-page Streamlit observability over state/.

Phase 4.5 deliverable. Pure read-only consumer of the decision log JSONL +
state/feeds_health.json + paper.log + capture.log. Never mutates runtime
state, never instantiates Feeds, never replays the backtest. Safe to run
on the operator's laptop alongside the running PaperRunner; safe to run
on a fresh checkout with no state at all (it surfaces the absence
gracefully). Per design/dashboard.md.
"""

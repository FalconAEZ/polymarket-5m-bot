"""Backtest harness — replay engine, fill simulator, walk-forward runner.

Phase 3 builds these on top of the captured Parquet archive. Type
definitions (MarketEvent, Decision, Fill) live in types.py and are imported
both by paper-mode (this session, Phase 3) and by the live runtime in
Phase 6 — same strategy code, two backends. See design/backtest.md.
"""

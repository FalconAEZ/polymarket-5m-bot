"""Strategy implementations — deterministic baseline + LLM ensemble (later).

The Strategy protocol lives in protocol.py. Phase 3.1 ships the
deterministic baseline (window-delta + oracle-gap composite). Phase 3.2
adds the 3-agent LLM ensemble plus a meta-decider. Both implementations
consume MarketEvent from polymarket_bot.backtest.types and produce
Decision objects per design/backtest.md §3.
"""

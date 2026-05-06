"""LLM agent layer — 3 specialists + meta-decider per locked decisions #4, #5.

Specialists (orderbook, oracle_gap, momentum) run on Haiku 4.5; meta-decider
runs on Sonnet 4.6 with adaptive thinking. Strategies in
polymarket_bot.strategies.ensemble compose these into a Strategy that the
Phase 3 BacktestRunner can drive without knowing about LLMs. See
design/agents.md for the full architecture.
"""

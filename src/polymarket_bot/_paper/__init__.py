"""Paper-mode (simulator) layer — populated in Phase 4.

This stub exists so import-linter can evaluate the "paper never imports live
infra" contract from .importlinter. Phase 4 fills in:
  - polymarket_bot._paper.feeds: replays from captured Parquet archives
  - polymarket_bot._paper.exchange: simulated CLOB matching against the book
  - polymarket_bot._paper.runtime: the paper-trading event loop

Tests inject paper components into strategy code via constructor arguments;
production code never imports from this package per anti-vibe rule #7.
"""

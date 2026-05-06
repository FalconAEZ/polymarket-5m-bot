"""Live feed implementations — Binance, Coinbase, Chainlink oracle, Polymarket.

Each module here implements polymarket_bot.feeds.protocols.Feed and accepts
injected stochastic-input dependencies (connect_fn, clock_ns, sleep) per
anti-vibe rule #10 so tests under tests/feeds/ can run without real network.
"""

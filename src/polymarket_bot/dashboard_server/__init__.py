"""FastAPI backend for the v3 dashboard.

Composes a single DashboardState JSON from on-disk state/* files plus
upstream WS subscriptions (Binance kline + depth20, Polymarket CTF
book), and pushes diffs to the React frontend at 127.0.0.1:8505.

Per design/dashboard-v3.md §4. importlinter contract4 forbids this
module from importing _live, _paper.runner/shadow_book, backtest
runtime, strategies, or agents — same boundary as the dashboard
package, ensuring the dashboard server is purely an observability
read layer.
"""

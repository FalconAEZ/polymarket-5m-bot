"""tg-alerter daemon — consumer-side process that bridges Redis ↔ Telegram.

Process-local module: only `scripts/run_alerter.py` imports from here. The bot
runtime itself never imports this package — communication is through Redis
(alerts) and the state/halt.sentinel file (halt). Public API is the `main`
entrypoint and the four protocols (RedisQueue, TelegramClient, HaltWriter,
ClockNs) so tests can wire fakes without touching httpx or redis.
"""

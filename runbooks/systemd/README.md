# systemd units (Phase 5.4)

Canonical sources for the units installed at `/etc/systemd/system/` on the VPS. Whenever an edit is needed, **edit the file here, commit, then re-deploy** — never edit `/etc/systemd/system/*.service` directly on the box. That keeps the runbook git-tracked and reproducible across box rebuilds.

## Files

| File | Purpose | Phase | Enabled? |
|---|---|---|---|
| `bot-staging.service` | Paper-mode runtime (`scripts/run_paper.py`) running against live data | 5 | enabled (active once `.envrc` is populated) |
| `tg-alerter.service` | Telegram alerter daemon (`scripts/run_alerter.py`) — drains `polybot:alerts` from Redis, writes `state/halt.sentinel` on `/halt` | 5.5 | enabled (active once `.envrc` has Redis + Telegram vars) |
| `bot.service` | Live-mode runtime — runs `scripts/run_live.py` (does not exist until Phase 6) | 6 | **disabled** until Phase 6 gate passes |

`bot.service` declares `ConditionPathExists=/home/ops/polymarket-5m-bot/scripts/run_live.py` so even an accidental `systemctl start bot.service` is a no-op until that file lands in Phase 6.

## Deploy

From the operator's local repo, with the linted file committed:

```bash
scp -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -P 2222 \
    runbooks/systemd/bot-staging.service runbooks/systemd/bot.service \
    runbooks/systemd/tg-alerter.service \
    ops@108.132.51.116:/tmp/

ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 \
  'sudo install -m 644 /tmp/bot-staging.service /etc/systemd/system/bot-staging.service \
   && sudo install -m 644 /tmp/bot.service          /etc/systemd/system/bot.service \
   && sudo install -m 644 /tmp/tg-alerter.service   /etc/systemd/system/tg-alerter.service \
   && sudo systemctl daemon-reload \
   && sudo systemctl enable  bot-staging.service \
   && sudo systemctl enable  tg-alerter.service \
   && sudo systemctl disable bot.service \
   && rm /tmp/bot-staging.service /tmp/bot.service /tmp/tg-alerter.service'
```

Then start staging once `.envrc` has all required vars:
```bash
ssh -i ~/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 \
  'sudo systemctl restart bot-staging.service && journalctl -u bot-staging -n 50 --no-pager'
```

## Required env vars in `/home/ops/polymarket-5m-bot/.envrc`

`bot-staging.service` will fail at startup until `.envrc` exports these (file mode must be `0600`):

| Var | Used by | Notes |
|---|---|---|
| `POLYGON_RPC_URL` | `_live/feeds/oracle.py` | Required — `os.environ[…]` lookup, raises if missing. |
| `REDIS_URL` | `bot-staging` (RedisAlertSink) + `tg-alerter` (RedisQueue) | `redis://127.0.0.1:6379/0` on the VPS. Phase 5.5. |
| `TELEGRAM_BOT_TOKEN` | Phase 5.5 `tg-alerter` | Already in operator's local `.envrc` from Phase 0. |
| `TELEGRAM_CHAT_ID`  | Phase 5.5 `tg-alerter` | Same. |

Phase 5.6 will add `POLY_PRIVATE_KEY` (Signer EOA) via age-encrypted SCP per locked decision #11. Phase 6 will add `POLY_API_KEY` / `POLY_API_SECRET` / `POLY_API_PASSPHRASE`. **Funder key NEVER goes to the VPS.**

## Why `ExecStart` wraps `bash -c '…source .envrc…'`

systemd's `EnvironmentFile=` directive expects bare `KEY=VALUE` lines. The project's `.envrc` uses `export KEY=VALUE` so it is shell-sourceable (direnv compatible) on the operator's local machine. Wrapping the bot launch in `bash -c 'source … && exec …'` lets the same file work for both surfaces without maintaining two copies.

## Hardening notes

Both units set `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=full` (so `/usr`, `/boot`, `/efi`, `/etc` are read-only) and run as the unprivileged `ops` user. The bot writes `state/decisions/<UTC-date>.jsonl`, `state/token_side_index.json`, `state/halt.sentinel`, and Phase 5.5 will add `trades.db` (litestream-replicated) — all under `/home/ops/polymarket-5m-bot/`. `ProtectHome=read-only` was tried initially but blocked `uv`'s cache writes at `~/.cache/uv` and `~/.local/share/uv`; user-level isolation via the `ops` account is the real boundary here.

## Verification commands

```bash
systemctl status bot-staging.service
systemctl status bot.service
systemctl is-enabled bot-staging.service   # → enabled
systemctl is-enabled bot.service            # → disabled
systemctl is-active  bot.service            # → inactive
journalctl -u bot-staging -f
```

# Deploy v3 dashboard to VPS — operator runbook

> 10-minute deploy. v2.1 stays at port 8503 as `/audit`; v3 is the new
> primary at 8505. Bot stays untouched. Run end-to-end from your
> laptop.

**Prereqs:**
- v3 branch merged or pulled (this commit)
- SSH access to VPS — tested with: `ssh pmb-staging` (your alias, or
  `ssh -p 2222 ops@108.132.51.116`)
- Bot is running: `systemctl is-active bot-staging.service` returns `active`
- Node 20+ installed on the VPS (for the React build step)

---

## Step 1 — SSH in + pull latest

```bash
ssh -p 2222 ops@108.132.51.116          # or your usual command
cd /home/ops/polymarket-bot
git fetch origin
git checkout claude/trusting-spence-03c165
git pull
uv sync                                  # installs fastapi, uvicorn, aiofiles
```

## Step 2 — Build the React frontend

```bash
cd apps/dashboard-v3
npm ci                                   # install deps from package-lock
npm run build                            # produces apps/dashboard-v3/dist/
cd /home/ops/polymarket-bot
ls -la apps/dashboard-v3/dist/index.html # expect: file present
```

If Node isn't installed on the VPS:
```bash
sudo apt update && sudo apt install -y nodejs npm
# or via fnm: curl -fsSL https://fnm.vercel.app/install | bash
```

## Step 3 — Smoke-test locally on the VPS

```bash
PMB_DASH_STATE_DIR=/home/ops/polymarket-bot/state \
  uv run python -m polymarket_bot.dashboard_server &

sleep 4
curl -s http://127.0.0.1:8505/api/health   # expect: {"ok":true}
curl -s http://127.0.0.1:8505/api/state | head -c 200   # expect: JSON
pkill -f "polymarket_bot.dashboard_server"
```

## Step 4 — Install the systemd unit

```bash
sudo cp /home/ops/polymarket-bot/runbooks/staging/dashboard-server.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dashboard-server.service
sleep 5
sudo systemctl status dashboard-server.service --no-pager
```

Expect: `active (running)`, `binance ws connected` log line.

## Step 5 — Update the SSH tunnel script (if not already)

The tunnel forwards both ports — v3 (8505) and v2.1 audit (8503):

```bash
# On laptop, in the project root:
cat runbooks/operations/dashboard-tunnel.sh | grep -E "8505|8503"
# Should show -L 8505:127.0.0.1:8505 -L 8503:127.0.0.1:8503
```

## Step 6 — Open the tunnel from your laptop

In a fresh laptop terminal:

```bash
cd /Users/hamad/Desktop/PolyMarket-5m
make dash-tunnel
```

Open in browser:
- **http://127.0.0.1:8505/** — v3 dashboard (the new one)
- **http://127.0.0.1:8503/** — v2.1 dashboard (audit / deep-dive)

## Verify on v3

You should see:
- Top strip: `●LIVE POLYMARKET 5M v3 · AGGRESSIVE · BTC $XX,XXX · BANKROLL $X,XXX.XX · clock UTC`
- Live tape scrolling at the top with WIN/LOSS events
- Wallet panel: large green PnL number with digit-roll on update
- Chart: real BTC 5m candles from Binance (animated tick updates)
- Spot book: red asks + green bids (Binance depth20)
- CTF book: Polymarket UP/DOWN depth for the current 5m window
- Pipeline strip: 6 numbered stages with real timing
- Decisions tape: rows animated in from top on new fires
- Provider RTT panel: real Dublin → provider RTT (Binance/Coinbase
  sub-50ms; PM-CLOB ~100-200ms)
- Trip-wires: 4 progress bars (PnL / fire-rate / WR / elapsed)
- Per-tier: stacked-bar visualization

## If something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `dashboard-server.service` failed to start | uv not in PATH | Check unit's Environment line; verify `/home/ops/.local/bin/uv` exists |
| `502 Bad Gateway` from tunnel | port 8505 not listening | `sudo systemctl status dashboard-server` |
| Page renders but no data | state dir wrong | check Environment `PMB_DASH_STATE_DIR` matches bot's state |
| Chart empty | Binance WS not connected | check logs: `journalctl -u dashboard-server -n 50` |
| CTF book empty | no recent decisions, or Gamma offline | normal until next decision fires |
| Provider RTT empty | rtt-collector.service not running | `sudo systemctl start rtt-collector.service` |

## Rollback

```bash
sudo systemctl disable --now dashboard-server.service
sudo rm /etc/systemd/system/dashboard-server.service
sudo systemctl daemon-reload
```

v2.1 (port 8503) remains untouched — it's the fallback.

The bot itself (`bot-staging.service`) is **never** touched throughout
deploy or rollback.

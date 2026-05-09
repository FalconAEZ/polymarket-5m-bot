# Deploy v2 dashboard to VPS — operator runbook

> 5-minute deploy. Run end-to-end from your laptop. Bot stays up
> throughout (the dashboard is a separate read-only systemd unit; it
> never touches `bot-staging.service`).

**Prereqs:**
- v2 dashboard branch merged or pushed (this commit)
- SSH access to VPS as `ops@108.132.51.116:2222` (already configured)
- Bot is running (check: `systemctl is-active bot-staging.service` returns `active`)

---

## Step 1 — SSH into the VPS

```bash
ssh -p 2222 ops@108.132.51.116
```

## Step 2 — Pull the latest code + new deps

```bash
cd /home/ops/polymarket-bot
git pull origin main           # or whichever branch the v2 work landed on
uv sync                        # installs streamlit-shadcn-ui, streamlit-aggrid, plotly
```

`uv sync` should take ~30s. If it fails on a missing system package
(e.g. `gcc` for a wheel), install that and re-run.

## Step 3 — Smoke-test the dashboard locally on the VPS

```bash
PMB_DASH_V2=1 \
PMB_DASH_STATE_DIR=/home/ops/polymarket-bot/state \
uv run streamlit run scripts/dashboard.py \
    --server.port=8503 \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --browser.gatherUsageStats=false &
```

Wait ~5s for boot, then verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8503/
# Expect: 200
```

Kill the smoke-test:

```bash
pkill -f "streamlit run scripts/dashboard.py"
```

## Step 4 — Install the systemd units

```bash
sudo cp /home/ops/polymarket-bot/runbooks/staging/streamlit-dashboard.service /etc/systemd/system/
sudo cp /home/ops/polymarket-bot/runbooks/staging/rtt-collector.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## Step 5 — Start the RTT collector first

```bash
sudo systemctl enable --now rtt-collector.service
sleep 30           # let it write a few samples
sudo systemctl status rtt-collector.service --no-pager
tail -n 5 /home/ops/polymarket-bot/state/provider_rtt.jsonl
```

Expect: 5 lines per tick (one per provider), `ok: true` for at least
Binance + Coinbase + PM-CLOB + PM-Gamma. Chainlink may fail with the
default endpoint — that's a known caveat; swap the URL in
`provider_rtt.py` if you have a private RPC.

## Step 6 — Start the dashboard

```bash
sudo systemctl enable --now streamlit-dashboard.service
sleep 5
sudo systemctl status streamlit-dashboard.service --no-pager
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8503/
# Expect: 200
```

## Step 7 — Open the SSH tunnel from your laptop

In a fresh terminal **on your laptop**:

```bash
cd /Users/hamad/Desktop/PolyMarket-5m
make dash-tunnel
```

(or `bash runbooks/operations/dashboard-tunnel.sh`)

Open http://127.0.0.1:8503/ in your browser.

## Verify

You should see:
- `MODE: AGGRESSIVE` banner (live, the bot is running)
- Real cumulative PnL in the wallet panel (no longer +$0)
- TradingView chart loading
- Polymarket CTF orderbook for the current 5m window
- **PROVIDER RTT · VPS** panel showing real VPS→provider RTT (sub-50ms
  for Binance/Coinbase/PM-CLOB from Dublin; PM-Gamma may be 100-200ms;
  Chainlink TBD)
- "collector live · last sample <30s ago" liveness label in the RTT
  panel
- Pipeline strip with CAPTURE alive (the bot's feed processes are up)

## If something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `streamlit-dashboard.service` failed to start | `uv` not in PATH for systemd | Verify `/home/ops/.local/bin/uv` exists; check unit file Environment line |
| Port 8503 in use | Old streamlit smoke test still running | `pkill -f streamlit; sudo systemctl restart streamlit-dashboard` |
| Tunnel can't connect | SSH config wrong | Test plain SSH first: `ssh -p 2222 ops@108.132.51.116` |
| RTT JSONL not growing | rtt-collector crashed | `sudo journalctl -u rtt-collector -n 50` |
| Dashboard renders but no PnL | Dashboard reading wrong state dir | Check `PMB_DASH_STATE_DIR` env in unit file points to bot's state |
| RTT panel says "collector stale" | rtt-collector down for >2min | `sudo systemctl restart rtt-collector.service` |

## Rollback

```bash
sudo systemctl disable --now streamlit-dashboard.service rtt-collector.service
sudo rm /etc/systemd/system/streamlit-dashboard.service /etc/systemd/system/rtt-collector.service
sudo systemctl daemon-reload
```

The bot itself (`bot-staging.service`) is untouched throughout — neither
the deploy nor the rollback affects bot trading.

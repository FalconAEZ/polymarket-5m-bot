# RESUME-WINDOWS — pickup prompt for the Windows PC

> **You are reading this in a fresh Claude Code session on Windows
> after `git clone`.** Below is everything the next session needs to
> continue the project. Paste this into Claude Code as your first
> message. Anchored docs are in the repo — Claude can read them
> directly.

---

## ONE-LINE STATUS

Branch `main` @ HEAD ([latest commit](https://github.com/FalconAEZ/polymarket-5m-bot/commits/main)). Phases 0 → 4.5 closed. Phase 4 14-day paper run pending; Phase 5 (VPS) not started.

## SESSION PRIMER (READ FIRST — 30 SECONDS)

Polymarket BTC 5-minute up/down trading bot, real-money, solo build by Hamad. Started 2026-05-04. The Mac that hosted Phases 0-4.5 has been stepped away from; you (Claude on Windows) are continuing.

**What was shipped on the Mac:**
- **Phase 0** (Foundations) → tag `phase-0-pass`
- **Phase 1A** (Wallet & Auth, no funds) → tag `phase-1a-pass`
- **Phase 2** (4-feed Capture) → closed; capture ran 24/7 on the Mac
- **Phase 3** (Backtest + LLM A/B) → tag `phase-3-pass`. **OD-5 verdict: CUT**. Ensemble code retained, gated behind `--enable-ensemble`. Phase 4+ deterministic-only.
- **Phase 4 dev** (paper runtime) → closed. `_paper/{shadow_book,runner,decision_log}.py` + `scripts/run_paper.py` + sim-validation harness + monitor runbook + gate scaffold.
- **Phase 4.5** (operations dashboard) → closed. `scripts/dashboard.py` Streamlit single-page app, pixel-aligned at 1728×1117, 274 pytest pass. Live demo at `scripts/demo_live.py`.

**Mac processes** (capture pid 23820, paper pid 30325) are dead now — laptop sleep killed them. Phase 4 14-day paper-run wall-clock work needs to restart on Windows OR on the future VPS.

## CONTEXT ANCHORS (READ IN ORDER)

| # | Path | Purpose |
|---|---|---|
| 1 | `CLAUDE.md` | Durable preferences + 10 anti-vibe rules + locked decisions index |
| 2 | `state/sessions/2026-05-07-evening.md` | Previous session hand-off note (full detail) |
| 3 | `state/runbooks/decision-18-revision.md` | Why the Obsidian vault now lives in git |
| 4 | `RUNBOOK.md` §"PHASE 4" + §"PHASE 4.5" + §"PHASE 5" | Phase-by-phase execution source-of-truth |
| 5 | `design/paper.md` + `design/dashboard.md` | Two locked architectural design docs |
| 6 | `runbooks/dashboard.md` | Operator runbook for the dashboard |
| 7 | `runbooks/paper-monitor.md` | Operator runbook for the 14-day paper run |
| 8 | `runbooks/windows-pc-setup.md` | Manual Windows install steps (already done if you're reading this) |
| 9 | `runbooks/obsidian-setup.md` | Open the vault on Windows |

## VERIFY THE INSTALL (1 MINUTE)

```powershell
git rev-parse HEAD                          # printed at the top of this doc
uv sync                                     # idempotent, fast on second run
uv run pytest -q                            # must show 274 passed
uv run mypy --strict src\                   # must show 43 files, 0 issues
uv run lint-imports                         # must show 3 contracts kept, 0 broken
```

If any step fails: do NOT proceed. Open a Claude session and ask what regressed.

## SEE THE DASHBOARD LIVE (3 MINUTES)

```powershell
# Terminal 1 — start the live simulator (seeds + ticks fake state)
uv run python scripts\demo_live.py

# Terminal 2 — launch the dashboard
uv run streamlit run scripts\dashboard.py
```

Browser opens at http://127.0.0.1:8501. You should see:
- Header bar with pulsing live-dot, DETERMINISTIC badge, refresh time
- 5 KPI cards (PnL / Win / Decisions / Last Decision / Paper Uptime) — pixel-aligned with the panels below them
- 3-col panel grid: chart+decisions (left, 55%), processes+feeds (mid, 25%), live logs (right, 20%)
- Collapsed historical agent activity expander at the bottom

If anything looks broken: use the Claude Preview MCP (`.claude/launch.json` is wired). `preview_start name="dashboard"` → `preview_eval` + `preview_inspect` to diagnose pixel-level layout issues.

## NEXT STEPS — THREE OPTIONS

### Option A — Restart the Phase 4 14-day paper run on Windows

The Phase 4 gate requires 14 calendar days of `state/decisions/*.jsonl` evidence. Mac's run is dead; restart on Windows.

Pre-flight (per `runbooks/paper-monitor.md`):
- 14-day window must include ≥1 CPI/FOMC release, ≥1 weekend low-vol period, ≥1 BTC daily move > 2%
- Windows PC must stay awake the full 14 days. Set: Settings → System → Power → Sleep "Never" while plugged in
- `caffeinate`-equivalent on Windows: `Start-Process powercfg -ArgumentList "/change standby-timeout-ac 0"` (no sleep when on AC)

Launch (Windows-equivalent of `runbooks/capture-launch.md` Option A):
```powershell
# Terminal 1 — capture
$env:POLYGON_RPC_URL = "wss://..."
Start-Process uv -ArgumentList "run","python","-u","scripts\run_capture.py" `
    -RedirectStandardOutput "state\capture.log" -RedirectStandardError "state\capture.err.log" -NoNewWindow
# capture this PID:
Get-Process | Where-Object {$_.Path -like "*python*"} | Format-Table -AutoSize
# write to state\capture.pid by hand for monitoring

# Terminal 2 — paper runner (after capture is healthy)
Start-Process uv -ArgumentList "run","python","-u","scripts\run_paper.py" `
    -RedirectStandardOutput "state\paper.log" -RedirectStandardError "state\paper.err.log" -NoNewWindow
```

Daily ritual: open the dashboard and glance at it. No jq needed on Windows.

**Caveat:** if you want true 24/7 reliability, Phase 5 (VPS) is the better path.

### Option B — Skip to Phase 5 (VPS provisioning)

The 14-day run on the VPS is more reliable than on a Windows desktop. Phase 5 plan is in `RUNBOOK.md` §"PHASE 5".

**VPS recommendation** (locked decision #2 — reaffirmed):

> **AWS Lightsail eu-west-1 (Dublin)** · 2 vCPU / 4 GB / 80 GB NVMe / Ubuntu 24.04 · static IP · $5/mo plan

Why Dublin specifically:
- Polymarket's CLOB infrastructure is co-located near AWS eu-west-1; measured **sub-5ms WS latency** in pre-flight research
- The bot is latency-sensitive (5-minute window decisions need TTL ≤ 30s; every ms counts on the gasless relayer's confirm path)
- Dublin is the cheapest tier among the regions with low CLOB latency
- AWS Lightsail's $5 plan is sufficient — Phase 4 paper consumes < 1% CPU

Other regions considered + rejected:
- AWS us-east-1 (Virginia) — high CLOB latency in tests
- DigitalOcean fra1 (Frankfurt) — comparable latency to Dublin but worse Polymarket throughput in pings
- Hetzner Falkenstein — cheapest, but Polymarket has periodically rate-limited their IP ranges

Phase 5 7-step gate (manual + automated):
1. AWS account + billing alert ($20/mo cap)
2. Provision Lightsail
3. WS latency check: p50 < 5ms, p99 < 15ms
4. Two systemd units (bot-staging + bot, the second disabled)
5. Prometheus + Grafana Cloud free tier; tg-alerter
6. Move Signer key (NOT funder) via age-encrypted SSH transfer
7. 24-hour staging run

Steps 1, 2, 6 are manual (account, payment, security-sensitive transfers). The rest Claude can drive over SSH.

If picking this path: write `phase-5-prompt.txt` in the repo root and start a new Claude Code session against it.

### Option C — Polish the dashboard further

Phase 4.5 left some nice-to-haves on the table:

- Tag `phase-4.5-pass` (gate is green, just hasn't been tagged)
- Sparklines on each KPI showing recent trend
- `st.cache_data` on the loaders so the 4s refresh doesn't re-parse JSONL each tick
- Better empty states with iconography
- Re-run `/design:design-critique` on the final state
- Add live agent-vote logging to PaperRunner (this is Phase 8 work but the dashboard panel scaffolding exists)

Lowest stakes path. Good if you want to polish before committing to the 14-day clock.

## HARD LIMITS (DO NOT EXCEED WITHOUT EXPLICIT OPERATOR GO)

- **Cumulative Anthropic spend so far:** $0.405 (Phase 3 only). Phases 4 + 4.5 added $0. Stay deterministic-only.
- **Phase 1B (real money):** still parked. No funder/signer activity, no real orders, no signing of anything that touches Polymarket execution.
- **Paper mode** must run on a machine that stays awake. Windows desktop is OK if you configure power; VPS is more reliable.

## ANTI-VIBE RULES — UNCHANGED

Same 10 rules in `CLAUDE.md`. The disciplines that landed Phases 0-4.5 cleanly should land what's next.

- Design doc before any `src/` change
- Bug → failing test → fix → green
- 3-fix rule before incident report
- All 3 import-linter contracts must stay green
- mypy --strict + 274 pytest pass on every commit

## SESSION BOUNDARY — END WHEN ONE OF

(a) Demo dashboard verified working on Windows + an explicit choice made between Options A/B/C + corresponding work begun. ✅
(b) 50% context burn → close out, write `state/sessions/<date>-windows-pickup.md`, stop. ⏸
(c) Hard blocker (uv sync fails on Windows, Streamlit doesn't render, pytest regression) → `runbooks/incidents/<date>-<slug>.md`; abort; escalate. 🛑

## THREE REMINDERS

1. **The Claude Preview MCP is your friend** for any UI iteration. `.claude/launch.json` is already wired. `preview_start name="dashboard"` → `preview_eval` + `preview_inspect` for pixel diagnosis. This made Phase 4.5 alignment work measurable instead of guesswork.
2. **Phase 1B still parked.** No real money flows yet. The wallet derivation work in Phase 1A finished at `phase-1a-pass`; funding is gated by Phase 4 + Phase 5 evidence.
3. **State you brought across via git** (after the Phase 4.5b decision-18 revision):
   - `state/decisions/*.jsonl` — Phase 4 decision log
   - `state/sessions/*.md`, `state/postmortems/*.md`, `state/runbooks/*.md` — Obsidian vault notes
   - `state/token_side_index.json` — Gamma side resolver cache
   - **NOT brought:** parquet captures, `.log` files, `.pid` files, `state-demo/`. These regenerate fresh on Windows.

## HAND-OFF SIGNATURE

Mac session closed at HEAD on `main` (fast-forwarded from `claude/bold-galileo-2d56ca`).
Pushed to `github.com/FalconAEZ/polymarket-5m-bot`.
274 pytest pass · mypy --strict on 43 files · lint-imports 3/3 KEPT · gate-4.5 green.

Demo:
```powershell
uv run python scripts\demo_live.py
uv run streamlit run scripts\dashboard.py
```

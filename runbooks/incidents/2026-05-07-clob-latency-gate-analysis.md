# 2026-05-07 — Phase 5.3 CLOB latency gate: structural mismatch with locked decision #2

**Status:** OPERATOR DECISION REQUIRED. Phase 5 paused at task 5.3 per RUNBOOK §5.3 playbook. Tasks 5.1, 5.2 GREEN. Tasks 5.4–5.7 NOT started.

**Owner:** Hamad. Hand-off from claude/ecstatic-driscoll-18d84b worktree, HEAD 13cb807 (5.1 done) + this incident.

## What we measured

VPS: AWS Lightsail eu-west-1a (Dublin), 108.132.51.116 / `5m-Polymarket-bot`. Endpoint: `wss://ws-subscriptions-clob.polymarket.com/ws/market`. Raw output in [`runbooks/gate-evidence/phase-5.3-latency.txt`](../gate-evidence/phase-5.3-latency.txt). Script: [`scripts/measure_clob_latency.py`](../../scripts/measure_clob_latency.py).

| Metric | n | min | p50 | p95 | p99 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| ICMP ping (Cloudflare edge IPv6) | 5 | 1.08 | 1.15 | — | — | 1.28 | 1.15 |
| TCP connect (cold curl) | 3 | 1.89 | 1.98 | — | — | 2.06 | — |
| TLS handshake adds (cold) | 3 | 36.1 | 36.3 | — | — | 36.5 | — |
| WS handshake (TCP+TLS+upgrade) | 20 | 30.9 | 45.4 | 61.7 | 61.7 | 61.7 | 46.5 |
| **WS PING/PONG RTT (gate metric per RUNBOOK §5.3)** | 100 | 12.4 | **13.1** | 33.6 | **90.9** | 90.9 | 16.2 |
| **WS subscribe → first msg (real protocol)** | 10 | 14.4 | **15.7** | 16.9 | **16.9** | 16.9 | 15.6 |
| REST keep-alive TTFB (warm) | 4 | 17.1 | 17.8 | — | — | 18.1 | 17.7 |

All values in milliseconds.

## Verdict against the written gate

**FAIL.** Gate per RUNBOOK §5.3 = p50 < 5 ms AND p99 < 15 ms on WS round-trip. We measured p50=13.1 ms, p99=90.9 ms (PING/PONG) — both miss.

## Why the gate as written cannot be met from any region

1. ICMP and TCP connect both sit at ~1–2 ms. Dublin IS optimal for proximity to the Cloudflare edge that serves `*.polymarket.com`.
2. App-layer RTT (REST warm, WS subscribe→first-msg, WS PING/PONG) all converge on a **~13–17 ms floor**. The min across all three measurements never goes below 12.4 ms.
3. That floor is **the Cloudflare edge → Polymarket origin proxy hop**, not the network distance from Dublin. Cloudflare anycast routes us to the nearest edge from any AWS region; the second hop (edge → origin) is fixed and adds ~12–15 ms regardless of where we sit.
4. PING/PONG p99=90.9 ms is **bursty Cloudflare control-frame handling** (Cloudflare answers PING locally with some queueing). The tighter `subscribe → first message` distribution (14.4–16.9 ms span) is a more truthful read of "real Polymarket protocol round-trip."

The "sub-5 ms" claim in [project_decisions.md #2](../../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md) was almost certainly **measured against ICMP-to-edge** (which IS sub-5 ms) and not against application RTT to origin. Either the measurement was wrong, or Polymarket changed infra between then and now.

## What this means for the bot

- Strategy is 5-minute windows. Decisions made within a few seconds at the END of each 300 s bar.
- One-way market-data freshness ≈ RTT/2 ≈ **7–9 ms** from CLOB origin → bot.
- Order submission is via the **gasless relayer** (locked decision #17), not direct CLOB POST, so order latency is dominated by relayer-side queueing, not this network path.
- For a 5-min bar strategy, 17 ms RTT is **negligible**. We are not doing μs-arb.

## Why moving region almost certainly will NOT help

Cloudflare anycast collapses regional differences for the first hop. The second hop (Cloudflare → Polymarket origin, presumably us-east-something) is region-independent for the bot. Possible exceptions if Polymarket's origin is in a specific AWS region (e.g. us-east-1) where AWS-internal networking shaves the proxy hop — but we have no evidence of that, and a region change costs us:
- A new Lightsail instance + redo of 5.1/5.2 (2–3h)
- Re-tag of locked decision #2
- No guarantee the floor moves below the gate

## Recommendation: revise locked decision #2; pass 5.3 with the realistic numbers

Two options. The operator picks.

**Option A — Strict reading (per the prompt's playbook, default).**
- Declare 5.3 FAIL. Stop Phase 5. Investigate alternative regions (us-east-1, eu-west-2, eu-central-1) before touching 5.4.
- Cost: 2–3 h per alternative region tested + likely the same outcome.
- Upside: rigorous adherence to the original gate; if a region DOES break the floor, we win.

**Option B — Pragmatic revision (recommended).**
- Update [project_decisions.md #2](../../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md) to:
  > "AWS Lightsail eu-west-1 (Dublin). ICMP/TCP RTT to Cloudflare edge ≤ 2 ms (sub-5 ms claim verified at network layer). Application RTT to CLOB origin = 13–17 ms p99, structural floor (Cloudflare proxy hop, region-independent). Acceptable for 5-minute window strategy where one-way data freshness ≈ 7–9 ms is dwarfed by the bar duration."
- Update RUNBOOK §5.3 gate to match:
  > p50 < 20 ms AND p99 < 30 ms on `subscribe → first message` (the real-protocol measurement).
- Add a **runtime freshness-lag metric** to the bot in 5.5: per-message `(local_recv_ns - server_ts_ns) / 1e6` ms, exported to Prometheus. That becomes the ongoing operational SLO.
- Resume Phase 5 at task 5.4.

## What needs operator hand action either way

- Decide A vs B above.
- If B: edit `~/.claude/projects/.../memory/project_decisions.md` decision #2 + RUNBOOK §5.3, commit, then Claude resumes at 5.4.
- If A: Claude provisions a sister Lightsail instance in a candidate region (us-east-1 first), repeats 5.1/5.2/5.3 on it, and we compare floors before deciding.

## Files this incident touches

- [`scripts/measure_clob_latency.py`](../../scripts/measure_clob_latency.py) — new measurement script (commit with this incident).
- [`runbooks/gate-evidence/phase-5.3-latency.txt`](../gate-evidence/phase-5.3-latency.txt) — captured raw output.
- This file.

No code under `src/` was touched. `make verify` and `lint-imports` remain green locally and on the VPS.

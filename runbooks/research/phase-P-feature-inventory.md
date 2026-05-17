# Phase P feature inventory — KEEP/DROP on hard revert to J.1.6

Authored: 2026-05-18 (operator UAE local, ≈ 2026-05-17 21:40 UTC).
Source: git log on `claude/jovial-hermann-7e103f` between H.5 ship
(2026-05-13) and Phase O Session 1 close (2026-05-17), cross-referenced
with PHASE_N_FORENSIC_AUDIT.pdf §3-§7 and `memory/checkpoint_phase_{J,K,L,M,N,O}.md`.

Verdict legend:
- **KEEP** → in the J.1.6 baseline restored on `claude/phase-P-hard-reset` at `83fe119`.
- **DROP** → git-reverted by cutting the branch from `83fe119`; env-stripped on VPS.
- **PRESERVE** → not bot-runtime code; cherry-picked onto the new branch (`53e08c9`).

| Feature | Ship UTC | Commit | Design doc | Data justification | Defense / Edge | Phase N verdict | KEEP/DROP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **H.5 multi-fire cap=1** | 2026-05-13 00:21 | env-only (was cap=2 in H.2.13) | n/a | Live obs H.5+3.8h: cap=1 and cap=2 IDENTICAL 41.9% WR — cap=2 only doubles capital exposure, not edge | Variance | ✓ Working | **KEEP** |
| **H.2.10 instant-settle gamma timeout 30s** | 2026-05-13 | env-only (`INSTANT_SETTLE_GAMMA_TIMEOUT_S=30`) | n/a | Operator-visible settle latency requirement | Latency | ✓ Working | **KEEP** |
| **H.2.12 path-A block_up in 70-85%** | 2026-05-13 00:56 | `c746db3` | n/a (Phase H session) | Phase G forensic: UP fires in 70-85% net -$0.06/tr (n=41) vs DOWN +$0.13/tr (n=31) | Edge filter | ✓ 0 UP fires across 237 tier-70-85% records on n=755 | **KEEP** |
| **J.1 CH3 sub-floor abstain (price ≥ 0.42)** | 2026-05-13 07:11 | `49340e2` | n/a | H.3 audit n=111: below 0.42 WR 25.5% -$5.70/tr; above 0.42 WR 56.7% +$1.77/tr | Edge filter | n/a (J.1.5 superseded) | **KEEP** (env scaffolding) |
| **J.2 hour-of-day blocklist (22/23/00 UTC × 70-85%)** | 2026-05-13 07:17 | `878a87b` | n/a | H.5 era: tier 70-85% × hour {22, 23, 00} catastrophic at -$18/tr and -$7/tr | Edge filter | ✓ Confirmed band | **KEEP** |
| **J.1.5 fold (`SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK=0.0`)** | 2026-05-14 07:22 | env-only | n/a | n=247 audit: J.1 CH3 cell statistically dead — n=175 WR 35.4% CI upper 42.8%, $/tr −$1.08 | Edge filter | ✓ 0 CH3 fires post-fold across n=755 | **KEEP** |
| **J.1.6 A — bankroll replay** (`BANKROLL_REPLAY_ENABLED=true`) | 2026-05-14 18:36 | env-only | n/a | Kelly compounds off live bankroll; J.1.6 thesis | Sizing | ✓ Realized as designed; +$1,235 peak then −$1,140 drawdown — symmetric variance | **KEEP** |
| **J.1.6 B — Kelly Tier S1** (`KELLY_MULT=0.10 → 0.15`) | 2026-05-14 18:36 | env-only | Phase J Kelly ladder | Full session n=327 WR 50.5% passes Kelly S1 gate; post-fold n=75 WR 74.7% | Sizing | ✓ Realized; combined A+B → 2.3× bet scaling | **KEEP** |
| **L.5 daily-PnL auto-halt** | 2026-05-16 12:52 | `3277225` | `design/L.5-daily-pnl-auto-halt.md` | Operator-manual gate trips daily; needs automation | Bleed-stopper | ✓ Tripped correctly 2026-05-16 23:50Z (PnL −$634, gate −$30 × 21) | **DROP** — operator chose clean Phase M strip; no automated halt-on-bleed |
| **M.1a v0 — SHADOW regime classifier** | 2026-05-16 19:14 | `d0797f4` | `design/M.1a-flat-vs-trend-shadow-log.md` | Phase L thesis: regime-aware abstain | Edge filter (shadow) | ⚠ n=32 over 4.6h before L.5 trip: 81% MIXED dominance unexpected | **DROP** |
| **M.1a v1 — ACTIVE chop-abstain** | 2026-05-17 ~11:00 | `b3421b5` | `design/M.1a-v1-active-abstain.md` | n=23 annotated subset showed chop > mixed WR | Edge filter | ✗ **FALSIFIED** on n=755 |Δbps| proxy — monotonic WR by |Δ| (35.7 / 33.8 / 60.5 / 71.4%) contradicts chop > mixed | **DROP** |
| **M.5 — path-A regime wrapper** | 2026-05-17 | `84d33b1` | `design/M.5-path-a-regime-wrapper.md` | Phase L Path A 77.6% WR vs 73.8% break-even; only 3.8pp above | Edge filter | ✓ Design CORRECT — but shipped 3 days late; +$330 counterfactual avoided if shipped at first-activatable 2026-05-14 05:55Z | **DROP** (operator wants Phase P clean; M.5 may return after Phase Q MMD verdict) |
| **M.2 v0 — orderbook imbalance shadow** | 2026-05-17 | `e72142c` | `design/M.2-orderbook-imbalance-shadow.md` | Phase L theory: imbalance is a leading signal | Edge filter (shadow) | ⚠ Lived 45 min, n=3, all `too_thin`, all lost — un-evaluable | **DROP** |
| **O.1 — SURV-cell shift canary** | 2026-05-17 17:00 | `16e8f38` | `design/O.1-surv-cell-shift-canary.md` | Phase N §3.3: SURV cell (tier 30-50% × \|Δbps\|≥5) WR collapsed 60.7% → 46.5% from peak; dominant bleeder | Edge filter | n/a (1 fire post-restart → lost; never field-validated post-ship) | **DROP** |
| **Phase O bankroll override** $1k → $3k (`PMB_STARTING_BANKROLL=3000`, `BANKROLL_REPLAY_ENABLED=false`) | 2026-05-17 16:32 | env-only + `98940b1` dashboard fix | n/a (operator override of locked decision #10) | Op call to scale exposure post Phase N | Sizing | n/a | **DROP** — decision #10 restored ($1,000 + replay=true) |
| **Phase O L.5 scaling 3×** (`DAILY_PNL_GATE_USD=-30 → -90`) | 2026-05-17 16:34 | env-only | n/a | Scale gate to preserve 3%-of-bankroll posture vs $3k | Bleed-stopper | n/a | **DROP** (with L.5 itself) |
| **Phase O M.5 lookback tune** (`REGIME_M5_LOOKBACK_N=30 → 15`, `MIN_SAMPLES=20 → 10`) | 2026-05-17 17:00 | env-only | n/a | Mid-session tune to narrow M.5 ABSTAIN gap from 22pp to 8.8pp | n/a | n/a | **DROP** (with M.5 itself) |
| **Phase O M.1a v1 disable** (`REGIME_M1A_V1_ENABLED=true → false`) | 2026-05-17 16:25 | env-only | n/a | Phase N falsifier killed it | Edge filter | ✓ Phase O Session 1 implemented Phase N recommendation | n/a — drop is consistent |
| **Dashboard PMB env passthrough** (systemd drop-in `/etc/systemd/system/dashboard-server.service.d/bankroll.conf`) | 2026-05-17 | `98940b1` | n/a | Make dashboard honor Phase O bankroll override | Reporting | n/a | **DROP** (drop-in removed on VPS, daemon-reloaded) |
| **Phase N forensic PDF + scripts + 14 charts** | 2026-05-17 (various) | `16e8f38` → `2e930c0` | n/a (research) | Phase N investigation | n/a | n/a (research, not bot-runtime) | **PRESERVE** (cherry-picked onto Phase P branch at `53e08c9`) |
| **Phase 14 tier-gate kill-switch** (`TIER_GATE_ENABLED`/`TIER_GATE_BLOCKLIST`) | pre-J.1.6 (dark) | n/a (already in `scripts/run_paper.py` at `83fe119`) | n/a | Dark-shipped infra; never activated on jovial-hermann | Edge filter (dormant) | n/a | **DROP env, KEEP code** (env stripped from `.envrc` for cleanliness; code remains as no-op default-false) |
| **Phase 15 regime-gate kill-switch** (`REGIME_GATE_ENABLED`/`REGIME_GATE_ABSTAIN_REGIMES`) | pre-J.1.6 (dark) | n/a (already in `scripts/run_paper.py` at `83fe119`) | n/a | Dark-shipped infra; never activated on jovial-hermann | Edge filter (dormant) | n/a | **DROP env, KEEP code** (same as above) |

## Verdict summary

**KEEP (J.1.6 baseline restored on VPS as of 2026-05-17 21:37:28 UTC):**
- `STRATEGY=spot_aware_v2_1`, `KELLY_MULT=0.15`, `MULTI_FIRE_CAP=1`
- `BANKROLL_REPLAY_ENABLED=true`, `PMB_STARTING_BANKROLL=1000`
- J.1.5 fold (`SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK=0.0`)
- J.1 floor (`SPOT_AWARE_TIER_RELAX_PRICE_FLOOR=0.42`)
- J.2 hour-blocklist (`SPOT_AWARE_HOUR_BLOCKLIST_UTC=22,23,0`, `SPOT_AWARE_HOUR_BLOCKLIST_TIERS=70-85%`)
- H.2.12 path-A (`SPOT_AWARE_BLOCK_UP_IN_TIERS=70-85%`)
- Cross-phase infra: `INSTANT_SETTLE_ENABLED=1`, `INSTANT_SETTLE_GAMMA_TIMEOUT_S=30`, `POST_HOC_GAMMA_RETRY_ENABLED=1`

**DROP (Phase M/O — git-reverted via branch cut from `83fe119`):**
- L.5 daily-PnL auto-halt + auto-resume cron (per operator decision; bot has no automated halt-on-bleed)
- M.1a v0 + v1 regime classifier (v1 falsified by Phase N)
- M.5 path-A regime wrapper (design correct, will revisit in Phase Q after MMD verdict)
- M.2 v0 orderbook imbalance shadow (un-evaluable on n=3)
- O.1 SURV canary (never field-validated)
- Phase 14 tier-gate env (dormant; code stays for future re-enable)
- Phase 15 regime-gate env (dormant; code stays for future re-enable)
- Dashboard PMB env passthrough drop-in
- Phase O bankroll override (decision #10 restored at $1,000 + replay=true)

**PRESERVE (cherry-picked from `e3133e6`):**
- `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` + builder
- `scripts/research/phase_n_forensic_audit.py` + `phase_n_charts.py`
- `runbooks/research/phase-N-forensic-output-2026-05-17.txt` + `phase-N-forensic-summary.md`
- `state/research/phase-N-charts/*.png` (14 files)
- `state/phases/phase-N-forensic-audit.md` + `phase-O-remediation.md`
- `state/sessions/2026-05-17-phase-N-*` + `2026-05-17-phase-O-session-1-bot-resumed.md` + `2026-05-18-phase-O-session-2-prep.md`

## Source notes

- Phase N PDF (22 pp, 14 charts) is the empirical backbone for all DROP/KEEP
  verdicts that cite "Phase N" above.
- Phase O Session 1 already implemented Phase N's #1 recommendation (disable
  M.1a v1), but layered on additional features (SURV canary, bankroll
  override, L.5 scale) that the operator concluded did not deliver before
  the revert decision.
- 5-day decision data preserved at:
  `state/decisions/archived/phase-P-reset/2026-05-{13..17}.jsonl`
  `state/decisions-resolved/archived/phase-P-reset/2026-05-{13..17}.jsonl`
  Plus the original Phase N tarball at `/tmp/phaseN_data/` on VPS.
- This inventory will be the input to the Session-2 MMD backtest extension
  of `scripts/research/phase_n_forensic_audit.py`.

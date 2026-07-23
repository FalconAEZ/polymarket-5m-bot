# W.1 — Weather-ladder strategy: paper re-validation (Mission B)

> 2026-07-23. Design doc gates `scripts/research/weather_scan.py` (anti-vibe rule #1).
> Scope: **research scanner + paper evidence only.** No order code, no keys, no live path.
> Source thesis: RELAUNCH_BRIEF_2026-07-23.md §2 family #2 (verified practitioners: ColdMath
> ~$74k/1.58% margin; automatedAItradingbot ~$88.5k since Jan 2025 via 3–10¢ model laddering).

## Thesis

Polymarket runs daily "Highest temperature in <city> on <date>" events (59 open city-days observed
2026-07-23), each a ladder of ~11 integer-degree buckets trading as independent binaries. Prices are
set by retail flow and reprice slowly after weather-model runs, while a numerical forecast plus a
lead-time error model prices every bucket objectively. When model P(bucket) materially exceeds the
ask on a cheap bucket (≤20¢), buying YES has positive expected value net of the 0.05-coefficient
taker fee. Resolution is objective (official station observations), there is no latency war, and
capacity is retail-scale — the opposite profile of the BTC 5-min game that failed.

## Market anatomy (measured 2026-07-23)

- Gamma: `GET /events?tag_slug=weather&closed=false` → event per city-day
  (`highest-temperature-in-<city>-on-<month>-<day>-2026`), `markets[]` = buckets with
  `groupItemTitle` ("15°C or below" | "16-17°C" | "24°C or above"), `bestBid`/`bestAsk`,
  `clobTokenIds`. °C for non-US cities, °F for US.
- Zombie events exist (past `endDate`, still `closed=false`) → filter to target dates ≥ today.
- CLOB `GET /book?token_id=` for depth on flagged candidates only. **Book levels are worst-first on
  both sides** (archive lesson `project_polymarket_book_sort_order_2026_05_25`) — take
  `min(asks)`/`max(bids)` explicitly.

## Model v1

1. Forecast: Open-Meteo daily `temperature_2m_max` (free, global, keyless), city-local date.
2. Error model: T_actual ~ Normal(T_forecast, σ(lead)), σ = 1.2 °C same-day / 1.6 °C +1d / 2.2 °C
   +2d (×1.8 in °F). **These σ are priors, not calibrated claims** — calibrating them is what the
   soak measures.
3. Bucket probability: integer-rounded resolution ⇒ P("16-17") = Φ((17.5−μ)/σ) − Φ((15.5−μ)/σ);
   tails are open-ended.
4. Economics per share at ask *a*: taker fee = 0.05·a·(1−a); EV/share = P − a − fee;
   breakeven P* = a·(1 + 0.05·(1−a)). EV per $ staked = EV/share ÷ a.

## Candidate filter (the "ladder zone")

Two stages (day-0 run proved gamma-only filtering flags untradeable sub-cent dust quotes):
1. **Provisional** (gamma prices): 0 < ask ≤ 0.20, EV per $ ≥ +0.25, model P ≥ 2× breakeven.
2. **Verified** (CLOB book re-check, top 25 provisional, real-priced first): book best ask
   ∈ [0.02, 0.20], cumulative ask notional within best+2¢ ≥ $25 (day-0 instrument note:
   single-level depth measured $0.2–$10 — a fill sweeps levels, so depth is cumulative;
   set pre-soak, frozen thereafter), EV per $ at the *book* ask ≥ +0.25. **Only verified
   candidates count toward the gate.** Everything is still **logged** — the full bucket table
   (model P vs market price for every open bucket) is the calibration dataset.

## Soak protocol

Run `python3 scripts/research/weather_scan.py` ≥1×/day (any hour; each run snapshots to
`state/research/weather/scan-<UTC>.jsonl` + prints the candidate table). 14 consecutive days
minimum. Zero config changes mid-soak (change ⇒ restart the 14-day clock). After each city-day
resolves, the next run auto-scores prior snapshots against realized outcomes (winning bucket from
the resolved market's 1.00/0.00 prices).

## Pre-registered gate (evaluate 2026-08-06 or later — no peeking-based edits)

- **G1 edge:** verified candidates, n ≥ 25: realized win rate ≥ 1.3 × mean breakeven P*.
- **G2 calibration:** model Brier score ≤ market Brier score over all logged buckets (model must
  beat the market's own prices as a forecaster, else there is no edge to harvest).
- **G3 capacity:** ≥ 15 flagged candidates/week AND median best-ask depth on flagged candidates
  ≥ $50 notional.
- **Hard NO-GO:** any of — n < 25 flagged in 14d; G1 fails; G2 fails. PASS on all three ⇒ operator
  decision on Mission C (micro-live per RELAUNCH_BRIEF §3 governance: flat ≤5% bankroll, −25%
  auto-halt, profit ladder, L.5-equivalent guard before the first order).

## Known risks / stated assumptions

1. Open-Meteo model output ≠ the resolution source (official station obs); v1.1 should score
   against the exact named station (NWS CLI reports for US cities) and adjust per-city bias.
2. Same-day markets: part of the day is already realized — σ=1.2 °C overstates uncertainty late in
   the local day (bias flags toward stale intraday buckets). v1 mitigations: none; noted for
   calibration. Do not trade same-day candidates in any future live mission until v1.1 handles this.
3. Fee coefficient 0.05 assumed for weather (docs, Jul 2026); re-verify at gate time.
4. Thin books: gamma bestAsk can be stale vs CLOB; flagged candidates re-check via CLOB book.
5. σ priors are hand-set; G2 exists precisely to catch them being wrong.

## v1.1 roadmap (only if gate passes)

Exact-station scoring (NWS CLI / METAR), per-city bias + σ fit from soak data, ensemble spread
(Open-Meteo ensemble API) instead of fixed σ, depth-aware sizing sim, UK/EU station sources.

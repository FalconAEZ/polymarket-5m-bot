/**
 * DashboardState — TypeScript shape mirroring the FastAPI snapshot.
 * Per design/dashboard-v3.md §4.2. Backend authority is
 * src/polymarket_bot/dashboard_server/state.py:snapshot().
 */

export type Tone = "good" | "bad" | "warn" | "muted" | "neutral"
export type Mode = "AGGRESSIVE" | "SPOT_AWARE" | "DETERMINISTIC" | "WAITING"
export type Side = "UP" | "DOWN"
export type StageStatus = "alive" | "pending" | "warn" | "dead"

export interface ModeBlock {
  label: Mode
  tone: Tone
  raw: string | null
}

export interface BankrollBlock {
  starting_usd: number
  current_usd: number
  delta_usd: number
  delta_pct: number
}

export interface AggBlock {
  n_fired: number
  n_filled: number
  n_settled: number
  n_won: number
  win_rate: number | null
  avg_pnl_per_filled: number | null
  total_pnl_usd: number
}

export interface StreakBlock {
  glyph: string
  n: number
  best_win: number
  worst_loss: number
}

export interface PaceBlock {
  usd_per_hour: number
  n_settled_60m: number
}

export interface TodayBlock {
  pnl_usd: number | null
  n_settled: number
}

export interface FireRateBlock {
  per_hour: number
  fires_24h: number
  projected_per_day: number
}

export interface PipelineBlock {
  capture_ms: number | null
  strategy_ms: number | null
  sim_fill_ms: number | null
  settle_wait_s: number | null
  resolve_ms: number | null
  persist_ms: number | null
}

export interface FeedSnapshot {
  name: string
  msgs_seen: number
  healthy: boolean
  reconnects: number
  last_error: string
  last_seen_ns: number
}

export interface ProcessSnapshot {
  name: string
  pid: number | null
  alive: boolean
  create_time_utc: string | null
}

export interface ProcessesBlock {
  capture: ProcessSnapshot
  paper: ProcessSnapshot
}

export interface RttProvider {
  name: string
  samples: (number | null)[]
  last_ms: number | null
  last_age_s: number
}

export interface ProviderRttBlock {
  providers: RttProvider[]
  last_sample_age_s: number | null
}

export interface TierBreakdownRow {
  tier: string
  n_fired: number
  n_filled: number
  n_settled: number
  n_won: number
  win_rate: number | null
  pnl_usd: number
}

export interface TripWire {
  name: string
  current_str: string
  current: number | null
  threshold_str: string
  breach: boolean
  progress_pct: number
}

export interface DecisionTapeRow {
  decision_id: string
  window_ts: number
  decision_dt_utc: string
  side: Side
  size_usd: number
  price_limit: number
  fill_price: number | null
  ttl_s: number
  strategy: string | null
  mode: string | null
  delta_bps: number | null
  p_win: number | null
  ev_dollars: number | null
  resolution: Side | null
  pnl_usd: number | null
  won: boolean | null
  tier: string
}

export interface Candle {
  ts: number  // unix seconds (start of bar)
  o: number
  h: number
  l: number
  c: number
  v: number
}

export interface ChartBlock {
  candles: Candle[]
  last_price: number | null
  change_pct: number | null
}

export interface BookLevel {
  p: number
  s: number
}

export interface SpotBookBlock {
  asks: BookLevel[]
  bids: BookLevel[]
  mid: number | null
  ts_ns: number
}

export interface CtfBookBlock {
  window_ts: number | null
  side: Side | null
  slug: string | null
  asks: BookLevel[]
  bids: BookLevel[]
  mid: number | null
  ts_ns: number
}

export interface DisagreementBlock {
  n_resolved: number
  rate: number | null
  last_disagree_window_ts: number | null
}

export interface BestTierBlock {
  label: string | null
  pnl_usd: number | null
}

/** Single point on the running PnL curve. Backend `cumulative_pnl_series`
 * field — one entry per settled decision, sorted ascending by ts. */
export interface CumulativePnlPoint {
  ts: number
  pnl: number
}

export interface DashboardState {
  schema_version: number
  now_utc_iso: string
  now_utc_ns: number
  mode: ModeBlock
  bankroll: BankrollBlock
  agg: AggBlock
  streak: StreakBlock
  pace: PaceBlock
  today: TodayBlock
  fire_rate: FireRateBlock
  pipeline: PipelineBlock
  feeds: FeedSnapshot[]
  feeds_snapshot_age_s: number | null
  processes: ProcessesBlock
  provider_rtt: ProviderRttBlock
  tier_breakdown: TierBreakdownRow[]
  best_tier: BestTierBlock
  cumulative_pnl_series: CumulativePnlPoint[]
  trip_wires: TripWire[]
  halt_requested: boolean
  incidents: string[]
  decisions: DecisionTapeRow[]
  n_decisions_total: number
  chart: ChartBlock
  spot_book: SpotBookBlock
  ctf_book: CtfBookBlock
  disagreement: DisagreementBlock
}

export type WsMessage =
  | { type: "snapshot"; state: DashboardState }
  | { type: "patch"; ops: unknown[] }

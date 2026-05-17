import { motion } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { fmtUsd, fmtPct } from "../lib/format"
import { cn } from "../lib/cn"
import type { TierBreakdownRow } from "../store/types"

/**
 * Per-tier discipline panel — one row per price tier. Each row shows a
 * stacked-bar visualization (fired → filled → settled → won) and the
 * cumulative PnL on the right. Bars animate in with `width` transition.
 */
export function TierBreakdownPanel() {
  const s = useDashboard()
  if (!s) return <Panel title="PER-TIER DISCIPLINE" />
  const tiers = s.tier_breakdown
  if (tiers.length === 0) {
    return (
      <Panel title="PER-TIER DISCIPLINE">
        <div className="text-[10px] text-text-muted py-2">
          no fires yet to break down by tier.
        </div>
      </Panel>
    )
  }
  const maxFired = Math.max(...tiers.map((t) => t.n_fired), 1)
  return (
    <Panel title="PER-TIER DISCIPLINE" subtitle={`${tiers.length} tiers · live`}>
      <div className="flex flex-col gap-1.5 mt-1">
        {tiers.map((t) => (
          <TierRow key={t.tier} t={t} maxFired={maxFired} />
        ))}
      </div>
    </Panel>
  )
}

function TierRow({ t, maxFired }: { t: TierBreakdownRow; maxFired: number }) {
  const firedPct = (t.n_fired / maxFired) * 100
  const filledPct = t.n_fired > 0 ? (t.n_filled / t.n_fired) * 100 : 0
  const wonPct = t.n_settled > 0 ? (t.n_won / t.n_settled) * 100 : 0
  const pnlTone =
    t.pnl_usd > 0 ? "text-good" : t.pnl_usd < 0 ? "text-bad" : "text-text-secondary"
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between gap-2 text-[10px]">
        <span className="font-bold uppercase tracking-[0.06em] text-text-primary tabular-nums">
          {t.tier}
        </span>
        <span className="text-text-muted tabular-nums">
          {t.n_fired} fires · {t.n_filled} filled · {t.n_won}/{t.n_settled} won
        </span>
        <span className={cn("font-mono font-bold tabular-nums", pnlTone)}>
          {fmtUsd(t.pnl_usd)}
        </span>
      </div>
      <div
        className="grid grid-rows-1 h-1.5 rounded-sm overflow-hidden bg-bg-inset relative"
        style={{ width: `${firedPct}%` }}
      >
        <div className="absolute inset-y-0 left-0 bg-text-muted opacity-50" style={{ width: "100%" }} />
        <motion.div
          className="absolute inset-y-0 left-0 bg-text-secondary opacity-70"
          initial={{ width: 0 }}
          animate={{ width: `${filledPct}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
        <motion.div
          className="absolute inset-y-0 left-0 bg-good"
          initial={{ width: 0 }}
          animate={{ width: `${wonPct}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>
      <div className="flex items-baseline gap-2 text-[8.5px] uppercase tracking-widest text-text-muted">
        <span>WR {fmtPct(t.win_rate, 0)}</span>
      </div>
    </div>
  )
}

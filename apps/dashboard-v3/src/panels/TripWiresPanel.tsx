import { motion } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { cn } from "../lib/cn"

/**
 * Aggressive-mode trip-wires panel. Renders only when trip_wires has
 * entries (i.e. the active mode is "aggressive"). Each wire shows the
 * current value, threshold, and a smooth progress bar that fills toward
 * breach.
 */
export function TripWiresPanel() {
  const s = useDashboard()
  if (!s || s.trip_wires.length === 0) {
    return (
      <Panel title="TRIP-WIRES" subtitle="aggressive-mode only">
        <div className="text-[10px] text-text-muted py-2">
          inactive · only renders when mode=aggressive
        </div>
      </Panel>
    )
  }
  return (
    <Panel
      title="AGGRESSIVE-MODE TRIP-WIRES"
      subtitle="exit criteria · live"
      badge={s.trip_wires.some((w) => w.breach) ? "BREACH" : "OK"}
      badgeTone={s.trip_wires.some((w) => w.breach) ? "bad" : "good"}
    >
      <div className="flex flex-col gap-2 mt-1">
        {s.trip_wires.map((w) => (
          <Wire key={w.name} {...w} />
        ))}
      </div>
    </Panel>
  )
}

function Wire({
  name,
  current_str,
  threshold_str,
  breach,
  progress_pct,
}: {
  name: string
  current_str: string
  threshold_str: string
  breach: boolean
  progress_pct: number
}) {
  const fillColor = breach ? "bg-bad" : progress_pct > 70 ? "bg-warn" : "bg-good"
  const tone = breach ? "text-bad" : "text-text-primary"
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between gap-2 text-[10px]">
        <span className={cn("font-bold uppercase tracking-[0.06em]", tone)}>
          {breach ? "🛑" : "✓"} {name}
        </span>
        <span className="font-mono tabular-nums text-text-primary">{current_str}</span>
      </div>
      <div className="h-1 bg-bg-inset rounded-sm overflow-hidden">
        <motion.div
          className={cn("h-full rounded-sm", fillColor)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, Math.max(0, progress_pct))}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>
      <div className="text-[8.5px] uppercase tracking-widest text-text-muted">
        threshold: {threshold_str}
      </div>
    </div>
  )
}

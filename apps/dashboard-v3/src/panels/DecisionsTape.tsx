import { motion, AnimatePresence } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { fmtUsd } from "../lib/format"
import { cn } from "../lib/cn"
import { Panel } from "./_Panel"
import type { DecisionTapeRow } from "../store/types"

/**
 * Custom decisions tape — rows animate in from the top when new
 * decisions arrive (Framer Motion AnimatePresence). Each row carries:
 *  - left border color (green won, red lost, amber pending)
 *  - side glyph (▲ UP / ▼ DOWN)
 *  - tier label
 *  - PnL with proportional bar fill behind the number
 *  - hover reveals the rationale fields (delta_bps, p_win, ev)
 */
export function DecisionsTape() {
  const s = useDashboard()
  if (!s) return <Panel title="DECISIONS TAPE" />

  return (
    <Panel title="DECISIONS TAPE" subtitle={`${s.n_decisions_total} total · newest first`}>
      {/*
        flex-1 + min-h-0 is the canonical "let me shrink under flex"
        idiom — without min-h-0 the table's intrinsic size forces the
        scroll container to grow past its parent on Safari (operator
        screenshot — 89 rows × 22px overflowed the panel boundary).
      */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <table className="w-full text-[10.5px] tabular-nums">
          <thead className="sticky top-0 bg-bg-panel z-10">
            <tr className="text-text-muted text-[9px] uppercase tracking-[0.08em]">
              <th className="text-left font-bold py-1.5">When</th>
              <th className="text-left font-bold py-1.5">Side</th>
              <th className="text-left font-bold py-1.5">Tier</th>
              <th className="text-right font-bold py-1.5">Limit</th>
              <th className="text-right font-bold py-1.5">Fill</th>
              <th className="text-right font-bold py-1.5">PnL</th>
              <th className="text-right font-bold py-1.5">Δbps</th>
              <th className="text-right font-bold py-1.5">p_win</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {s.decisions.map((d) => (
                <DecisionRow key={d.decision_id} d={d} />
              ))}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function DecisionRow({ d }: { d: DecisionTapeRow }) {
  const won =
    d.resolution !== null && d.fill_price !== null && d.resolution === d.side
  const lost = d.resolution !== null && d.fill_price !== null && !won
  const sideUp = d.side === "UP"

  const borderTone = won
    ? "border-l-good"
    : lost
      ? "border-l-bad"
      : "border-l-warn"

  const pnlTone =
    d.pnl_usd === null
      ? "text-text-muted"
      : d.pnl_usd > 0
        ? "text-good"
        : d.pnl_usd < 0
          ? "text-bad"
          : "text-text-secondary"

  // PnL bar: width proportional to abs(pnl) clamped at 100%.
  const pnlBarPct =
    d.pnl_usd === null ? 0 : Math.min(100, (Math.abs(d.pnl_usd) / 5.0) * 100)
  const pnlBarColor =
    d.pnl_usd === null
      ? "transparent"
      : d.pnl_usd >= 0
        ? "rgba(110, 255, 161, 0.18)"
        : "rgba(255, 92, 92, 0.18)"

  const time = new Date(d.decision_dt_utc).toISOString().substring(11, 19)

  return (
    <motion.tr
      initial={{ opacity: 0, y: -8, scaleY: 0.92 }}
      animate={{ opacity: 1, y: 0, scaleY: 1 }}
      exit={{ opacity: 0, y: 6 }}
      transition={{ duration: 0.28, ease: [0.65, 0, 0.3, 1] }}
      className={cn(
        "border-l-2 hover:bg-bg-panel-hi transition-colors duration-150",
        borderTone,
      )}
    >
      <td className="px-2 py-0.5 text-text-secondary">{time}</td>
      <td className="px-2 py-0.5">
        <span className={cn("font-bold", sideUp ? "text-good" : "text-bad")}>
          {sideUp ? "▲" : "▼"} {d.side}
        </span>
      </td>
      <td className="px-2 py-0.5 text-text-secondary">{d.tier}</td>
      <td className="px-2 py-0.5 text-right text-text-secondary">
        {d.price_limit.toFixed(3)}
      </td>
      <td className="px-2 py-0.5 text-right text-text-secondary">
        {d.fill_price !== null ? d.fill_price.toFixed(3) : "—"}
      </td>
      <td className="px-2 py-0.5 text-right relative">
        {pnlBarPct > 0 && (
          <motion.div
            className="absolute right-0 top-0 bottom-0 rounded-sm"
            style={{ backgroundColor: pnlBarColor }}
            initial={{ width: 0 }}
            animate={{ width: `${pnlBarPct}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        )}
        <span className={cn("relative z-10 font-bold", pnlTone)}>
          {fmtUsd(d.pnl_usd, 2)}
        </span>
      </td>
      <td
        className={cn(
          "px-2 py-0.5 text-right tabular-nums",
          d.delta_bps === null
            ? "text-text-muted"
            : d.delta_bps >= 0
              ? "text-good"
              : "text-bad",
        )}
      >
        {/* Display raw basis points (typical [-50..+50] bps range). */}
        {d.delta_bps !== null
          ? (d.delta_bps >= 0 ? "+" : "") + d.delta_bps.toFixed(1)
          : "—"}
      </td>
      <td className="px-2 py-0.5 text-right text-text-secondary">
        {d.p_win !== null ? d.p_win.toFixed(3) : "—"}
      </td>
    </motion.tr>
  )
}

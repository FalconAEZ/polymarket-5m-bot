import { useDashboard } from "../store/dashboardStore"
import { TickerScroll } from "../motion/TickerScroll"
import { fmtUsd } from "../lib/format"
import { cn } from "../lib/cn"
import type { DecisionTapeRow } from "../store/types"

/**
 * Continuous-scroll live tape. Newest 12 settled+filled events, rendered
 * twice (TickerScroll handles the seamless duplication). Pause on hover
 * for readability.
 */
export function LiveTape() {
  const s = useDashboard()
  const events = (s?.decisions ?? [])
    .filter((d) => d.resolution !== null && d.fill_price !== null)
    .slice(0, 12)
  if (events.length === 0) {
    return (
      <div className="h-7 border-y border-border-subtle bg-bg-inset px-4 flex items-center text-[10px] uppercase tracking-widest text-text-muted">
        ● live tape · awaiting first settled decision
      </div>
    )
  }
  return (
    <div className="h-7 border-y border-border-subtle bg-bg-inset overflow-hidden">
      <TickerScroll duration={60} className="h-full">
        {events.map((e) => (
          <Event key={e.decision_id} d={e} />
        ))}
      </TickerScroll>
    </div>
  )
}

function Event({ d }: { d: DecisionTapeRow }) {
  const won = d.resolution === d.side
  const tone = won ? "text-good" : "text-bad"
  const glyph = won ? "▲" : "▼"
  const label = won ? "WIN" : "LOSS"
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] font-medium tabular-nums",
        tone,
      )}
    >
      <span>{glyph}</span>
      <span>{label}</span>
      <span>{fmtUsd(d.pnl_usd)}</span>
      <span className="text-text-muted">·</span>
      <span>{d.tier}</span>
      <span className="text-text-muted">·</span>
      <span>{d.side}</span>
      {d.p_win !== null && (
        <>
          <span className="text-text-muted">· win=</span>
          <span>{d.p_win.toFixed(2)}</span>
        </>
      )}
    </span>
  )
}

import { motion, AnimatePresence } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { fmtUsd } from "../lib/format"
import { cn } from "../lib/cn"
import { PulseDot } from "../motion/PulseDot"
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
// 5-minute Polymarket window length in seconds. Identical to
// resolver.WINDOW_SECONDS on the Python side; duplicated here to avoid
// pulling a backend constant into the React bundle just for one panel.
const WINDOW_DURATION_S = 300

export function DecisionsTape() {
  const s = useDashboard()
  if (!s) return <Panel title="DECISIONS TAPE" />

  // Server-supplied "now" so the countdown advances on every WS push
  // (~1s) without each row needing its own setInterval. The ISO string
  // is precise to milliseconds, well within the precision we need to
  // render an MM:SS countdown.
  const nowS = Date.parse(s.now_utc_iso) / 1000
  // Current 5m window open at this moment (UTC). Independent of whether
  // the bot has fired — surfaces "the live market" to the operator even
  // when v2 is being patient (ev_min=0.05 → ~1 fire/day).
  const currentWindowTs = Math.floor(nowS / WINDOW_DURATION_S) * WINDOW_DURATION_S
  // Has the bot already fired in the current window? If yes, the existing
  // row at the top of the tape covers it — don't render a duplicate
  // "WAITING" banner. If no, the banner shows below.
  const firedInCurrentWindow =
    s.decisions.length > 0 && s.decisions[0].window_ts === currentWindowTs

  return (
    <Panel title="DECISIONS TAPE" subtitle={`${s.n_decisions_total} total · newest first`}>
      {!firedInCurrentWindow && (
        <LiveWindowBanner currentWindowTs={currentWindowTs} nowS={nowS} />
      )}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <table className="w-full text-[10.5px] tabular-nums">
          <thead className="sticky top-0 bg-bg-panel z-10">
            <tr className="text-text-muted text-[9px] uppercase tracking-[0.08em]">
              <th className="text-left font-bold py-1.5">When</th>
              <th className="text-left font-bold py-1.5">Market</th>
              <th className="text-left font-bold py-1.5">Side</th>
              <th className="text-left font-bold py-1.5">Tier</th>
              <th className="text-right font-bold py-1.5">Limit</th>
              <th className="text-right font-bold py-1.5">Fill</th>
              <th className="text-right font-bold py-1.5">PnL · Status</th>
              <th className="text-right font-bold py-1.5">Δbps</th>
              <th className="text-right font-bold py-1.5">p_win</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
              {s.decisions.map((d) => (
                <DecisionRow key={d.decision_id} d={d} nowS={nowS} />
              ))}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/** Banner shown ABOVE the tape when the bot has not (yet) fired in the
 * current 5m window. Surfaces the live market with a countdown so the
 * operator can see "the bot is watching this window" rather than a tape
 * full of stale fires. Replaced by a normal DecisionRow once the bot
 * commits to a fire.
 *
 * Per the 2026-05-10 operator feedback ("decisions tape is not showing
 * current 5min btc market"). v2 with ev_min=0.05 fires ~1/day, so most
 * windows look "empty" in the tape — this banner makes the live state
 * explicit. */
function LiveWindowBanner({
  currentWindowTs,
  nowS,
}: {
  currentWindowTs: number
  nowS: number
}) {
  const windowEndS = currentWindowTs + WINDOW_DURATION_S
  const secondsLeft = Math.max(0, windowEndS - nowS)
  const minutesElapsed = WINDOW_DURATION_S - secondsLeft
  // Progress 0→1 across the 5m window, used for the inset bar fill.
  const progress = Math.min(1, Math.max(0, minutesElapsed / WINDOW_DURATION_S))
  return (
    <div
      key={currentWindowTs}
      className={cn(
        "pmb-fade-in relative mb-1 flex items-center gap-3 overflow-hidden rounded-sm border bg-bg-panel-hi px-2.5 py-1.5",
        "border-[rgba(255,184,74,0.32)]",
      )}
    >
      <PulseDot tone="warn" />
      <div className="flex flex-col leading-tight">
        <span className="text-[8.5px] font-bold uppercase tracking-[0.10em] text-text-muted">
          live window · waiting for signal
        </span>
        <span className="font-mono text-[11px] font-bold tabular-nums text-text-primary">
          {currentWindowTs}
        </span>
      </div>
      <div className="ml-auto flex flex-col items-end leading-tight">
        <span className="text-[8.5px] font-bold uppercase tracking-[0.10em] text-text-muted">
          closes in
        </span>
        <span className="font-mono text-[12px] font-bold tabular-nums text-warn">
          {fmtCountdown(secondsLeft)}
        </span>
      </div>
      {/* progress bar — fills left→right across the 5m window */}
      <motion.div
        className="absolute bottom-0 left-0 h-[2px] bg-warn/60"
        initial={false}
        animate={{ width: `${progress * 100}%` }}
        transition={{ duration: 0.6, ease: "easeOut" }}
      />
    </div>
  )
}

function fmtCountdown(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

function DecisionRow({ d, nowS }: { d: DecisionTapeRow; nowS: number }) {
  const won =
    d.resolution !== null && d.fill_price !== null && d.resolution === d.side
  const lost = d.resolution !== null && d.fill_price !== null && !won
  const sideUp = d.side === "UP"
  // Open = no resolution yet. Window closes WINDOW_DURATION_S after
  // window_ts; Polymarket then takes another ~60-90s to publish the
  // truth. We surface those phases distinctly so the operator can tell
  // "still betting" from "waiting for oracle".
  const open = d.resolution === null
  const windowEndS = d.window_ts + WINDOW_DURATION_S
  const secondsLeft = windowEndS - nowS
  const inWindow = open && secondsLeft > 0
  const settling = open && secondsLeft <= 0

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
    // Entry animation is fade + scaleY only — NO `y` translate. Per the
    // Phase 11.A.2 hand-off Item 2.1 ("operator: tape isn't showing the
    // last trade"): the previous `y: -8` initial state slid the new top
    // row UP into the sticky <thead> region. The thead has `z-10` and
    // <motion.tr> creates its own stacking context via the transform,
    // so the row stacks at z-auto BELOW the thead during the entire
    // 280ms entry animation — on Safari this sometimes settled with the
    // row still partially clipped. Fading in at position avoids any
    // overlap with the sticky header. The exit animation keeps the y
    // offset because exit happens at the BOTTOM of the tape (row 100
    // sliding off) where there is no sticky element to clip against.
    <motion.tr
      initial={{ opacity: 0, scaleY: 0.92 }}
      animate={{ opacity: 1, scaleY: 1 }}
      exit={{ opacity: 0, y: 6 }}
      transition={{ duration: 0.28, ease: [0.65, 0, 0.3, 1] }}
      className={cn(
        "border-l-2 hover:bg-bg-panel-hi transition-colors duration-150",
        borderTone,
      )}
    >
      <td className="px-2 py-0.5 text-text-secondary">{time}</td>
      <td className="px-2 py-0.5 text-text-secondary font-mono">{d.window_ts}</td>
      <td className="px-2 py-0.5">
        <span className={cn("font-bold", sideUp ? "text-good" : "text-bad")}>
          {sideUp ? "▲" : "▼"} {d.side}
        </span>
        {d.fire_total !== null && d.fire_total > 1 && d.fire_n !== null && (
          // v2.1 multi-fire marker (H.2.7). Each fire in a multi-fire
          // window is an INDEPENDENT decision with its own pnl; the
          // badge surfaces "1/2" vs "2/2" so the operator can tell the
          // two rows apart at a glance. Single-fire strategies (cap=1)
          // omit the marker entirely.
          <span
            className="ml-1.5 rounded-sm border border-text-muted/40 px-1 py-px text-[8.5px] font-bold tracking-[0.05em] text-text-muted tabular-nums"
            title={`multi-fire ${d.fire_n} of ${d.fire_total} in this window`}
          >
            {d.fire_n}/{d.fire_total}
          </span>
        )}
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
        {inWindow ? (
          <span className="relative z-10 font-bold text-warn tabular-nums">
            {fmtCountdown(secondsLeft)} left
          </span>
        ) : settling ? (
          <span className="relative z-10 font-bold text-text-muted">
            settling…
          </span>
        ) : (
          <span className={cn("relative z-10 font-bold", pnlTone)}>
            {fmtUsd(d.pnl_usd, 2)}
          </span>
        )}
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

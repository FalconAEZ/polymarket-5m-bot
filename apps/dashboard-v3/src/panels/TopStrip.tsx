import { motion } from "framer-motion"
import { useEffect, useState } from "react"
import { useDashboard, useWsStatus } from "../store/dashboardStore"
import { PulseDot } from "../motion/PulseDot"
import { DigitRoll } from "../motion/DigitRoll"
import { fmtClock, fmtUsdPlain, fmtDeltaPct, fmtPctRaw } from "../lib/format"
import { cn } from "../lib/cn"

const MODE_TONE: Record<string, string> = {
  AGGRESSIVE: "text-warn border-border-amber bg-[rgba(255,184,74,0.06)]",
  SPOT_AWARE: "text-good border-[rgba(110,255,161,0.32)] bg-[rgba(110,255,161,0.04)]",
  DETERMINISTIC: "text-text-secondary border-border-subtle",
  WAITING: "text-text-secondary border-border-subtle",
}

export function TopStrip() {
  const s = useDashboard()
  const ws = useWsStatus()
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  if (!s) {
    return (
      <header className="flex items-center justify-between border-b border-border-subtle px-4 py-2.5">
        <div className="flex items-center gap-3">
          <PulseDot tone="warn" />
          <span className="text-xs uppercase tracking-widest text-text-secondary">
            connecting…
          </span>
        </div>
        <span className="text-xs text-text-muted">{fmtClock(now.toISOString())}</span>
      </header>
    )
  }

  const wsTone = ws === "open" ? "good" : ws === "reconnecting" ? "warn" : "bad"
  const bankrollTone =
    s.bankroll.delta_usd > 0
      ? "text-good"
      : s.bankroll.delta_usd < 0
        ? "text-bad"
        : "text-text-secondary"

  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1.5 border-b border-border-subtle px-4 py-2.5">
      {/* LEFT cluster */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 min-w-0">
        <PulseDot tone={wsTone} />
        <span className="font-sans text-sm font-bold uppercase tracking-[0.04em] text-text-primary">
          POLYMARKET 5M
        </span>
        <span className="text-[10px] uppercase tracking-widest text-text-muted">v3</span>
        <motion.div
          key={s.mode.label}
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          className={cn(
            "rounded-sm border px-2 py-0.5 text-[10px] font-bold tracking-[0.10em]",
            MODE_TONE[s.mode.label] ?? MODE_TONE.WAITING,
            s.mode.label === "AGGRESSIVE" &&
              "[animation:pmb-glow_2.4s_ease-in-out_infinite]",
          )}
        >
          {s.mode.label}
        </motion.div>
        <span className="text-[10px] uppercase tracking-[0.06em] text-text-muted">
          phase H v2.1
        </span>
      </div>

      {/* RIGHT cluster: BTC price · bankroll · clock · ws status */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {s.chart.last_price !== null && (
          <span className="flex items-baseline gap-1.5">
            <span className="text-[10px] uppercase tracking-widest text-text-muted">
              BTC
            </span>
            <span className="font-mono text-sm font-bold tabular-nums text-text-primary">
              {fmtUsdPlain(s.chart.last_price, 2)}
            </span>
            {s.chart.change_pct !== null && (
              <span
                className={cn(
                  "text-[10px] tabular-nums",
                  s.chart.change_pct >= 0 ? "text-good" : "text-bad",
                )}
              >
                {fmtPctRaw(s.chart.change_pct, 2)}
              </span>
            )}
          </span>
        )}

        <span className="flex items-baseline gap-1.5 rounded-sm border border-border-subtle bg-bg-panel px-2 py-0.5">
          <span className="text-[9px] font-bold uppercase tracking-widest text-text-muted">
            BANKROLL
          </span>
          <DigitRoll
            value={fmtUsdPlain(s.bankroll.current_usd, 2)}
            className="font-mono text-xs font-bold tabular-nums text-text-primary"
            duration={0.4}
          />
          <span className={cn("text-[10px] font-bold tabular-nums", bankrollTone)}>
            {fmtDeltaPct(s.bankroll.delta_pct)}
          </span>
        </span>

        <span className="text-[10px] uppercase tracking-widest text-text-muted tabular-nums">
          {s.processes.paper.alive ? (
            <span className="text-good">PAPER ALIVE</span>
          ) : (
            <span className="text-bad">PAPER OFFLINE</span>
          )}
        </span>

        <span className="font-mono text-xs tabular-nums text-text-secondary">
          {fmtClock(now.toISOString())}
        </span>
      </div>
    </header>
  )
}

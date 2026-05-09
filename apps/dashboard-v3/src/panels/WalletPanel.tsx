import { motion } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { DigitRoll } from "../motion/DigitRoll"
import { fmtUsd, fmtUsdPlain, fmtPct, fmtInt, fmtAge, fmtDeltaPct } from "../lib/format"
import { cn } from "../lib/cn"
import { Panel } from "./_Panel"

export function WalletPanel() {
  const s = useDashboard()
  if (!s) return <Panel title="WALLET · BANKROLL" subtitle="—" />

  const delta = s.bankroll.delta_usd
  const sign = delta >= 0 ? "+" : "-"
  const heroValue = `${sign}$${Math.abs(delta).toFixed(2)}`
  const heroTone =
    delta > 0
      ? "text-good drop-shadow-[0_0_18px_rgba(110,255,161,0.30)]"
      : delta < 0
        ? "text-bad drop-shadow-[0_0_18px_rgba(255,92,92,0.30)]"
        : "text-text-primary"

  const elapsedLabel =
    s.agg.n_fired === 0
      ? "—"
      : (() => {
          // First decision time isn't on the snapshot directly; use
          // n_fired count + a synthetic label. Backend can add this in v3.1.
          return `${s.agg.n_fired} TRADES`
        })()

  return (
    <Panel
      title="WALLET · BANKROLL"
      badge={s.mode.label}
      badgeTone={s.mode.tone}
      subtitle="BTC POLYMARKET · 5M UP/DOWN"
    >
      <div className="flex flex-col gap-1">
        <div className="text-[9px] uppercase tracking-widest text-text-muted mt-1">
          SESSION PNL
        </div>
        <DigitRoll
          value={heroValue}
          className={cn(
            "font-mono text-[44px] font-bold leading-none tabular-nums tracking-[-0.02em]",
            heroTone,
          )}
          duration={0.55}
        />
        <div className="flex items-baseline gap-2 text-[10px]">
          <motion.span
            key={`pct-${s.bankroll.delta_pct.toFixed(3)}`}
            initial={{ opacity: 0, y: -2 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className={cn(
              "font-bold tabular-nums px-1.5 py-px rounded-sm",
              delta >= 0
                ? "text-good bg-[rgba(110,255,161,0.10)]"
                : "text-bad bg-[rgba(255,92,92,0.10)]",
            )}
          >
            {delta >= 0 ? "▲" : "▼"} {fmtDeltaPct(s.bankroll.delta_pct).replace("+", "").replace("-", "")}
          </motion.span>
          <span className="text-text-muted">· {elapsedLabel}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-auto pt-2 border-t border-border-subtle">
        <Stat label="TRADES" value={fmtInt(s.agg.n_fired)} />
        <Stat
          label="WIN%"
          value={fmtPct(s.agg.win_rate)}
          tone={
            s.agg.win_rate === null
              ? "muted"
              : s.agg.win_rate >= 0.55
                ? "good"
                : s.agg.win_rate < 0.45
                  ? "bad"
                  : "warn"
          }
        />
        <Stat
          label="AVG/TR"
          value={fmtUsd(s.agg.avg_pnl_per_filled, 3)}
          tone={
            s.agg.avg_pnl_per_filled === null
              ? "muted"
              : s.agg.avg_pnl_per_filled >= 0
                ? "good"
                : "bad"
          }
        />
      </div>
      <div className="text-[9px] tabular-nums text-text-muted mt-1">
        BANKROLL {fmtUsdPlain(s.bankroll.current_usd, 2)} · STARTED $
        {s.bankroll.starting_usd.toFixed(0)}
        {s.feeds_snapshot_age_s !== null && (
          <span> · feeds {fmtAge(s.feeds_snapshot_age_s)}</span>
        )}
      </div>
    </Panel>
  )
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string
  value: string
  tone?: "good" | "bad" | "warn" | "neutral" | "muted"
}) {
  const toneCls =
    tone === "good"
      ? "text-good"
      : tone === "bad"
        ? "text-bad"
        : tone === "warn"
          ? "text-warn"
          : tone === "muted"
            ? "text-text-muted"
            : "text-text-primary"
  return (
    <div className="flex flex-col">
      <div className="text-[8.5px] font-bold uppercase tracking-widest text-text-muted">
        {label}
      </div>
      <div className={cn("font-mono text-sm font-bold tabular-nums", toneCls)}>
        {value}
      </div>
    </div>
  )
}

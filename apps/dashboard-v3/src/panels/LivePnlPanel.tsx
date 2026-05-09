import { useDashboard } from "../store/dashboardStore"
import { DigitRoll } from "../motion/DigitRoll"
import { Panel } from "./_Panel"
import { fmtUsd, fmtPct } from "../lib/format"
import { cn } from "../lib/cn"

/**
 * Live PnL pace + streak panel — companion to WalletPanel. Header
 * detail layered with secondary stats.
 */
export function LivePnlPanel() {
  const s = useDashboard()
  if (!s) return <Panel title="LIVE PACE · STREAK" />

  const pace = s.pace.usd_per_hour
  const paceSign = pace >= 0 ? "+" : "-"
  const paceTone =
    pace > 0 ? "text-good" : pace < 0 ? "text-bad" : "text-text-secondary"
  const paceValue = `${paceSign}$${Math.abs(pace).toFixed(2)}`

  const streak = s.streak
  const streakTone =
    streak.glyph === "▲"
      ? "text-good"
      : streak.glyph === "▼"
        ? "text-bad"
        : "text-text-muted"

  const today = s.today
  const todayTone =
    today.pnl_usd === null
      ? "text-text-muted"
      : today.pnl_usd > 0
        ? "text-good"
        : today.pnl_usd < 0
          ? "text-bad"
          : "text-text-secondary"

  return (
    <Panel
      title="LIVE PACE · STREAK"
      badge="LIVE"
      badgeTone="good"
      subtitle={`${s.pace.n_settled_60m} settled · last 60m`}
    >
      <div className="text-[9px] uppercase tracking-widest text-text-muted">
        PROFIT PACE / HR
      </div>
      <DigitRoll
        value={paceValue}
        className={cn(
          "font-mono text-3xl font-bold leading-none tabular-nums tracking-[-0.01em]",
          paceTone,
        )}
        duration={0.45}
      />
      <div className="text-[10px] text-text-muted tabular-nums">
        {s.pace.n_settled_60m} settled · last 60m
      </div>

      <div className="flex flex-col gap-1.5 mt-auto pt-2 border-t border-border-subtle">
        <Row
          label="TODAY"
          value={
            today.pnl_usd === null ? "—" : fmtUsd(today.pnl_usd)
          }
          sub={`${today.n_settled} settled`}
          tone={todayTone}
        />
        <Row
          label="STREAK"
          value={`${streak.glyph} ${streak.n}`}
          sub={`best ${streak.best_win}W · worst ${streak.worst_loss}L`}
          tone={streakTone}
        />
        {s.best_tier.label && s.best_tier.pnl_usd !== null && (
          <Row
            label="BEST TIER"
            value={`${s.best_tier.label} ${fmtUsd(s.best_tier.pnl_usd)}`}
            sub=""
            tone={s.best_tier.pnl_usd >= 0 ? "text-good" : "text-bad"}
          />
        )}
        <Row
          label="WIN RATE"
          value={fmtPct(s.agg.win_rate)}
          sub={`${s.agg.n_won}/${s.agg.n_settled}`}
          tone={
            s.agg.win_rate === null
              ? "text-text-muted"
              : s.agg.win_rate >= 0.55
                ? "text-good"
                : s.agg.win_rate < 0.45
                  ? "text-bad"
                  : "text-warn"
          }
        />
      </div>
    </Panel>
  )
}

function Row({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub: string
  tone: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-0.5">
      <span className="text-[9px] font-bold uppercase tracking-widest text-text-muted shrink-0">
        {label}
      </span>
      <span className="text-right tabular-nums">
        <span className={cn("font-mono text-xs font-bold", tone)}>{value}</span>
        {sub && (
          <span className="text-[9.5px] text-text-muted ml-1.5">({sub})</span>
        )}
      </span>
    </div>
  )
}

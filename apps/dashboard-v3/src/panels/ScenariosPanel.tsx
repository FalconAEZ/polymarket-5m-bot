import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { fmtUsd, fmtUsdPlain } from "../lib/format"
import { cn } from "../lib/cn"
import type { ScenarioRow } from "../store/types"

/**
 * Phase 16 — bankroll scenarios projection.
 *
 * Stake is fixed at locked decision #9 ($5/trade for first 100 trades),
 * so realised PnL is the SAME absolute dollar amount across every
 * scenario — the rows differ only in the starting balance. The active
 * row is the $1,000 paper bankroll (locked decision #10); the rest are
 * model-only — DO NOT relitigate decision #10 from this panel.
 *
 * `is_bankrupt` flags rows where the realised PnL pushes the small
 * starting bankroll below zero. We deliberately show the negative
 * end_bankroll_usd as-is (no clamp) so the operator sees the threshold.
 */
export function ScenariosPanel() {
  const s = useDashboard()
  if (!s) return <Panel title="BANKROLL SCENARIOS" />
  const rows = s.scenarios
  if (!rows || rows.length === 0 || rows[0].n_settled === 0) {
    return (
      <Panel title="BANKROLL SCENARIOS">
        <div className="text-[10px] text-text-muted py-2">
          no settled trades yet to project.
        </div>
      </Panel>
    )
  }
  const head = rows[0]
  const liveStart = s.bankroll.starting_usd
  const subtitle = `stake $${head.fixed_stake_usd.toFixed(2)} fixed · ${head.n_settled} settled · phase 17 unlocks fractional`
  return (
    <Panel title="BANKROLL SCENARIOS" subtitle={subtitle}>
      <div className="flex flex-col gap-1 mt-1">
        <div className="grid grid-cols-[64px_1fr_88px_64px] gap-2 text-[9px] uppercase tracking-[0.06em] text-text-muted px-1">
          <span>start</span>
          <span></span>
          <span className="text-right">end</span>
          <span className="text-right">Δ%</span>
        </div>
        {rows.map((r) => (
          <ScenarioRowView
            key={r.start_bankroll_usd}
            r={r}
            active={r.start_bankroll_usd === liveStart}
          />
        ))}
      </div>
    </Panel>
  )
}

function ScenarioRowView({ r, active }: { r: ScenarioRow; active: boolean }) {
  const deltaPct =
    r.start_bankroll_usd > 0
      ? ((r.end_bankroll_usd - r.start_bankroll_usd) / r.start_bankroll_usd) * 100
      : 0
  const tone =
    r.is_bankrupt || r.realized_pnl_usd < 0
      ? "text-bad"
      : r.realized_pnl_usd > 0
        ? "text-good"
        : "text-text-secondary"
  // Bar lengths normalize to the LARGEST starting bankroll so $500 doesn't
  // hog 100% just because it's the only thing on screen.
  const barPct = Math.max(0, Math.min(100, r.end_bankroll_usd / 100))
  return (
    <div
      className={cn(
        "grid grid-cols-[64px_1fr_88px_64px] gap-2 items-baseline px-1 py-0.5 rounded-sm",
        active
          ? "bg-[rgba(255,255,255,0.04)] border border-border-subtle"
          : "border border-transparent",
      )}
    >
      <span className="font-bold tabular-nums text-text-primary text-[11px]">
        {fmtUsdPlain(r.start_bankroll_usd, 0)}
      </span>
      <div className="h-2 rounded-sm bg-bg-inset overflow-hidden relative">
        <div
          className={cn(
            "h-full",
            r.is_bankrupt
              ? "bg-[rgba(255,92,92,0.30)]"
              : r.realized_pnl_usd >= 0
                ? "bg-[rgba(110,255,161,0.30)]"
                : "bg-[rgba(255,184,74,0.30)]",
          )}
          style={{ width: `${barPct}%` }}
        />
        {active && (
          <div className="absolute inset-y-0 right-1 flex items-center text-[9px] text-text-muted uppercase tracking-[0.06em]">
            live
          </div>
        )}
      </div>
      <span className={cn("font-mono font-bold tabular-nums text-right text-[11px]", tone)}>
        {fmtUsd(r.end_bankroll_usd)}
      </span>
      <span className={cn("font-mono tabular-nums text-right text-[10px]", tone)}>
        {deltaPct >= 0 ? "+" : ""}
        {deltaPct.toFixed(1)}%
      </span>
    </div>
  )
}

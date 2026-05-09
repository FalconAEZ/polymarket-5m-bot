import { useDashboard, useWsStatus } from "./store/dashboardStore"
import { TopStrip } from "./panels/TopStrip"
import { LiveTape } from "./panels/LiveTape"
import { WalletPanel } from "./panels/WalletPanel"
import { ChartPanel } from "./panels/ChartPanel"
import { DecisionsTape } from "./panels/DecisionsTape"
import { CumulativePnlPanel } from "./panels/CumulativePnlPanel"
import { LivePnlPanel } from "./panels/LivePnlPanel"
import { PipelineStrip } from "./panels/PipelineStrip"
import { SpotBookPanel } from "./panels/SpotBookPanel"
import { CTFBookPanel } from "./panels/CTFBookPanel"
import { RTTPanel } from "./panels/RTTPanel"
import { TripWiresPanel } from "./panels/TripWiresPanel"
import { TierBreakdownPanel } from "./panels/TierBreakdownPanel"

/**
 * v3 layout shell. 12-col grid mapped to a CSS grid with named regions.
 * Per design/dashboard-v3.md §6.
 */
export default function App() {
  const s = useDashboard()
  const ws = useWsStatus()

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-bg-page text-text-primary">
      <TopStrip />
      <LiveTape />

      {/* Incident strip (only when present) */}
      {s && s.incidents.length > 0 && (
        <div className="border-b border-[rgba(255,92,92,0.40)] bg-[linear-gradient(180deg,rgba(255,92,92,0.10),transparent_80%)] px-4 py-1.5 flex items-center gap-3 text-xs">
          <span className="text-bad font-bold">⚠ {s.incidents.length}</span>
          <span className="text-text-secondary truncate">
            {s.incidents.join(" · ")}
          </span>
        </div>
      )}

      {/* MAIN GRID — 4 rows fitting in viewport */}
      <div className="flex-1 grid grid-rows-[auto_auto_1fr_auto] gap-2 p-2 min-h-0 overflow-y-auto">
        {/* ROW A — wallet | chart | spot book | live pnl */}
        <div className="grid grid-cols-12 gap-2 min-h-[260px]">
          <div className="col-span-3 min-h-0"><WalletPanel /></div>
          <div className="col-span-5 min-h-0"><ChartPanel /></div>
          <div className="col-span-2 min-h-0"><SpotBookPanel /></div>
          <div className="col-span-2 min-h-0"><LivePnlPanel /></div>
        </div>

        {/* ROW B — pipeline */}
        <div><PipelineStrip /></div>

        {/* ROW C — decisions tape | cumulative PnL chart | CTF book.
            min-h-0 on each cell is required so the inner Panel + table
            can shrink under flex/grid; without it the table's intrinsic
            height pushes the row past min-h-[280px] and bleeds past the
            panel boundary on Safari. */}
        <div className="grid grid-cols-12 gap-2 min-h-[280px]">
          <div className="col-span-5 min-h-0"><DecisionsTape /></div>
          <div className="col-span-4 min-h-0"><CumulativePnlPanel /></div>
          <div className="col-span-3 min-h-0"><CTFBookPanel /></div>
        </div>

        {/* ROW D — RTT | trip-wires | tier breakdown */}
        <div className="grid grid-cols-12 gap-2 min-h-[160px]">
          <div className="col-span-4 min-h-0"><RTTPanel /></div>
          <div className="col-span-4 min-h-0"><TripWiresPanel /></div>
          <div className="col-span-4 min-h-0"><TierBreakdownPanel /></div>
        </div>
      </div>

      <footer className="border-t border-border-subtle px-4 py-1 text-[9px] uppercase tracking-widest text-text-muted flex items-center justify-between">
        <span>
          ws:{" "}
          <span
            className={
              ws === "open"
                ? "text-good"
                : ws === "reconnecting"
                  ? "text-warn"
                  : "text-bad"
            }
          >
            {ws}
          </span>
        </span>
        {s && (
          <span className="text-text-muted">
            {s.n_decisions_total} fired · {s.agg.n_settled} settled · schema v
            {s.schema_version}
          </span>
        )}
      </footer>
    </div>
  )
}

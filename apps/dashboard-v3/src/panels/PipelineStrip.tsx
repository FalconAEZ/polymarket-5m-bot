import { motion } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { fmtMs, fmtAge } from "../lib/format"
import { cn } from "../lib/cn"
import type { StageStatus } from "../store/types"

/**
 * 6-stage execution pipeline strip. Numbered Bloomberg-style with
 * per-stage status color (top border + number). Includes the
 * CYCLE/BUDGET/ELAPSED meta chip on the right.
 *
 * Status derived from real bot state:
 *   CAPTURE  — feeds_health.healthy (any unhealthy → warn)
 *   STRATEGY — paper process alive
 *   SIM-FILL — has fills + paper alive
 *   SETTLE   — has unsettled most-recent decision (pending)
 *   RESOLVE  — at least one resolved decision (Gamma OK)
 *   PERSIST  — JSONL writes
 */
export function PipelineStrip() {
  const s = useDashboard()
  if (!s) return null

  const captureHealthy = s.feeds.length > 0 && s.feeds.every((f) => f.healthy)
  const captureStatus: StageStatus = !s.processes.capture.alive
    ? "dead"
    : captureHealthy
      ? "alive"
      : "warn"
  const strategyStatus: StageStatus = s.processes.paper.alive
    ? s.agg.n_fired > 0
      ? "alive"
      : "pending"
    : "dead"
  const simFillStatus: StageStatus =
    s.agg.n_fired > 0 && s.processes.paper.alive
      ? "alive"
      : s.agg.n_fired > 0
        ? "warn"
        : "pending"
  const hasUnsettled = s.agg.n_fired > s.agg.n_settled
  const settleStatus: StageStatus = hasUnsettled ? "pending" : "alive"
  const resolveStatus: StageStatus = s.agg.n_settled > 0 ? "alive" : "pending"
  const persistStatus: StageStatus = s.agg.n_fired > 0 ? "alive" : "pending"

  const stages: Array<{
    name: string
    detail: string
    latency: string
    status: StageStatus
  }> = [
    {
      name: "Capture",
      detail: `${s.feeds.filter((f) => f.healthy).length}/${s.feeds.length} feeds`,
      latency: fmtMs(s.pipeline.capture_ms),
      status: captureStatus,
    },
    {
      name: "Strategy",
      detail: s.mode.raw ?? "—",
      latency: fmtMs(s.pipeline.strategy_ms),
      status: strategyStatus,
    },
    {
      name: "Sim-Fill",
      detail: `${s.agg.n_filled}/${s.agg.n_fired} fills`,
      latency: fmtMs(s.pipeline.sim_fill_ms),
      status: simFillStatus,
    },
    {
      name: "Settle",
      detail:
        s.pipeline.settle_wait_s !== null
          ? s.pipeline.settle_wait_s <= 0
            ? "DUE"
            : `T-${fmtAge(s.pipeline.settle_wait_s)}`
          : "—",
      latency: hasUnsettled ? "pending" : "—",
      status: settleStatus,
    },
    {
      name: "Resolve",
      detail: s.agg.n_settled > 0 ? "Gamma OK" : "—",
      latency: fmtMs(s.pipeline.resolve_ms),
      status: resolveStatus,
    },
    {
      name: "Persist",
      detail: "JSONL",
      latency: fmtMs(s.pipeline.persist_ms),
      status: persistStatus,
    },
  ]

  return (
    <div className="flex items-stretch gap-2">
      <div className="flex-1 grid grid-cols-6 gap-2">
        {stages.map((stage, i) => (
          <Stage key={stage.name} num={i + 1} {...stage} />
        ))}
      </div>
      <CycleMeta n_fired={s.agg.n_fired} settle_wait_s={s.pipeline.settle_wait_s} />
    </div>
  )
}

function Stage({
  num,
  name,
  detail,
  latency,
  status,
}: {
  num: number
  name: string
  detail: string
  latency: string
  status: StageStatus
}) {
  const numColor =
    status === "alive"
      ? "text-good"
      : status === "pending"
        ? "text-warn"
        : status === "warn"
          ? "text-warn"
          : "text-bad"
  const borderColor =
    status === "alive"
      ? "border-[rgba(110,255,161,0.30)]"
      : status === "pending"
        ? "border-[rgba(255,184,74,0.40)] bg-[linear-gradient(180deg,rgba(255,184,74,0.06),transparent_60%)]"
        : status === "warn"
          ? "border-[rgba(255,184,74,0.30)]"
          : "border-[rgba(255,92,92,0.30)]"
  return (
    <motion.div
      whileHover={{ y: -1 }}
      transition={{ duration: 0.15 }}
      className={cn(
        "grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 rounded-sm border bg-bg-panel p-2",
        borderColor,
      )}
    >
      <div
        className={cn("row-span-3 font-mono text-2xl font-bold leading-none tabular-nums", numColor)}
      >
        {num.toString().padStart(2, "0")}
      </div>
      <div className="text-[10.5px] font-bold uppercase tracking-[0.06em] text-text-primary">
        {name}
      </div>
      <div className="text-[9.5px] uppercase tracking-[0.04em] text-text-muted tabular-nums">
        {detail}
      </div>
      <div
        className={cn(
          "col-span-2 font-mono text-base font-bold tabular-nums leading-tight",
          status === "pending" ? "text-warn" : "text-text-primary",
        )}
      >
        {latency}
      </div>
    </motion.div>
  )
}

function CycleMeta({
  n_fired,
  settle_wait_s,
}: {
  n_fired: number
  settle_wait_s: number | null
}) {
  return (
    <div className="flex items-center gap-4 rounded-sm border border-border-subtle bg-bg-panel px-3 py-2">
      <div className="rounded-sm bg-[rgba(255,184,74,0.08)] px-2 py-1 text-[10px] font-bold tracking-[0.10em] text-warn">
        CYCLE #{n_fired}
      </div>
      <div className="flex flex-col">
        <span className="text-[8px] font-bold uppercase tracking-widest text-text-muted">
          BUDGET
        </span>
        <span className="font-mono text-sm font-bold text-text-primary">5m</span>
      </div>
      <div className="flex flex-col">
        <span className="text-[8px] font-bold uppercase tracking-widest text-text-muted">
          ELAPSED
        </span>
        <span
          className={cn(
            "font-mono text-sm font-bold tabular-nums",
            settle_wait_s !== null ? "text-warn" : "text-text-primary",
          )}
        >
          {settle_wait_s !== null ? fmtAge(300 - settle_wait_s) : "—"}
        </span>
      </div>
    </div>
  )
}

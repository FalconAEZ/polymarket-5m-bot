import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useRef, useState } from "react"
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
  // Per-stage "ping" counter — bumped each time the underlying signal
  // increments. The Stage component watches it via key= to re-trigger
  // its glow animation. Per the 2026-05-10 operator feedback ("01-06
  // are static and don't do anything; make them live"). Without this,
  // n_fired/n_filled/n_settled tick silently and the strip just shows
  // numbers updating without any sense of "an event just happened".
  const captureMsgs = s ? s.feeds.reduce((acc, f) => acc + f.msgs_seen, 0) : 0
  const pings = useEventPings({
    capture: captureMsgs,
    strategy: s?.agg.n_fired ?? 0,
    simFill: s?.agg.n_filled ?? 0,
    settle: s?.agg.n_settled ?? 0,
    resolve: s?.agg.n_settled ?? 0,
    persist: (s?.agg.n_fired ?? 0) + (s?.agg.n_settled ?? 0),
  })

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
    pingKey: number
    pingTone: "good" | "warn" | "bad"
  }> = [
    {
      name: "Capture",
      detail: `${s.feeds.filter((f) => f.healthy).length}/${s.feeds.length} feeds`,
      latency: fmtMs(s.pipeline.capture_ms),
      status: captureStatus,
      pingKey: pings.capture,
      pingTone: "good",
    },
    {
      name: "Strategy",
      detail: s.mode.raw ?? "—",
      latency: fmtMs(s.pipeline.strategy_ms),
      status: strategyStatus,
      pingKey: pings.strategy,
      pingTone: "warn",
    },
    {
      name: "Sim-Fill",
      detail: `${s.agg.n_filled}/${s.agg.n_fired} fills`,
      latency: fmtMs(s.pipeline.sim_fill_ms),
      status: simFillStatus,
      pingKey: pings.simFill,
      pingTone: "warn",
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
      pingKey: pings.settle,
      pingTone: "warn",
    },
    {
      name: "Resolve",
      detail: s.agg.n_settled > 0 ? "Gamma OK" : "—",
      latency: fmtMs(s.pipeline.resolve_ms),
      status: resolveStatus,
      pingKey: pings.resolve,
      pingTone: "good",
    },
    {
      name: "Persist",
      detail: "JSONL",
      latency: fmtMs(s.pipeline.persist_ms),
      status: persistStatus,
      pingKey: pings.persist,
      pingTone: "good",
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

/** Track per-stage "an event just fired here" pings. Returns a counter
 * per stage that bumps every time the underlying input value increases
 * across renders (compared via useRef-stored prev snapshot). The Stage
 * component watches the counter and replays its glow when it changes.
 * Cold start (first render) does NOT ping — initial values are stored
 * silently so a fresh dashboard load doesn't strobe every stage. */
function useEventPings(inputs: {
  capture: number
  strategy: number
  simFill: number
  settle: number
  resolve: number
  persist: number
}): typeof inputs {
  const prev = useRef<typeof inputs | null>(null)
  const [pings, setPings] = useState<typeof inputs>({
    capture: 0,
    strategy: 0,
    simFill: 0,
    settle: 0,
    resolve: 0,
    persist: 0,
  })
  useEffect(() => {
    const before = prev.current
    if (before === null) {
      prev.current = { ...inputs }
      return
    }
    const next = { ...pings }
    let changed = false
    ;(Object.keys(inputs) as Array<keyof typeof inputs>).forEach((k) => {
      if (inputs[k] > before[k]) {
        next[k] = pings[k] + 1
        changed = true
      }
    })
    prev.current = { ...inputs }
    if (changed) setPings(next)
    // We intentionally only depend on the input values; the pings
    // setter is stable and including it triggers redundant re-runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputs.capture, inputs.strategy, inputs.simFill, inputs.settle, inputs.resolve, inputs.persist])
  return pings
}

function Stage({
  num,
  name,
  detail,
  latency,
  status,
  pingKey,
  pingTone,
}: {
  num: number
  name: string
  detail: string
  latency: string
  status: StageStatus
  pingKey: number
  pingTone: "good" | "warn" | "bad"
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
  // Ping color: which stage just had an event fire? Capture/Resolve
  // pings green (success); Strategy/Sim-Fill/Settle/Persist ping amber
  // (in-flight or write event).
  const glowColor =
    pingTone === "good"
      ? "rgba(110,255,161,0.75)"
      : pingTone === "warn"
        ? "rgba(255,184,74,0.75)"
        : "rgba(255,92,92,0.75)"
  return (
    <motion.div
      whileHover={{ y: -1 }}
      transition={{ duration: 0.15 }}
      className={cn(
        "relative grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 overflow-hidden rounded-sm border bg-bg-panel p-2",
        borderColor,
      )}
    >
      {/*
        Event ping: a one-shot ring that flares whenever pingKey
        increments. Mounts/unmounts via AnimatePresence + a key tied
        to pingKey. Suppressed when pingKey===0 (cold start) so a
        fresh dashboard load doesn't strobe every stage.
      */}
      <AnimatePresence>
        {pingKey > 0 && (
          <motion.div
            key={pingKey}
            className="pointer-events-none absolute inset-0 rounded-sm"
            initial={{ opacity: 0, boxShadow: `0 0 0 0 ${glowColor}` }}
            animate={{
              opacity: [0, 1, 0],
              boxShadow: [
                `0 0 0 0 ${glowColor}`,
                `0 0 18px 3px ${glowColor}`,
                `0 0 0 0 ${glowColor}`,
              ],
            }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.0, ease: [0.4, 0, 0.6, 1] }}
          />
        )}
      </AnimatePresence>
      <div
        className={cn(
          "row-span-3 font-mono text-2xl font-bold leading-none tabular-nums relative z-10",
          numColor,
        )}
      >
        {num.toString().padStart(2, "0")}
      </div>
      <div className="text-[10.5px] font-bold uppercase tracking-[0.06em] text-text-primary relative z-10">
        {name}
      </div>
      <div className="text-[9.5px] uppercase tracking-[0.04em] text-text-muted tabular-nums relative z-10">
        {detail}
      </div>
      <div
        className={cn(
          "col-span-2 font-mono text-base font-bold tabular-nums leading-tight relative z-10",
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

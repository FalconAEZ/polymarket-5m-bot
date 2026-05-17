import { motion } from "framer-motion"
import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { fmtAge } from "../lib/format"
import { cn } from "../lib/cn"

const N_BARS = 6

/**
 * Provider RTT panel — server-side measurements from VPS, per
 * design/dashboard-v3.md §3.4. Reads from state.provider_rtt.
 */
export function RTTPanel() {
  const s = useDashboard()
  if (!s) return <Panel title="PROVIDER RTT · VPS" />

  const last_age = s.provider_rtt.last_sample_age_s
  const liveTone =
    last_age === null
      ? "muted"
      : last_age < 30
        ? "good"
        : last_age < 120
          ? "warn"
          : "bad"
  const liveLabel =
    last_age === null
      ? "no collector data yet"
      : last_age < 30
        ? `live · ${fmtAge(last_age)} ago`
        : last_age < 120
          ? `slow · ${fmtAge(last_age)} ago`
          : `stale · ${fmtAge(last_age)} ago`

  return (
    <Panel title="PROVIDER RTT · VPS" subtitle="MEASURED FROM VPS · 10s CADENCE">
      <div className={cn("text-[9px] font-bold uppercase tracking-widest mt-1", `text-${liveTone === "muted" ? "text-muted" : liveTone}`)}>
        {liveLabel}
      </div>
      <div className="flex flex-col gap-0.5 mt-2">
        {s.provider_rtt.providers.map((p) => (
          <Row key={p.name} name={p.name} samples={p.samples} last={p.last_ms} />
        ))}
        {s.provider_rtt.providers.length === 0 && (
          <div className="text-[10px] text-text-muted py-2">
            collector not running. start with{" "}
            <code className="bg-bg-inset px-1 py-0.5 rounded-sm text-[9.5px]">
              systemctl start rtt-collector
            </code>
          </div>
        )}
      </div>
    </Panel>
  )
}

function classify(ms: number | null): "good" | "warn" | "bad" {
  // Cross-region HTTP RTT thresholds. AWS Lightsail eu-west-1 → Binance
  // edge can sit at 250-350ms in the steady state without indicating a
  // problem; the previous 200/600 buckets painted normal latency amber
  // for no reason. New buckets give "fine" 0-300, "watch" 300-800,
  // "alarm" 800+ which matches what an operator actually wants to see.
  if (ms === null) return "bad"
  if (ms < 300) return "good"
  if (ms < 800) return "warn"
  return "bad"
}

function Row({
  name,
  samples,
  last,
}: {
  name: string
  samples: (number | null)[]
  last: number | null
}) {
  const padded = [...Array(Math.max(0, N_BARS - samples.length)).fill(null), ...samples].slice(
    -N_BARS,
  ) as (number | null)[]
  const visible = padded.filter((v): v is number => v !== null)
  const max = Math.max(...visible, 100)
  const lastClass =
    last === null ? "text-bad" : classify(last) === "good" ? "text-good" : classify(last) === "warn" ? "text-warn" : "text-bad"
  return (
    <div className="flex items-center gap-2 py-1 border-b border-border-subtle last:border-b-0">
      <div className="text-[10px] font-bold uppercase tracking-[0.06em] text-text-secondary min-w-[64px]">
        {name}
      </div>
      <div className="flex-1 flex items-end gap-px h-4">
        {padded.map((ms, i) => {
          const cls = classify(ms)
          const barColor =
            ms === null
              ? "bg-border-subtle"
              : cls === "good"
                ? "bg-good"
                : cls === "warn"
                  ? "bg-warn"
                  : "bg-bad"
          const h = ms === null ? 2 : Math.max(2, Math.min(16, (ms / max) * 16))
          return (
            <motion.div
              key={i}
              className={cn("flex-1 rounded-sm", barColor)}
              initial={{ height: 2 }}
              animate={{ height: h }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            />
          )
        })}
      </div>
      <div className={cn("text-[11px] font-bold tabular-nums min-w-[52px] text-right", lastClass)}>
        {last === null ? "err" : `${Math.round(last)}ms`}
      </div>
    </div>
  )
}

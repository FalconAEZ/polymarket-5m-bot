import { useEffect, useMemo, useRef } from "react"
import {
  createChart,
  BaselineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { fmtUsd } from "../lib/format"
import { cn } from "../lib/cn"

/**
 * Cumulative PnL chart — running sum of pnl_usd over every settled
 * decision since the bot started. lightweight-charts BaselineSeries
 * tints the area green above $0 and red below, so a glance tells you
 * whether the bot is in profit territory and how decisively. Same
 * chart instance survives across snapshot pushes; only the series
 * data is replaced when the snapshot changes.
 */
export function CumulativePnlPanel() {
  const s = useDashboard()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null)

  const series = s?.cumulative_pnl_series ?? []
  const last = series.length > 0 ? series[series.length - 1].pnl : 0
  const lastTone =
    last > 0 ? "text-good" : last < 0 ? "text-bad" : "text-text-secondary"

  // Stats summary: peak / trough / current — simple but informative
  // beneath the chart hero number.
  const { peak, trough } = useMemo(() => {
    if (series.length === 0) return { peak: 0, trough: 0 }
    let p = series[0].pnl
    let t = series[0].pnl
    for (const point of series) {
      if (point.pnl > p) p = point.pnl
      if (point.pnl < t) t = point.pnl
    }
    return { peak: p, trough: t }
  }, [series])

  // Mount the chart once. Same pattern as ChartPanel — autoSize off,
  // ResizeObserver drives applyOptions with floored ints so iOS Safari
  // doesn't bleed the canvas past the panel boundary.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const initialRect = container.getBoundingClientRect()
    const chart = createChart(container, {
      width: Math.max(1, Math.floor(initialRect.width)),
      height: Math.max(1, Math.floor(initialRect.height)),
      layout: {
        background: { color: "transparent" },
        textColor: "#a08f6a",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 9,
      },
      rightPriceScale: {
        borderColor: "#221e15",
        textColor: "#a08f6a",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: "#221e15",
        timeVisible: true,
        secondsVisible: false,
      },
      grid: {
        horzLines: { color: "rgba(34, 30, 21, 0.5)" },
        vertLines: { color: "rgba(34, 30, 21, 0.3)" },
      },
      crosshair: {
        vertLine: { color: "#6b4d18", width: 1, style: 2 },
        horzLine: { color: "#6b4d18", width: 1, style: 2 },
      },
      autoSize: false,
      handleScroll: false,
      handleScale: false,
    })
    const baselineSeries = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 0 },
      topLineColor: "rgba(110, 255, 161, 0.95)",
      topFillColor1: "rgba(110, 255, 161, 0.32)",
      topFillColor2: "rgba(110, 255, 161, 0.04)",
      bottomLineColor: "rgba(255, 92, 92, 0.95)",
      bottomFillColor1: "rgba(255, 92, 92, 0.04)",
      bottomFillColor2: "rgba(255, 92, 92, 0.32)",
      lineWidth: 2,
      priceFormat: {
        type: "custom",
        formatter: (v: number) =>
          (v >= 0 ? "+$" : "-$") + Math.abs(v).toFixed(2),
        minMove: 0.01,
      },
    })
    chartRef.current = chart
    seriesRef.current = baselineSeries

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      chart.applyOptions({
        width: Math.max(1, Math.floor(width)),
        height: Math.max(1, Math.floor(height)),
      })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // Push series data on snapshot change. lightweight-charts requires
  // ascending unique timestamps; the backend already sorts and the
  // snapshot caps at 500 points so this is cheap.
  useEffect(() => {
    if (!seriesRef.current) return
    if (series.length === 0) {
      seriesRef.current.setData([])
      return
    }
    // Two settled decisions can land in the same UTC second when the
    // bot fires fast in aggressive mode; lightweight-charts rejects
    // duplicate timestamps. Bump conflicting points by +1s so the
    // chart sees a strictly-monotonic series.
    let lastTs = -Infinity
    const data = series.map((p) => {
      let t = p.ts
      if (t <= lastTs) t = lastTs + 1
      lastTs = t
      return { time: t as UTCTimestamp, value: p.pnl }
    })
    seriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [series])

  const subtitle =
    series.length === 0
      ? "no settled decisions yet"
      : `${series.length} settled · peak ${fmtUsd(peak, 2)} · trough ${fmtUsd(trough, 2)}`

  return (
    <Panel
      title="CUMULATIVE PNL · CURVE"
      subtitle={subtitle}
      badge={fmtUsd(last, 2)}
      badgeTone={last > 0 ? "good" : last < 0 ? "bad" : "muted"}
    >
      <div className="flex items-baseline gap-2">
        <span className="text-[9px] uppercase tracking-widest text-text-muted">
          NOW
        </span>
        <span className={cn("font-mono text-base font-bold tabular-nums", lastTone)}>
          {fmtUsd(last, 2)}
        </span>
      </div>
      <div
        ref={containerRef}
        className="relative w-full flex-1 min-h-0 overflow-hidden"
      />
    </Panel>
  )
}

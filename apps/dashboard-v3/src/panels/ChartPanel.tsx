import { useEffect, useRef } from "react"
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"

/**
 * BTC 5M chart — lightweight-charts v5 (TradingView's free OSS).
 * The chart instance lives across renders via useRef; we update only
 * the data when the snapshot changes. lightweight-charts handles its
 * own animation between bar updates so the price moves smoothly even
 * with our 1-2s state push cadence.
 */
export function ChartPanel() {
  const s = useDashboard()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null)

  // Setup chart once on mount.
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#a08f6a",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
      },
      rightPriceScale: {
        borderColor: "#221e15",
        textColor: "#a08f6a",
      },
      timeScale: {
        borderColor: "#221e15",
        timeVisible: true,
        secondsVisible: false,
      },
      grid: {
        horzLines: { color: "rgba(34, 30, 21, 0.6)" },
        vertLines: { color: "rgba(34, 30, 21, 0.4)" },
      },
      crosshair: {
        vertLine: { color: "#6b4d18", width: 1, style: 2 },
        horzLine: { color: "#6b4d18", width: 1, style: 2 },
      },
      autoSize: true,
    })
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#6effa1",
      downColor: "#ff5c5c",
      borderUpColor: "#6effa1",
      borderDownColor: "#ff5c5c",
      wickUpColor: "#6effa1",
      wickDownColor: "#ff5c5c",
    })
    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    return () => {
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
    }
  }, [])

  // Push candle data on snapshot change.
  useEffect(() => {
    if (!s || !candleSeriesRef.current) return
    if (s.chart.candles.length === 0) return
    const data = s.chart.candles.map((c) => ({
      time: Math.floor(c.ts) as UTCTimestamp,
      open: c.o,
      high: c.h,
      low: c.l,
      close: c.c,
    }))
    candleSeriesRef.current.setData(data)
    // v3.1 will add decision-fire arrow markers via lightweight-charts
    // v5's createSeriesMarkers plugin API (markers were moved out of
    // the series API in v5). For now the chart is candles only.
  }, [s])

  return (
    <Panel title="BTC · 5M · BINANCE" subtitle="SPOT REFERENCE">
      <div ref={containerRef} className="flex-1 min-h-[220px]" />
    </Panel>
  )
}

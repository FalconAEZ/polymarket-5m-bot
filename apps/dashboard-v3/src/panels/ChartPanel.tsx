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
      // autoSize:true measures the container *after* layout settles and
      // can over-extend the canvas past the overflow boundary on iOS
      // Safari (operator screenshot 2). Driving size manually via the
      // observer below keeps the canvas strictly inside the container's
      // measured box on every browser.
      autoSize: false,
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

    // Resize the chart to match the container box exactly. Floor to
    // integer pixels so the canvas never gets a sub-pixel size that
    // Safari rounds up.
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
      {/*
        Container is `relative + overflow-hidden` so the lightweight-charts
        canvas (which absolutely-positions its layers) is always clipped
        to the panel bounds. min-h/max-h together prevent autoSize from
        ballooning the canvas vertically on iOS Safari, which was bleeding
        into the row below per operator's screenshot 2.
      */}
      <div
        ref={containerRef}
        className="relative w-full overflow-hidden min-h-[220px] max-h-[260px] flex-shrink"
        style={{ flexBasis: "240px" }}
      />
    </Panel>
  )
}

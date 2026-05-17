import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { AnimatedBook } from "../book/AnimatedBook"
import { fmtPrice, fmtSpotSize } from "../lib/format"

/** Binance L2 spot orderbook — depth20@100ms via FastAPI backend. */
export function SpotBookPanel() {
  const s = useDashboard()
  return (
    <Panel
      title="BTC SPOT · BINANCE"
      subtitle="L2 · depth20@100ms"
      badge={s?.spot_book.asks.length ? "LIVE" : "—"}
      badgeTone={s?.spot_book.asks.length ? "good" : "muted"}
    >
      {s && (
        <AnimatedBook
          asks={s.spot_book.asks}
          bids={s.spot_book.bids}
          mid={s.spot_book.mid}
          fmtPrice={(n) => fmtPrice(n, 2)}
          fmtSize={fmtSpotSize}
          maxLevels={6}
        />
      )}
    </Panel>
  )
}

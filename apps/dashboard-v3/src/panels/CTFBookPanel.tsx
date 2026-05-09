import { useDashboard } from "../store/dashboardStore"
import { Panel } from "./_Panel"
import { AnimatedBook } from "../book/AnimatedBook"
import { fmtCtfPrice, fmtCtfSize } from "../lib/format"

/** Polymarket CTF orderbook — current 5m window's UP or DOWN side. */
export function CTFBookPanel() {
  const s = useDashboard()
  const sideLabel = s?.ctf_book.side ? `· ${s.ctf_book.side}` : ""
  const subtitle = s?.ctf_book.slug
    ? `Polymarket CLOB · ${s.ctf_book.slug.split("-").slice(-1)}`
    : "Polymarket CLOB · resolving…"
  const live = !!s?.ctf_book.asks.length
  return (
    <Panel
      title={`OUR MARKET ${sideLabel}`}
      subtitle={subtitle}
      badge={live ? "LIVE" : "WAIT"}
      badgeTone={live ? "good" : "muted"}
    >
      {s && (
        <AnimatedBook
          asks={s.ctf_book.asks}
          bids={s.ctf_book.bids}
          mid={s.ctf_book.mid}
          fmtPrice={fmtCtfPrice}
          fmtSize={fmtCtfSize}
          maxLevels={6}
        />
      )}
    </Panel>
  )
}

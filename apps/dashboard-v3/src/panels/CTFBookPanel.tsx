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
  // Three states surfaced to the operator (Phase 11.A.2 Item 2.3 — the
  // 2026-05-09 22:35 UTC "DOWN book empty" report turned out to be a
  // genuine low-liquidity snapshot, not a fetch bug; before this fix
  // the panel showed "WAIT" indistinguishably from "still resolving"):
  //   - LIVE  → fetched the book and there is depth on at least one side
  //   - EMPTY → fetched the book successfully (we have a slug) but
  //             Polymarket returned zero asks AND zero bids for this
  //             side; no parser/network issue, just no liquidity
  //   - WAIT  → no slug yet, still resolving the token IDs upstream
  const hasSlug = !!s?.ctf_book.slug
  const hasDepth = !!s?.ctf_book.asks.length || !!s?.ctf_book.bids.length
  const live = hasSlug && hasDepth
  const emptyMarket = hasSlug && !hasDepth
  const badge = live ? "LIVE" : emptyMarket ? "EMPTY" : "WAIT"
  const badgeTone = live ? "good" : "muted"
  return (
    <Panel title={`OUR MARKET ${sideLabel}`} subtitle={subtitle} badge={badge} badgeTone={badgeTone}>
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

import { motion, AnimatePresence } from "framer-motion"
import type { BookLevel } from "../store/types"
import { cn } from "../lib/cn"

/**
 * Animated orderbook — used for both Binance spot and Polymarket CTF.
 * Framer Motion's `layout` prop animates row reorder when prices shift.
 * Columns: depth bar (proportional), price, size.
 *
 * Spot uses dollar-style price ($77,501.34); CTF uses 4-decimal
 * (0.5720). The fmtPrice/fmtSize callbacks let the parent control.
 */
export function AnimatedBook({
  asks,
  bids,
  mid,
  fmtPrice,
  fmtSize,
  rowHeight = 18,
  maxLevels = 8,
}: {
  asks: BookLevel[]
  bids: BookLevel[]
  mid: number | null
  fmtPrice: (n: number) => string
  fmtSize: (n: number) => string
  rowHeight?: number
  maxLevels?: number
}) {
  const visibleAsks = [...asks].slice(0, maxLevels)
  const visibleBids = [...bids].slice(0, maxLevels)
  const maxAskSize = Math.max(...visibleAsks.map((r) => r.s), 1)
  const maxBidSize = Math.max(...visibleBids.map((r) => r.s), 1)

  return (
    <div className="flex flex-col font-mono tabular-nums">
      {/* asks: highest first descending toward mid */}
      <div className="flex flex-col-reverse">
        <AnimatePresence initial={false}>
          {visibleAsks.map((row) => (
            <BookRow
              key={`a-${row.p}`}
              row={row}
              max={maxAskSize}
              side="ask"
              fmtPrice={fmtPrice}
              fmtSize={fmtSize}
              rowHeight={rowHeight}
            />
          ))}
        </AnimatePresence>
      </div>

      {mid !== null && (
        <div className="flex justify-between items-baseline border-y border-dashed border-border-strong py-1 my-0.5">
          <span className="text-[8px] font-bold uppercase tracking-widest text-text-muted">
            MID
          </span>
          <motion.span
            key={mid.toFixed(2)}
            initial={{ opacity: 0.6 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2 }}
            className="text-sm font-bold text-text-primary"
          >
            {fmtPrice(mid)}
          </motion.span>
        </div>
      )}

      {/* bids: highest first descending */}
      <div className="flex flex-col">
        <AnimatePresence initial={false}>
          {visibleBids.map((row) => (
            <BookRow
              key={`b-${row.p}`}
              row={row}
              max={maxBidSize}
              side="bid"
              fmtPrice={fmtPrice}
              fmtSize={fmtSize}
              rowHeight={rowHeight}
            />
          ))}
        </AnimatePresence>
      </div>
    </div>
  )
}

function BookRow({
  row,
  max,
  side,
  fmtPrice,
  fmtSize,
  rowHeight,
}: {
  row: BookLevel
  max: number
  side: "ask" | "bid"
  fmtPrice: (n: number) => string
  fmtSize: (n: number) => string
  rowHeight: number
}) {
  const widthPct = max > 0 ? (row.s / max) * 100 : 0
  const barColor =
    side === "ask" ? "bg-[rgba(255,92,92,0.18)]" : "bg-[rgba(110,255,161,0.16)]"
  const priceColor = side === "ask" ? "text-bad" : "text-good"
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ layout: { duration: 0.24, ease: "easeOut" } }}
      style={{ height: rowHeight }}
      className="relative grid grid-cols-[1fr_auto] items-center gap-2 px-1 text-[10.5px]"
    >
      <motion.div
        className={cn("absolute right-0 top-0 bottom-0 rounded-sm z-0", barColor)}
        animate={{ width: `${widthPct}%` }}
        transition={{ duration: 0.3, ease: "easeOut" }}
      />
      <span className={cn("relative z-10", priceColor)}>{fmtPrice(row.p)}</span>
      <span className="relative z-10 text-text-secondary text-right">
        {fmtSize(row.s)}
      </span>
    </motion.div>
  )
}

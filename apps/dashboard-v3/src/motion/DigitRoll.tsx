import { motion, AnimatePresence } from "framer-motion"
import { useMemo } from "react"

/**
 * DigitRoll — animated number whose individual digits roll on update.
 * Used for the hero PnL display and the BTC last-price ticker.
 *
 * The trick: each character (digit, dot, comma, sign) gets its own
 * AnimatePresence-wrapped span keyed by the character. When the value
 * changes, characters that change get exit/enter animations (slide+fade),
 * unchanged characters stay put. Result: an elegant slot-machine feel
 * without flicker.
 */
export function DigitRoll({
  value,
  className,
  duration = 0.45,
}: {
  value: string
  className?: string
  duration?: number
}) {
  // Memoize the character split + positional keys so unchanged chars
  // don't re-animate.
  const chars = useMemo(
    () => value.split("").map((ch, i) => ({ ch, key: `${i}-${ch}` })),
    [value],
  )
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "baseline", overflow: "hidden" }}
    >
      <AnimatePresence mode="popLayout" initial={false}>
        {chars.map(({ ch, key }) => (
          <motion.span
            key={key}
            initial={{ y: -16, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 16, opacity: 0 }}
            transition={{ duration, ease: [0.22, 1, 0.36, 1] }}
            style={{
              display: "inline-block",
              fontVariantNumeric: "tabular-nums",
              whiteSpace: "pre",
            }}
          >
            {ch}
          </motion.span>
        ))}
      </AnimatePresence>
    </span>
  )
}

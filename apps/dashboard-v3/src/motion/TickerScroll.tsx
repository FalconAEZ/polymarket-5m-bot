import type { ReactNode } from "react"
import { cn } from "../lib/cn"

/**
 * Continuous left-scrolling ticker. Renders children twice (once
 * visible, once shifted +100% so the seam is invisible). CSS keyframe
 * pmb-tape-scroll loops every `duration`. Pause on hover for readability.
 */
export function TickerScroll({
  children,
  duration = 60,
  className,
}: {
  children: ReactNode
  duration?: number
  className?: string
}) {
  return (
    <div className={cn("relative overflow-hidden", className)}>
      <div
        className="flex items-center whitespace-nowrap will-change-transform hover:[animation-play-state:paused]"
        style={{
          width: "max-content",
          animation: `pmb-tape-scroll ${duration}s linear infinite`,
        }}
      >
        <div className="flex items-center gap-8 pl-4">{children}</div>
        <div className="flex items-center gap-8 pl-4" aria-hidden="true">
          {children}
        </div>
      </div>
    </div>
  )
}

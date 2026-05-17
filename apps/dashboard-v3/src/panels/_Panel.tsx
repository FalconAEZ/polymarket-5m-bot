import type { ReactNode } from "react"
import { cn } from "../lib/cn"

/**
 * Shared Panel wrapper — every dashboard panel uses this for consistent
 * header (title + optional badge + subtitle), border, padding. The
 * structure mirrors the reference Bloomberg-terminal panels.
 */
export function Panel({
  title,
  subtitle,
  badge,
  badgeTone,
  className,
  noPadding,
  children,
}: {
  title?: string
  subtitle?: string
  badge?: string
  badgeTone?: "good" | "bad" | "warn" | "muted" | "neutral"
  className?: string
  noPadding?: boolean
  children?: ReactNode
}) {
  const badgeCls =
    badgeTone === "good"
      ? "bg-[rgba(110,255,161,0.10)] text-good border-[rgba(110,255,161,0.30)]"
      : badgeTone === "bad"
        ? "bg-[rgba(255,92,92,0.10)] text-bad border-[rgba(255,92,92,0.30)]"
        : badgeTone === "warn"
          ? "bg-[rgba(255,184,74,0.10)] text-warn border-[rgba(255,184,74,0.32)]"
          : "bg-[rgba(160,143,106,0.06)] text-text-secondary border-border-subtle"

  return (
    <section
      className={cn(
        "flex flex-col bg-bg-panel border border-border-subtle rounded-sm h-full",
        noPadding ? "p-0" : "p-2.5",
        "pmb-fade-in",
        className,
      )}
    >
      {(title || badge || subtitle) && (
        <div className={cn("flex flex-col gap-0.5", noPadding && "px-3 pt-2.5")}>
          <div className="flex items-center justify-between gap-2">
            {title && (
              <span className="text-[10px] font-bold uppercase tracking-[0.10em] text-text-secondary">
                {title}
              </span>
            )}
            {badge && (
              <span
                className={cn(
                  "rounded-sm border px-1.5 py-0 text-[9px] font-bold tracking-[0.10em]",
                  badgeCls,
                )}
              >
                {badge}
              </span>
            )}
          </div>
          {subtitle && (
            <div className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
              {subtitle}
            </div>
          )}
        </div>
      )}
      <div className={cn("flex flex-col gap-1 flex-1 min-h-0", title && "mt-2")}>
        {children}
      </div>
    </section>
  )
}

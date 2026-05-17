import { cn } from "../lib/cn"

/**
 * Pulsing live dot — used in the top strip "●LIVE" indicator and on
 * any panel that wants a live-ness signal. CSS keyframe pmb-pulse runs
 * forever (1.6s loop), respects prefers-reduced-motion globally.
 */
export function PulseDot({
  tone = "good",
  className,
}: {
  tone?: "good" | "warn" | "bad"
  className?: string
}) {
  const color =
    tone === "good"
      ? "bg-good shadow-[0_0_8px_rgba(110,255,161,0.6)]"
      : tone === "warn"
        ? "bg-warn shadow-[0_0_8px_rgba(255,184,74,0.6)]"
        : "bg-bad shadow-[0_0_8px_rgba(255,92,92,0.6)]"
  return (
    <span
      className={cn(
        "inline-block w-2 h-2 rounded-full align-middle",
        color,
        "[animation:pmb-pulse_1.6s_ease-in-out_infinite]",
        className,
      )}
      aria-label="live"
    />
  )
}

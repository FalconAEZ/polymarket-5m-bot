/**
 * Number/time/age formatters used across the v3 panels.
 * Consistent voice for every numeric output.
 */

export function fmtUsd(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : n < 0 ? "-" : ""
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

export function fmtUsdPlain(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

export function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return `${(n * 100).toFixed(decimals)}%`
}

export function fmtPctRaw(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  const sign = n > 0 ? "+" : ""
  return `${sign}${n.toFixed(decimals)}%`
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return Math.floor(n).toLocaleString("en-US")
}

export function fmtMs(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  if (n < 1000) return `${Math.round(n)}ms`
  return `${(n / 1000).toFixed(1)}s`
}

export function fmtAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—"
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

export function fmtPrice(p: number | null | undefined, decimals = 2): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—"
  return `$${p.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`
}

export function fmtCtfPrice(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "—"
  return p.toFixed(4)
}

export function fmtCtfSize(s: number): string {
  if (s >= 10000) return `${(s / 1000).toFixed(1)}k`
  return s.toLocaleString("en-US", { maximumFractionDigits: 0 })
}

export function fmtSpotSize(s: number): string {
  return s.toFixed(4)
}

export function fmtClock(iso: string): string {
  const d = new Date(iso)
  const hh = d.getUTCHours().toString().padStart(2, "0")
  const mm = d.getUTCMinutes().toString().padStart(2, "0")
  const ss = d.getUTCSeconds().toString().padStart(2, "0")
  return `${hh}:${mm}:${ss} UTC`
}

export function ageSinceIso(iso: string): number {
  return (Date.now() - new Date(iso).getTime()) / 1000
}

/** Format a delta with explicit + or - prefix; for the bankroll % chip. */
export function fmtDeltaPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  const sign = n >= 0 ? "+" : "-"
  return `${sign}${(Math.abs(n) * 100).toFixed(2)}%`
}

import type { DashboardState } from "../store/types"

/** Initial REST fetch — used when WS is unavailable or for SSR. */
export async function fetchSnapshot(): Promise<DashboardState> {
  const res = await fetch("/api/state", { cache: "no-store" })
  if (!res.ok) throw new Error(`/api/state HTTP ${res.status}`)
  return (await res.json()) as DashboardState
}

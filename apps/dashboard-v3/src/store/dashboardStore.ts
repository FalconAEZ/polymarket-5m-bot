import { create } from "zustand"
import type { DashboardState } from "./types"

/**
 * Single Zustand store. Holds the latest DashboardState plus connection
 * status. WS handler in src/api/ws.ts calls setSnapshot() on each
 * message; React components subscribe via useDashboard hooks.
 */

export type WsStatus = "connecting" | "open" | "reconnecting" | "closed"

interface Slice {
  state: DashboardState | null
  wsStatus: WsStatus
  lastUpdateAt: number | null
  setSnapshot: (s: DashboardState) => void
  setWsStatus: (s: WsStatus) => void
}

export const useDashboardStore = create<Slice>((set) => ({
  state: null,
  wsStatus: "connecting",
  lastUpdateAt: null,
  setSnapshot: (s) => set({ state: s, lastUpdateAt: Date.now() }),
  setWsStatus: (s) => set({ wsStatus: s }),
}))

/** Convenience hook: returns the live state or null until first snapshot. */
export const useDashboard = () => useDashboardStore((s) => s.state)
export const useWsStatus = () => useDashboardStore((s) => s.wsStatus)

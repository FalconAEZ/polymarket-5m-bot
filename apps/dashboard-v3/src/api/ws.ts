import { useDashboardStore } from "../store/dashboardStore"
import type { WsMessage } from "../store/types"

/**
 * WS client with exponential-backoff reconnect.
 * Connect: GET /api/state for first paint, then ws /api/live.
 * On disconnect: backoff 0.5s → 30s with jitter, refetch snapshot on reopen.
 * Per design/dashboard-v3.md §5.4.
 */

const WS_PATH = "/api/live"
const MIN_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 30_000

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${proto}//${window.location.host}${WS_PATH}`
}

let reconnectTimer: number | null = null
let backoff = MIN_BACKOFF_MS

export function connectLive(): () => void {
  const { setSnapshot, setWsStatus } = useDashboardStore.getState()
  let ws: WebSocket | null = null
  let stopped = false

  const open = () => {
    if (stopped) return
    setWsStatus("connecting")
    ws = new WebSocket(wsUrl())
    ws.onopen = () => {
      backoff = MIN_BACKOFF_MS
      setWsStatus("open")
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage
        if (msg.type === "snapshot") {
          setSnapshot(msg.state)
        }
        // Patch type reserved for v3.1 — we send full snapshots in v3.0.
      } catch (e) {
        console.warn("ws parse error:", e)
      }
    }
    ws.onclose = () => {
      if (stopped) return
      setWsStatus("reconnecting")
      const jitter = Math.random() * 250
      reconnectTimer = window.setTimeout(open, backoff + jitter)
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
    }
    ws.onerror = () => {
      // onclose handles backoff; just close to trigger it
      ws?.close()
    }
  }

  open()

  return () => {
    stopped = true
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    ws?.close()
    setWsStatus("closed")
  }
}

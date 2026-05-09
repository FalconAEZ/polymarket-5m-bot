import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import "./index.css"
import App from "./App"
import { connectLive } from "./api/ws"
import { fetchSnapshot } from "./api/snapshot"
import { useDashboardStore } from "./store/dashboardStore"

const qc = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 2, refetchOnWindowFocus: false },
  },
})

// Bootstrap: REST snapshot first (so the page paints something even if
// WS takes a moment), then open the WS for live updates.
fetchSnapshot()
  .then((s) => useDashboardStore.getState().setSnapshot(s))
  .catch((e) => console.warn("initial /api/state fetch failed:", e))

connectLive()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)

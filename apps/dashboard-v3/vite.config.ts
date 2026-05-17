import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vite config for the v3 dashboard. Dev server proxies /api/* to the
// FastAPI backend at localhost:8505 so the React app uses the same
// origin in dev as in prod (where FastAPI serves both / and /api).
// Per design/dashboard-v3.md §4.5.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8505',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
})

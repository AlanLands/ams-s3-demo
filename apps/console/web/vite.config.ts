import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-server host/port and the backend it proxies to, all overridable from the
// environment so a developer running uvicorn on a non-default port (or the
// production 20111-20115 block) needs no edit here. Defaults are what they
// have always been, so an unset environment behaves identically.
const DEV_PORT = Number(process.env.VITE_DEV_PORT ?? 5173)
const API_PROXY_TARGET = process.env.VITE_DEV_API_PROXY ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: DEV_PORT,
    proxy: {
      // Dev-only: every backend route lives under /api (see api/main.py)
      // specifically so it never collides with a same-named React route
      // (/s1, /s2, ...) — this is the only proxy rule needed as a result. In
      // production the built frontend is served by the same process
      // (api/main.py's SPA fallback), so this proxy has no equivalent there.
      '/api': API_PROXY_TARGET,
    },
  },
})

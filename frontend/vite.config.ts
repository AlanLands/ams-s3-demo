import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Dev-only: the FastAPI backend runs on :8000. Every backend route
      // lives under /api (see api/main.py) specifically so it never
      // collides with a same-named React route (/s1, /s2, ...) — this is
      // the only proxy rule needed as a result. In production the built
      // frontend is served by the same process (api/main.py's SPA
      // fallback), so this proxy has no equivalent there.
      '/api': 'http://localhost:8000',
    },
  },
})

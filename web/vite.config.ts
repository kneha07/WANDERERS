import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Served by server.js under /explore/; the live SPHEREx API (backend/, FastAPI) runs on port 8001.
export default defineConfig({
  base: '/explore/',
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8001' } },
})

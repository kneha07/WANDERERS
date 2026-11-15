import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Served by server.js under /explore/; the live SPHEREx API (backend/, FastAPI) runs on port 8001.
export default defineConfig({
  base: '/explore/',
  plugins: [react()],
  // VITE_API_TARGET points the dev proxy at another backend (for example a second checkout on port 8011).
  server: { proxy: { '/api': process.env.VITE_API_TARGET || 'http://127.0.0.1:8001' } },
  // aladin-lite is one 2.4 MB chunk (its WASM is inside), loaded only by the Sky context panel.
  build: { chunkSizeWarningLimit: 2500 },
})

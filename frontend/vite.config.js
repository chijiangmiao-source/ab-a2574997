import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev the page talks to the FastAPI backend via the /api and /health
// proxies; the production build is served by the backend itself.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})

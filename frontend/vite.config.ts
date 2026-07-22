/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Everything now goes through the gateway — one origin, one target.
const GATEWAY_TARGET = process.env.VITE_API_TARGET ?? 'http://localhost:8080'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev proxy so the browser needs no CORS setup. The gateway owns routing,
    // auth-plane checks, and rate limiting behind this single target.
    proxy: Object.fromEntries(
      [
        '/candidate',
        '/auth',
        '/examiners',
        '/blueprints',
        '/exams',
        '/submissions',
        '/topics',
        '/questions',
      ].map((path) => [path, { target: GATEWAY_TARGET, changeOrigin: true }]),
    ),
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})

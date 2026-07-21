/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const EXAM_TARGET = process.env.VITE_API_TARGET ?? 'http://localhost:8001'
const QUESTION_TARGET =
  process.env.VITE_QUESTION_TARGET ?? 'http://localhost:8002'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev proxy so the browser needs no CORS setup. Paths don't collide
    // between the two services; Slice 9 collapses this into the gateway.
    proxy: Object.fromEntries(
      [
        ['/candidate', EXAM_TARGET],
        ['/auth', EXAM_TARGET],
        ['/examiners', EXAM_TARGET],
        ['/blueprints', EXAM_TARGET],
        ['/exams', EXAM_TARGET],
        ['/submissions', EXAM_TARGET],
        ['/topics', QUESTION_TARGET],
        ['/questions', QUESTION_TARGET],
      ].map(([path, target]) => [path, { target, changeOrigin: true }]),
    ),
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})

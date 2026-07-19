import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // The AI-teammate panels are imported from sibling folders with no
    // node_modules of their own — always resolve React from this project.
    dedupe: ['react', 'react-dom'],
  },
  server: {
    port: 5173,
    // Allow importing components from the sibling AI-teammate folders
    fs: { allow: ['..'] },
    proxy: {
      '/api': 'http://localhost:8000',
      // Gemini UI assistant service
      '/assistant-api': 'http://localhost:8002',
      // Therapist copilot service
      '/copilot-api': 'http://localhost:8003',
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['recharts'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: true,
  },
})

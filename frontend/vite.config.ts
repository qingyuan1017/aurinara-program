/// <reference types="vitest/config" />
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'

const dirname = path.dirname(fileURLToPath(import.meta.url))

// Backend API base used by the Vite dev proxy. The app itself always calls
// the relative "/api/v1" prefix, so switching environments only changes this.
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:18000'

// Vitest transforms source files through this same Vite config. The router
// plugin's auto code splitting moves a route's `component` into a separate
// virtual chunk, which leaves `Route.component` undefined when a test imports a
// route module directly. Disable splitting under Vitest only so route-component
// tests render the real component; production builds keep splitting on.
const isVitest = !!process.env.VITEST

export default defineConfig({
  plugins: [
    TanStackRouterVite({ target: 'react', autoCodeSplitting: !isVitest }),
    react(),
    tailwindcss(),
  ],
  // amazon-cognito-identity-js (via its deps) references Node's `global`, which
  // does not exist in the browser. Map it to `globalThis`.
  define: {
    global: 'globalThis',
  },
  resolve: {
    alias: {
      '@': path.resolve(dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})

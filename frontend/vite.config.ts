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

export default defineConfig({
  plugins: [
    TanStackRouterVite({ target: 'react', autoCodeSplitting: true }),
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
})

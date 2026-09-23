import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

const root = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig(({ mode }) => {
  let env = loadEnv(mode, root, '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      // The browser talks to one origin; Vite forwards API calls, including streams.
      proxy: { '/api': env.NBA_API_PROXY_TARGET || 'http://127.0.0.1:8000' },
    },
  }
})

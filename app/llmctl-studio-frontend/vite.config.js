import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function normalizeProxyTarget(value) {
  const raw = String(value ?? '').trim()
  return raw ? raw : ''
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const devApiProxyTarget = normalizeProxyTarget(env.VITE_DEV_API_PROXY_TARGET)

  return {
    plugins: [react()],
    server: devApiProxyTarget
      ? {
          proxy: {
            '^/api(?:/|$)': {
              target: devApiProxyTarget,
              changeOrigin: true,
              ws: true,
            },
          },
        }
      : undefined,
  }
})

import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function normalizeProxyTarget(value) {
  const raw = String(value ?? '').trim()
  return raw ? raw : ''
}

function normalizeBasePath(value) {
  const raw = String(value ?? '').trim()
  if (!raw || raw === '/') {
    return '/'
  }
  return `/${raw.replace(/^\/+|\/+$/g, '')}/`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const devApiProxyTarget = normalizeProxyTarget(env.VITE_DEV_API_PROXY_TARGET)
  const basePath = normalizeBasePath(env.VITE_WEB_BASE_PATH)

  return {
    base: basePath,
    plugins: [react()],
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.js',
    },
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

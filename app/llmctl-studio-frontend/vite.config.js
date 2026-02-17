import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function normalizeProxyTarget(value) {
  const raw = String(value ?? '').trim()
  return raw ? raw : ''
}

function normalizeBasePath(value, fallback = '/') {
  const raw = String(value ?? '').trim()
  const effective = raw || String(fallback ?? '').trim()
  if (!effective || effective === '/') {
    return '/'
  }
  return `/${effective.replace(/^\/+|\/+$/g, '')}/`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const devApiProxyTarget = normalizeProxyTarget(env.VITE_DEV_API_PROXY_TARGET)
  const defaultWebBasePath = mode === 'development' ? '/' : '/web'
  const basePath = normalizeBasePath(env.VITE_WEB_BASE_PATH, defaultWebBasePath)

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

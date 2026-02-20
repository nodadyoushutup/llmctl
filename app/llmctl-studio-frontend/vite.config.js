import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function normalizeProxyTarget(value) {
  const raw = String(value ?? '').trim()
  return raw ? raw : ''
}

function normalizeBoolean(value, fallback = false) {
  const raw = String(value ?? '').trim().toLowerCase()
  if (!raw) {
    return fallback
  }
  if (['1', 'true', 'yes', 'on'].includes(raw)) {
    return true
  }
  if (['0', 'false', 'no', 'off'].includes(raw)) {
    return false
  }
  return fallback
}

function normalizePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? '').trim(), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
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
  const isContainerWorkspace = process.cwd().startsWith('/app/')
  const usePolling = normalizeBoolean(env.VITE_DEV_WATCH_USE_POLLING, isContainerWorkspace)
  const watchInterval = normalizePositiveInt(env.VITE_DEV_WATCH_POLL_INTERVAL, 300)

  const server = {
    watch: {
      // Containerized bind mounts can emit unstable fs events; polling avoids chokidar EIO crashes.
      usePolling,
      interval: watchInterval,
      ignorePermissionErrors: true,
      ignored: ['**/.git/**', '**/node_modules/**'],
    },
  }

  if (devApiProxyTarget) {
    server.proxy = {
      '^/api(?:/|$)': {
        target: devApiProxyTarget,
        changeOrigin: true,
        ws: true,
      },
    }
  }

  return {
    base: basePath,
    plugins: [react()],
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: './src/test/setup.js',
    },
    server,
  }
})

const DEFAULT_API_BASE_PATH = '/api'
const DEFAULT_WEB_BASE_PATH = '/'
const DEFAULT_SOCKET_NAMESPACE = '/rt'

function normalizePathPrefix(value, fallback) {
  const raw = String(value ?? '').trim()
  if (!raw) {
    return fallback
  }
  if (raw === '/') {
    return '/'
  }
  return `/${raw.replace(/^\/+|\/+$/g, '')}`
}

function normalizeNamespace(value) {
  const raw = String(value ?? '').trim()
  if (!raw) {
    return DEFAULT_SOCKET_NAMESPACE
  }
  return raw.startsWith('/') ? raw : `/${raw}`
}

function normalizeOrigin(value) {
  const raw = String(value ?? '').trim()
  if (!raw) {
    return ''
  }
  return raw.replace(/\/+$/, '')
}

const apiBasePath = normalizePathPrefix(import.meta.env.VITE_API_BASE_PATH, DEFAULT_API_BASE_PATH)
const webBasePath = normalizePathPrefix(import.meta.env.VITE_WEB_BASE_PATH, DEFAULT_WEB_BASE_PATH)
const socketPath = normalizePathPrefix(import.meta.env.VITE_SOCKET_PATH, `${apiBasePath}/socket.io`)

export const runtimeConfig = {
  apiBaseUrl: normalizeOrigin(import.meta.env.VITE_API_BASE_URL),
  apiBasePath,
  webBasePath,
  socketPath,
  socketNamespace: normalizeNamespace(import.meta.env.VITE_SOCKET_NAMESPACE),
}

export function resolveApiUrl(endpoint) {
  const rawEndpoint = String(endpoint ?? '').trim()
  const normalizedEndpoint = rawEndpoint.startsWith('/') ? rawEndpoint : `/${rawEndpoint}`
  const path = `${runtimeConfig.apiBasePath}${normalizedEndpoint}`
  if (!runtimeConfig.apiBaseUrl) {
    return path
  }
  return new URL(path, `${runtimeConfig.apiBaseUrl}/`).toString()
}

export function resolveSocketUrl() {
  if (!runtimeConfig.apiBaseUrl) {
    return runtimeConfig.socketPath
  }
  return new URL(runtimeConfig.socketPath, `${runtimeConfig.apiBaseUrl}/`).toString()
}

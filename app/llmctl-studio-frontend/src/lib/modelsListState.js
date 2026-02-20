const MODELS_LIST_DEFAULT_HREF = '/models'
const MODELS_LIST_SCROLL_KEY = 'llmctl:models:list:scroll'
const MODELS_LIST_SCROLL_QUERY_KEY = 'llmctl:models:list:scroll:query'

export function resolveModelsListHref(candidate) {
  const raw = String(candidate || '').trim()
  if (!raw) {
    return MODELS_LIST_DEFAULT_HREF
  }
  return raw.startsWith('/models') ? raw : MODELS_LIST_DEFAULT_HREF
}

export function rememberModelsListScroll(locationSearch = '') {
  if (typeof window === 'undefined') {
    return
  }
  window.sessionStorage.setItem(MODELS_LIST_SCROLL_QUERY_KEY, String(locationSearch || ''))
  window.sessionStorage.setItem(MODELS_LIST_SCROLL_KEY, String(window.scrollY || 0))
}

export function restoreModelsListScroll(locationSearch = '') {
  if (typeof window === 'undefined') {
    return null
  }
  const expectedQuery = String(locationSearch || '')
  const savedQuery = window.sessionStorage.getItem(MODELS_LIST_SCROLL_QUERY_KEY)
  if (savedQuery !== expectedQuery) {
    return null
  }
  const rawOffset = window.sessionStorage.getItem(MODELS_LIST_SCROLL_KEY)
  window.sessionStorage.removeItem(MODELS_LIST_SCROLL_KEY)
  window.sessionStorage.removeItem(MODELS_LIST_SCROLL_QUERY_KEY)
  const offset = Number.parseFloat(String(rawOffset || ''))
  if (!Number.isFinite(offset) || offset < 0) {
    return null
  }
  return offset
}

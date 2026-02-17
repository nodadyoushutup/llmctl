const INTERACTIVE_SELECTOR =
  'a,button,input,select,textarea,label,summary,details'

export function shouldIgnoreRowClick(target) {
  if (!target || typeof target.closest !== 'function') {
    return false
  }
  return Boolean(target.closest(INTERACTIVE_SELECTOR))
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { FlashContext } from '../lib/flashMessages'

const DEFAULT_DURATION_MS = 4200
const ERROR_DURATION_MS = 6200
const MAX_FLASH_ITEMS = 4

function trimMessage(message) {
  return String(message || '').trim()
}

export default function FlashProvider({ children }) {
  const idCounterRef = useRef(1)
  const timerMapRef = useRef(new Map())
  const [items, setItems] = useState([])

  const dismiss = useCallback((id) => {
    const timerId = timerMapRef.current.get(id)
    if (timerId) {
      window.clearTimeout(timerId)
      timerMapRef.current.delete(id)
    }
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const clear = useCallback(() => {
    timerMapRef.current.forEach((timerId) => window.clearTimeout(timerId))
    timerMapRef.current.clear()
    setItems([])
  }, [])

  const push = useCallback((message, options = {}) => {
    const text = trimMessage(message)
    if (!text) {
      return null
    }

    const tone = String(options?.tone || 'info').toLowerCase()
    const durationMs = Number.isFinite(options?.durationMs)
      ? Math.max(0, Number(options.durationMs))
      : tone === 'error'
        ? ERROR_DURATION_MS
        : DEFAULT_DURATION_MS
    const id = `flash-${idCounterRef.current}`
    idCounterRef.current += 1
    const item = {
      id,
      tone,
      message: text,
    }

    setItems((current) => {
      const next = [...current, item]
      return next.length > MAX_FLASH_ITEMS ? next.slice(next.length - MAX_FLASH_ITEMS) : next
    })

    if (durationMs > 0) {
      const timerId = window.setTimeout(() => {
        dismiss(id)
      }, durationMs)
      timerMapRef.current.set(id, timerId)
    }

    return id
  }, [dismiss])

  useEffect(() => () => {
    timerMapRef.current.forEach((timerId) => window.clearTimeout(timerId))
    timerMapRef.current.clear()
  }, [])

  const contextValue = useMemo(() => ({
    push,
    clear,
    dismiss,
    info(message, options) {
      return push(message, { ...options, tone: 'info' })
    },
    success(message, options) {
      return push(message, { ...options, tone: 'success' })
    },
    warning(message, options) {
      return push(message, { ...options, tone: 'warning' })
    },
    error(message, options) {
      return push(message, { ...options, tone: 'error' })
    },
  }), [clear, dismiss, push])

  return (
    <FlashContext.Provider value={contextValue}>
      {children}
      <FlashViewport items={items} onDismiss={dismiss} />
    </FlashContext.Provider>
  )
}

function FlashViewport({ items, onDismiss }) {
  return (
    <div className="flash-viewport" role="region" aria-label="Application notifications" aria-live="polite">
      {items.map((item) => (
        <div key={item.id} className={`flash-item flash-${item.tone}`}>
          <div className="flash-item-content">
            <p>{item.message}</p>
          </div>
          <button
            type="button"
            className="flash-item-close"
            aria-label="Dismiss notification"
            onClick={() => onDismiss(item.id)}
          >
            <i className="fa-solid fa-xmark" aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  )
}

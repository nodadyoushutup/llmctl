import { useCallback, useEffect, useState } from 'react'

const DETAILS_STORAGE_PREFIX = 'llmctl-ui-details:'

function normalizeStorageKey(storageKey) {
  return String(storageKey || '').trim()
}

function readOpenState(storageKey, defaultOpen) {
  const normalizedKey = normalizeStorageKey(storageKey)
  if (!normalizedKey) {
    return Boolean(defaultOpen)
  }
  try {
    const raw = window.localStorage.getItem(`${DETAILS_STORAGE_PREFIX}${normalizedKey}`)
    if (raw === '1') {
      return true
    }
    if (raw === '0') {
      return false
    }
  } catch {
    return Boolean(defaultOpen)
  }
  return Boolean(defaultOpen)
}

function writeOpenState(storageKey, isOpen) {
  const normalizedKey = normalizeStorageKey(storageKey)
  if (!normalizedKey) {
    return
  }
  try {
    window.localStorage.setItem(`${DETAILS_STORAGE_PREFIX}${normalizedKey}`, isOpen ? '1' : '0')
  } catch {
    return
  }
}

export default function PersistedDetails({
  storageKey,
  defaultOpen = false,
  onToggle,
  ...rest
}) {
  const [isOpen, setIsOpen] = useState(() => readOpenState(storageKey, defaultOpen))

  useEffect(() => {
    setIsOpen(readOpenState(storageKey, defaultOpen))
  }, [storageKey, defaultOpen])

  useEffect(() => {
    writeOpenState(storageKey, isOpen)
  }, [storageKey, isOpen])

  const handleToggle = useCallback((event) => {
    const nextOpen = Boolean(event.currentTarget?.open)
    setIsOpen(nextOpen)
    if (typeof onToggle === 'function') {
      onToggle(event)
    }
  }, [onToggle])

  return <details {...rest} open={isOpen} onToggle={handleToggle} />
}

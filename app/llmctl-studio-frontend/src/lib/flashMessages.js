import { createContext, useContext, useEffect, useState } from 'react'

export const FlashContext = createContext(null)

const NO_OP_FLASH = {
  items: [],
  push() { return null },
  clear() {},
  dismiss() {},
  info() { return null },
  success() { return null },
  warning() { return null },
  error() { return null },
}

function trimMessage(message) {
  return String(message || '').trim()
}

export function useFlash() {
  const context = useContext(FlashContext)
  return context || NO_OP_FLASH
}

export function useFlashState(tone = 'info') {
  const flash = useFlash()
  const [value, setValue] = useState('')

  useEffect(() => {
    const text = trimMessage(value)
    if (!text) {
      return
    }
    const normalizedTone = String(tone || 'info').toLowerCase()
    if (normalizedTone === 'error') {
      flash.error(text)
      return
    }
    if (normalizedTone === 'success') {
      flash.success(text)
      return
    }
    if (normalizedTone === 'warning') {
      flash.warning(text)
      return
    }
    flash.info(text)
  }, [flash, tone, value])

  return [value, setValue]
}

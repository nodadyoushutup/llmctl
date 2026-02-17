import { memo, useCallback } from 'react'

function sanitizeIntegerValue(rawValue, allowNegative) {
  const raw = String(rawValue ?? '')
  if (!raw) {
    return ''
  }
  const digits = raw.replace(/\D+/g, '')
  if (!allowNegative) {
    return digits
  }
  if (raw.startsWith('-')) {
    return digits ? `-${digits}` : '-'
  }
  return digits
}

function IntegerInput({
  value,
  onValueChange,
  allowNegative = false,
  ...inputProps
}) {
  const handleChange = useCallback((event) => {
    onValueChange(sanitizeIntegerValue(event.target.value, allowNegative))
  }, [allowNegative, onValueChange])

  return (
    <input
      type="text"
      inputMode="numeric"
      pattern={allowNegative ? '-?[0-9]*' : '[0-9]*'}
      value={value ?? ''}
      onChange={handleChange}
      {...inputProps}
    />
  )
}

export default memo(IntegerInput)

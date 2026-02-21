export function parseAdvancedConfigInput(rawValue) {
  const trimmed = String(rawValue || '').trim()
  if (!trimmed) {
    return { config: {}, normalized: '{}', error: '' }
  }
  try {
    const parsed = JSON.parse(trimmed)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {
        config: {},
        normalized: trimmed,
        error: 'Advanced provider settings must be a JSON object.',
      }
    }
    return {
      config: parsed,
      normalized: JSON.stringify(parsed, null, 2),
      error: '',
    }
  } catch (_error) {
    return {
      config: {},
      normalized: trimmed,
      error: 'Advanced provider settings must be valid JSON.',
    }
  }
}

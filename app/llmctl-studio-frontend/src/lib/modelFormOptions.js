const FREEFORM_MODEL_PROVIDERS = new Set(['claude', 'vllm_remote'])
const REQUIRED_SELECT_MODEL_PROVIDERS = new Set(['codex', 'vllm_local'])

export function normalizeProviderModelOptions(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {}
  }
  return Object.fromEntries(
    Object.entries(raw).map(([provider, options]) => {
      if (!Array.isArray(options)) {
        return [String(provider || ''), []]
      }
      const unique = new Set()
      const normalized = []
      options.forEach((value) => {
        const next = String(value || '').trim()
        if (!next || unique.has(next)) {
          return
        }
        unique.add(next)
        normalized.push(next)
      })
      return [String(provider || ''), normalized]
    }),
  )
}

export function providerUsesFreeformModelInput(provider) {
  return FREEFORM_MODEL_PROVIDERS.has(String(provider || '').trim().toLowerCase())
}

export function providerAllowsBlankModelSelection(provider) {
  const normalized = String(provider || '').trim().toLowerCase()
  return !REQUIRED_SELECT_MODEL_PROVIDERS.has(normalized)
}

export function resolveProviderModelName({
  provider,
  currentModelName = '',
  modelOptions = {},
}) {
  const normalizedProvider = String(provider || '').trim().toLowerCase()
  const current = String(currentModelName || '').trim()
  const options = Array.isArray(modelOptions?.[normalizedProvider])
    ? modelOptions[normalizedProvider]
    : []
  if (!options.length) {
    return current
  }
  if (current && options.includes(current)) {
    return current
  }
  if (providerUsesFreeformModelInput(normalizedProvider)) {
    if (options.length) {
      return options[0]
    }
    return current
  }
  if (!current && providerAllowsBlankModelSelection(normalizedProvider)) {
    return ''
  }
  return options[0]
}

export function modelFieldLabel(provider, providerOptions = []) {
  const normalized = String(provider || '').trim().toLowerCase()
  if (normalized === 'vllm_local') {
    return 'vLLM local model'
  }
  if (normalized === 'vllm_remote') {
    return 'vLLM remote model'
  }
  const option = providerOptions.find((item) => item?.value === normalized)
  if (option?.label) {
    return `${option.label} model`
  }
  return 'Model name (config.model)'
}

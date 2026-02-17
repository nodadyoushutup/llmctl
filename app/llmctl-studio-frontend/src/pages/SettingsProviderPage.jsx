import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import {
  getSettingsProvider,
  updateSettingsProviderClaude,
  updateSettingsProviderCodex,
  updateSettingsProviderControls,
  updateSettingsProviderGemini,
  updateSettingsProviderVllmLocal,
  updateSettingsProviderVllmRemote,
} from '../lib/studioApi'

const SECTION_IDS = ['controls', 'codex', 'gemini', 'claude', 'vllm_local', 'vllm_remote']

function normalizeSection(raw) {
  const normalized = String(raw || '').trim().toLowerCase()
  if (!normalized || normalized === 'controls') {
    return 'controls'
  }
  if (normalized === 'vllm-local') {
    return 'vllm_local'
  }
  if (SECTION_IDS.includes(normalized)) {
    return normalized
  }
  return 'controls'
}

function routeSectionPath(sectionId) {
  if (sectionId === 'controls') {
    return '/settings/provider'
  }
  if (sectionId === 'vllm_local') {
    return '/settings/provider/vllm-local'
  }
  return `/settings/provider/${sectionId}`
}

function sectionLabel(sectionId) {
  if (sectionId === 'vllm_local') {
    return 'vLLM Local'
  }
  if (sectionId === 'vllm_remote') {
    return 'vLLM Remote'
  }
  if (sectionId === 'codex') {
    return 'Codex'
  }
  if (sectionId === 'gemini') {
    return 'Gemini'
  }
  if (sectionId === 'claude') {
    return 'Claude'
  }
  return 'Controls'
}

function errorMessage(error, fallback) {
  if (error instanceof HttpError) {
    if (error.isAuthError) {
      return `${error.message} Sign in to Studio if authentication is enabled.`
    }
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

export default function SettingsProviderPage() {
  const { section } = useParams()
  const activeSection = useMemo(() => normalizeSection(section), [section])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busy, setBusy] = useState(false)

  const [controlsForm, setControlsForm] = useState({
    defaultProvider: '',
    enabledByProvider: {},
  })
  const [codexApiKey, setCodexApiKey] = useState('')
  const [geminiApiKey, setGeminiApiKey] = useState('')
  const [claudeApiKey, setClaudeApiKey] = useState('')
  const [vllmLocalForm, setVllmLocalForm] = useState({ model: '', huggingfaceToken: '' })
  const [vllmRemoteForm, setVllmRemoteForm] = useState({
    baseUrl: '',
    apiKey: '',
    model: '',
    models: '',
  })

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getSettingsProvider({ section: activeSection })
      setState({ loading: false, payload, error: '' })

      const providerDetails = Array.isArray(payload?.provider_details) ? payload.provider_details : []
      const enabledByProvider = {}
      providerDetails.forEach((provider) => {
        const providerId = String(provider?.id || '').trim().toLowerCase()
        if (!providerId) {
          return
        }
        enabledByProvider[providerId] = Boolean(provider.enabled)
      })
      setControlsForm({
        defaultProvider: String(payload?.provider_summary?.provider || ''),
        enabledByProvider,
      })
      setCodexApiKey(String(payload?.codex_settings?.api_key || ''))
      setGeminiApiKey(String(payload?.gemini_settings?.api_key || ''))
      setClaudeApiKey(String(payload?.claude_settings?.api_key || ''))
      setVllmLocalForm({
        model: String(payload?.vllm_local_settings?.model || ''),
        huggingfaceToken: String(payload?.vllm_local_settings?.huggingface?.token || ''),
      })
      setVllmRemoteForm({
        baseUrl: String(payload?.vllm_remote_settings?.base_url || ''),
        apiKey: String(payload?.vllm_remote_settings?.api_key || ''),
        model: String(payload?.vllm_remote_settings?.model || ''),
        models: Array.isArray(payload?.vllm_remote_settings?.models)
          ? payload.vllm_remote_settings.models.join(',')
          : '',
      })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load provider settings.'),
      }))
    }
  }, [activeSection])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function save(action) {
    setActionError('')
    setActionInfo('')
    setBusy(true)
    try {
      await action()
      setActionInfo('Provider settings updated.')
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update provider settings.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const providerDetails = Array.isArray(payload?.provider_details) ? payload.provider_details : []
  const providerSections = Array.isArray(payload?.provider_sections) && payload.provider_sections.length > 0
    ? payload.provider_sections
    : SECTION_IDS.map((id) => ({ id, label: sectionLabel(id) }))
  const localModels = Array.isArray(payload?.vllm_local_settings?.models)
    ? payload.vllm_local_settings.models
    : []

  function toggleEnabled(providerId) {
    setControlsForm((current) => ({
      ...current,
      enabledByProvider: {
        ...current.enabledByProvider,
        [providerId]: !current.enabledByProvider[providerId],
      },
    }))
  }

  return (
    <section className="stack" aria-label="Settings provider">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Settings Provider</h2>
            <p>Native React replacement for provider controls and auth settings.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/core" className="btn-link btn-secondary">Core</Link>
            <Link to="/settings/runtime" className="btn-link btn-secondary">Runtime</Link>
            <Link to="/settings/chat" className="btn-link btn-secondary">Chat</Link>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            {providerSections.map((item) => {
              const itemId = normalizeSection(item?.id)
              const active = itemId === activeSection
              return (
                <Link
                  key={itemId}
                  to={routeSectionPath(itemId)}
                  className={active ? 'btn-link' : 'btn-link btn-secondary'}
                >
                  {item?.label || sectionLabel(itemId)}
                </Link>
              )
            })}
          </div>
        </div>
        {state.loading ? <p>Loading provider settings...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}

        {!state.loading && !state.error && activeSection === 'controls' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Default provider</span>
              <select
                value={controlsForm.defaultProvider}
                onChange={(event) => setControlsForm((current) => ({ ...current, defaultProvider: event.target.value }))}
              >
                <option value="">None</option>
                {providerDetails.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.label || provider.id}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="field">
              <legend>Enabled providers</legend>
              <div className="checkbox-grid">
                {providerDetails.map((provider) => (
                  <label key={provider.id} className="checkbox-item">
                    <input
                      type="checkbox"
                      checked={Boolean(controlsForm.enabledByProvider[provider.id])}
                      onChange={() => toggleEnabled(provider.id)}
                    />
                    <span>{provider.label || provider.id}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(async () => {
                  const enabledProviders = Object.entries(controlsForm.enabledByProvider)
                    .filter(([, enabled]) => Boolean(enabled))
                    .map(([providerId]) => providerId)
                  await updateSettingsProviderControls({
                    defaultProvider: controlsForm.defaultProvider,
                    enabledProviders,
                  })
                })}
              >
                Save Controls
              </button>
            </div>
          </div>
        ) : null}

        {!state.loading && !state.error && activeSection === 'codex' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Codex API key</span>
              <input
                type="password"
                value={codexApiKey}
                onChange={(event) => setCodexApiKey(event.target.value)}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(() => updateSettingsProviderCodex({ apiKey: codexApiKey }))}
              >
                Save Codex
              </button>
            </div>
          </div>
        ) : null}

        {!state.loading && !state.error && activeSection === 'gemini' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Gemini API key</span>
              <input
                type="password"
                value={geminiApiKey}
                onChange={(event) => setGeminiApiKey(event.target.value)}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(() => updateSettingsProviderGemini({ apiKey: geminiApiKey }))}
              >
                Save Gemini
              </button>
            </div>
          </div>
        ) : null}

        {!state.loading && !state.error && activeSection === 'claude' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Claude API key</span>
              <input
                type="password"
                value={claudeApiKey}
                onChange={(event) => setClaudeApiKey(event.target.value)}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(() => updateSettingsProviderClaude({ apiKey: claudeApiKey }))}
              >
                Save Claude
              </button>
            </div>
          </div>
        ) : null}

        {!state.loading && !state.error && activeSection === 'vllm_local' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Local model</span>
              <select
                value={vllmLocalForm.model}
                onChange={(event) => setVllmLocalForm((current) => ({ ...current, model: event.target.value }))}
              >
                <option value="">Default</option>
                {localModels.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label || item.value}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>HuggingFace token (optional)</span>
              <input
                type="password"
                value={vllmLocalForm.huggingfaceToken}
                onChange={(event) => setVllmLocalForm((current) => ({ ...current, huggingfaceToken: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(() => updateSettingsProviderVllmLocal({
                  model: vllmLocalForm.model,
                  huggingfaceToken: vllmLocalForm.huggingfaceToken,
                }))}
              >
                Save vLLM Local
              </button>
            </div>
          </div>
        ) : null}

        {!state.loading && !state.error && activeSection === 'vllm_remote' ? (
          <div className="stack-sm">
            <label className="field">
              <span>Base URL</span>
              <input
                type="text"
                value={vllmRemoteForm.baseUrl}
                onChange={(event) => setVllmRemoteForm((current) => ({ ...current, baseUrl: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>API key</span>
              <input
                type="password"
                value={vllmRemoteForm.apiKey}
                onChange={(event) => setVllmRemoteForm((current) => ({ ...current, apiKey: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Default model</span>
              <input
                type="text"
                value={vllmRemoteForm.model}
                onChange={(event) => setVllmRemoteForm((current) => ({ ...current, model: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Models list (comma separated)</span>
              <input
                type="text"
                value={vllmRemoteForm.models}
                onChange={(event) => setVllmRemoteForm((current) => ({ ...current, models: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(() => updateSettingsProviderVllmRemote(vllmRemoteForm))}
              >
                Save vLLM Remote
              </button>
            </div>
          </div>
        ) : null}
      </article>
    </section>
  )
}

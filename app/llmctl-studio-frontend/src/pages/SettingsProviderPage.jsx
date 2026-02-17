import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { useParams } from 'react-router-dom'
import SettingsInnerSidebar from '../components/SettingsInnerSidebar'
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

function sectionIcon(sectionId) {
  if (sectionId === 'controls') {
    return 'fa-solid fa-wave-square'
  }
  if (sectionId === 'codex') {
    return 'fa-solid fa-robot'
  }
  if (sectionId === 'gemini') {
    return 'fa-solid fa-star'
  }
  if (sectionId === 'claude') {
    return 'fa-solid fa-brain'
  }
  if (sectionId === 'vllm_local') {
    return 'fa-solid fa-computer'
  }
  if (sectionId === 'vllm_remote') {
    return 'fa-solid fa-globe'
  }
  return 'fa-solid fa-gear'
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

function ProviderSectionCard({
  title,
  description,
  icon,
  children,
  actions,
  className = '',
}) {
  return (
    <article className={`card provider-settings-card${className ? ` ${className}` : ''}`}>
      <header className="provider-settings-header">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        {icon ? (
          <span className="provider-settings-icon" aria-hidden="true">
            <i className={icon} />
          </span>
        ) : null}
      </header>
      <div className="stack-sm provider-settings-body">
        {children}
      </div>
      {actions ? <div className="form-actions provider-settings-actions">{actions}</div> : null}
    </article>
  )
}

export default function SettingsProviderPage() {
  const { section } = useParams()
  const activeSection = useMemo(() => normalizeSection(section), [section])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [actionInfo, setActionInfo] = useFlashState('success')
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
        defaultProvider: String(payload?.provider_summary?.provider || '').trim().toLowerCase(),
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
  const providerSidebarItems = providerSections.map((item) => {
    const itemId = normalizeSection(item?.id)
    return {
      id: itemId,
      to: routeSectionPath(itemId),
      label: item?.label || sectionLabel(itemId),
      icon: sectionIcon(itemId),
    }
  })
  const hasStatus = state.loading || state.error || actionError || actionInfo

  function toggleEnabled(providerId) {
    setControlsForm((current) => ({
      ...current,
      defaultProvider: current.defaultProvider === providerId && current.enabledByProvider[providerId]
        ? ''
        : current.defaultProvider,
      enabledByProvider: {
        ...current.enabledByProvider,
        [providerId]: !current.enabledByProvider[providerId],
      },
    }))
  }

  function toggleDefault(providerId) {
    setControlsForm((current) => {
      const isSameProvider = current.defaultProvider === providerId
      return {
        ...current,
        defaultProvider: isSameProvider ? '' : providerId,
        enabledByProvider: {
          ...current.enabledByProvider,
          [providerId]: isSameProvider ? current.enabledByProvider[providerId] : true,
        },
      }
    })
  }

  return (
    <section className="stack provider-fixed-page" aria-label="Settings provider">
      <SettingsInnerSidebar
        title="Provider Sections"
        ariaLabel="Provider sections"
        items={providerSidebarItems}
        activeId={activeSection}
      >
        {hasStatus ? (
          <article className="card">
            {state.loading ? <p>Loading provider settings...</p> : null}
            {state.error ? <p className="error-text">{state.error}</p> : null}
            {actionError ? <p className="error-text">{actionError}</p> : null}
            {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
          </article>
        ) : null}

        {!state.loading && !state.error ? (
          <div className="provider-settings-shell">
            {activeSection === 'controls' ? (
              <ProviderSectionCard
                title="Provider Controls"
                description="Choose the default provider and control which providers are available throughout Studio."
                icon="fa-solid fa-wave-square"
                actions={(
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
                )}
              >
                <div className="provider-controls-list" role="list" aria-label="Provider controls">
                  {providerDetails.length === 0 ? <p className="table-note">No providers available.</p> : null}
                  {providerDetails.map((provider) => {
                    const providerId = String(provider?.id || '').trim().toLowerCase()
                    const providerName = provider.label || providerId
                    const isEnabled = Boolean(controlsForm.enabledByProvider[providerId])
                    const isDefault = controlsForm.defaultProvider === providerId
                    return (
                      <article key={providerId} className="provider-controls-row" role="listitem">
                        <div className="provider-controls-provider-meta">
                          <p className="provider-controls-provider-label">{providerName}</p>
                          <p className="provider-controls-provider-state">
                            {isEnabled ? 'Enabled' : 'Disabled'}
                            {isDefault ? ' / Default' : ''}
                          </p>
                        </div>
                        <div className="provider-controls-provider-toggles">
                          <label className="provider-inline-switch">
                            <input
                              type="checkbox"
                              checked={isEnabled}
                              onChange={() => toggleEnabled(providerId)}
                            />
                            <span className="provider-inline-switch-track" aria-hidden="true" />
                            <span>Enabled</span>
                          </label>
                          <label className="provider-inline-switch">
                            <input
                              type="checkbox"
                              checked={isDefault}
                              onChange={() => toggleDefault(providerId)}
                            />
                            <span className="provider-inline-switch-track" aria-hidden="true" />
                            <span>Default</span>
                          </label>
                        </div>
                      </article>
                    )
                  })}
                </div>
              </ProviderSectionCard>
            ) : null}

            {activeSection === 'codex' ? (
              <ProviderSectionCard
                title="Codex"
                description="Configure the API key used for Codex provider requests."
                icon="fa-solid fa-robot"
                actions={(
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(() => updateSettingsProviderCodex({ apiKey: codexApiKey }))}
                  >
                    Save Codex
                  </button>
                )}
              >
                <label className="field">
                  <span>Codex API key</span>
                  <input
                    type="password"
                    value={codexApiKey}
                    onChange={(event) => setCodexApiKey(event.target.value)}
                  />
                </label>
              </ProviderSectionCard>
            ) : null}

            {activeSection === 'gemini' ? (
              <ProviderSectionCard
                title="Gemini"
                description="Set the Gemini credential used for inference and tooling."
                icon="fa-solid fa-star"
                actions={(
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(() => updateSettingsProviderGemini({ apiKey: geminiApiKey }))}
                  >
                    Save Gemini
                  </button>
                )}
              >
                <label className="field">
                  <span>Gemini API key</span>
                  <input
                    type="password"
                    value={geminiApiKey}
                    onChange={(event) => setGeminiApiKey(event.target.value)}
                  />
                </label>
              </ProviderSectionCard>
            ) : null}

            {activeSection === 'claude' ? (
              <ProviderSectionCard
                title="Claude"
                description="Set the Anthropic API key for Claude-backed responses."
                icon="fa-solid fa-brain"
                actions={(
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(() => updateSettingsProviderClaude({ apiKey: claudeApiKey }))}
                  >
                    Save Claude
                  </button>
                )}
              >
                <label className="field">
                  <span>Claude API key</span>
                  <input
                    type="password"
                    value={claudeApiKey}
                    onChange={(event) => setClaudeApiKey(event.target.value)}
                  />
                </label>
              </ProviderSectionCard>
            ) : null}

            {activeSection === 'vllm_local' ? (
              <ProviderSectionCard
                title="vLLM Local"
                description="Pick a local model and optional Hugging Face token for local vLLM runtime."
                icon="fa-solid fa-computer"
                actions={(
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
                )}
              >
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
                  <span>Hugging Face token (optional)</span>
                  <input
                    type="password"
                    value={vllmLocalForm.huggingfaceToken}
                    onChange={(event) => setVllmLocalForm((current) => ({ ...current, huggingfaceToken: event.target.value }))}
                  />
                </label>
              </ProviderSectionCard>
            ) : null}

            {activeSection === 'vllm_remote' ? (
              <ProviderSectionCard
                title="vLLM Remote"
                description="Configure remote vLLM endpoint details, credentials, and model defaults."
                icon="fa-solid fa-globe"
                actions={(
                  <button
                    type="button"
                    className="btn-link"
                    disabled={busy}
                    onClick={() => save(() => updateSettingsProviderVllmRemote(vllmRemoteForm))}
                  >
                    Save vLLM Remote
                  </button>
                )}
              >
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
              </ProviderSectionCard>
            ) : null}
          </div>
        ) : null}
      </SettingsInnerSidebar>
    </section>
  )
}

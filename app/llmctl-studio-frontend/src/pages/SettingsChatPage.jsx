import { useCallback, useEffect, useState } from 'react'
import { useFlash, useFlashState } from '../lib/flashMessages'
import { Link } from 'react-router-dom'
import IntegerInput from '../components/IntegerInput'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import {
  getSettingsChat,
  updateSettingsChatDefaults,
  updateSettingsRuntimeChat,
} from '../lib/studioApi'

const RESPONSE_COMPLEXITY_OPTIONS = ['low', 'medium', 'high', 'extra_high']

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

export default function SettingsChatPage() {
  const flash = useFlash()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [busy, setBusy] = useState(false)

  const [defaultsForm, setDefaultsForm] = useState({
    defaultModelId: '',
    defaultResponseComplexity: 'medium',
    defaultMcpServerIds: [],
    defaultRagCollections: [],
  })
  const [chatRuntimeForm, setChatRuntimeForm] = useState({
    historyBudgetPercent: '',
    ragBudgetPercent: '',
    mcpBudgetPercent: '',
    compactionTriggerPercent: '',
    compactionTargetPercent: '',
    preserveRecentTurns: '',
    ragTopK: '',
    defaultContextWindowTokens: '',
    maxCompactionSummaryChars: '',
  })

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getSettingsChat()
      setState({ loading: false, payload, error: '' })

      const defaults = payload?.chat_default_settings && typeof payload.chat_default_settings === 'object'
        ? payload.chat_default_settings
        : {}
      setDefaultsForm({
        defaultModelId: defaults.default_model_id ? String(defaults.default_model_id) : '',
        defaultResponseComplexity: String(defaults.default_response_complexity || 'medium'),
        defaultMcpServerIds: Array.isArray(defaults.default_mcp_server_ids)
          ? defaults.default_mcp_server_ids.map((item) => Number.parseInt(String(item), 10)).filter((id) => Number.isInteger(id) && id > 0)
          : [],
        defaultRagCollections: Array.isArray(defaults.default_rag_collections)
          ? defaults.default_rag_collections.map((item) => String(item))
          : [],
      })

      const chatRuntime = payload?.chat_runtime_settings && typeof payload.chat_runtime_settings === 'object'
        ? payload.chat_runtime_settings
        : {}
      setChatRuntimeForm({
        historyBudgetPercent: String(chatRuntime.history_budget_percent || ''),
        ragBudgetPercent: String(chatRuntime.rag_budget_percent || ''),
        mcpBudgetPercent: String(chatRuntime.mcp_budget_percent || ''),
        compactionTriggerPercent: String(chatRuntime.compaction_trigger_percent || ''),
        compactionTargetPercent: String(chatRuntime.compaction_target_percent || ''),
        preserveRecentTurns: String(chatRuntime.preserve_recent_turns || ''),
        ragTopK: String(chatRuntime.rag_top_k || ''),
        defaultContextWindowTokens: String(chatRuntime.default_context_window_tokens || ''),
        maxCompactionSummaryChars: String(chatRuntime.max_compaction_summary_chars || ''),
      })
    } catch (error) {
      const message = errorMessage(error, 'Failed to load chat settings.')
      flash.error(message)
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: silent ? current.error : message,
      }))
    }
  }, [flash])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function save(action, message) {
    setActionError('')
    setActionInfo('')
    setBusy(true)
    try {
      await action()
      setActionInfo(message)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update chat settings.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const models = Array.isArray(payload?.models) ? payload.models : []
  const mcpServers = Array.isArray(payload?.mcp_servers) ? payload.mcp_servers : []
  const ragHealth = payload?.rag_health && typeof payload.rag_health === 'object'
    ? payload.rag_health
    : {}
  const ragCollections = Array.isArray(payload?.rag_collections) ? payload.rag_collections : []

  function toggleMcp(serverId) {
    setDefaultsForm((current) => {
      const already = current.defaultMcpServerIds.includes(serverId)
      return {
        ...current,
        defaultMcpServerIds: already
          ? current.defaultMcpServerIds.filter((id) => id !== serverId)
          : [...current.defaultMcpServerIds, serverId],
      }
    })
  }

  function toggleCollection(collectionId) {
    setDefaultsForm((current) => {
      const already = current.defaultRagCollections.includes(collectionId)
      return {
        ...current,
        defaultRagCollections: already
          ? current.defaultRagCollections.filter((id) => id !== collectionId)
          : [...current.defaultRagCollections, collectionId],
      }
    })
  }

  return (
    <section className="stack" aria-label="Settings chat">
      <article className="card">
        <PanelHeader
          title="Chat Defaults"
          actions={(
            <div className="table-actions">
              <Link to="/settings/core" className="btn-link btn-secondary">Core</Link>
              <Link to="/settings/provider" className="btn-link btn-secondary">Provider</Link>
              <Link to="/settings/runtime/chat" className="btn-link btn-secondary">Runtime Chat</Link>
              <Link to="/settings/integrations" className="btn-link btn-secondary">Integrations</Link>
            </div>
          )}
        />
        <p className="muted">Defaults here are applied when creating a new chat thread.</p>
        {state.loading ? <p>Loading chat settings...</p> : null}
        {!state.loading && !state.error ? (
          <p className="toolbar-meta">
            Runtime controls (compaction, context budget, retrieval) are managed in Runtime Chat.
          </p>
        ) : null}
      </article>

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Chat Defaults</h2>
          <div className="form-grid">
            <label className="field">
              <span>Default model</span>
              <select
                value={defaultsForm.defaultModelId}
                onChange={(event) => setDefaultsForm((current) => ({ ...current, defaultModelId: event.target.value }))}
              >
                <option value="">Use provider/global default</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} ({model.provider})
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Default complexity</span>
              <select
                value={defaultsForm.defaultResponseComplexity}
                onChange={(event) => setDefaultsForm((current) => ({ ...current, defaultResponseComplexity: event.target.value }))}
              >
                {RESPONSE_COMPLEXITY_OPTIONS.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
            <fieldset className="field field-span">
              <legend>Default MCP servers</legend>
              {mcpServers.length === 0 ? <p className="toolbar-meta">No MCP servers available.</p> : null}
              {mcpServers.length > 0 ? (
                <div className="checkbox-grid">
                  {mcpServers.map((server) => (
                    <label key={server.id} className="checkbox-item">
                      <input
                        type="checkbox"
                        checked={defaultsForm.defaultMcpServerIds.includes(server.id)}
                        onChange={() => toggleMcp(server.id)}
                      />
                      <span>{server.name}</span>
                    </label>
                  ))}
                </div>
              ) : null}
            </fieldset>
            <fieldset className="field field-span">
              <legend>Default RAG collections</legend>
              {ragHealth.state !== 'configured_healthy' ? (
                <p className="toolbar-meta">
                  RAG state: {ragHealth.state || 'unknown'}
                  {ragHealth.error ? ` (${ragHealth.error})` : ''}
                </p>
              ) : null}
              {ragHealth.state === 'configured_healthy' && ragCollections.length > 0 ? (
                <div className="checkbox-grid">
                  {ragCollections.map((collection) => (
                    <label key={collection.id} className="checkbox-item">
                      <input
                        type="checkbox"
                        checked={defaultsForm.defaultRagCollections.includes(collection.id)}
                        onChange={() => toggleCollection(collection.id)}
                      />
                      <span>{collection.name}</span>
                    </label>
                  ))}
                </div>
              ) : null}
            </fieldset>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsChatDefaults({
                    defaultModelId: defaultsForm.defaultModelId
                      ? Number.parseInt(defaultsForm.defaultModelId, 10)
                      : null,
                    defaultResponseComplexity: defaultsForm.defaultResponseComplexity,
                    defaultMcpServerIds: defaultsForm.defaultMcpServerIds,
                    defaultRagCollections: defaultsForm.defaultRagCollections,
                  }),
                  'Chat default settings updated.',
                )}
              >
                Save Chat Defaults
              </button>
            </div>
          </div>
        </article>
      ) : null}

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Chat Runtime</h2>
          <div className="form-grid">
            <label className="field"><span>History budget percent</span><IntegerInput value={chatRuntimeForm.historyBudgetPercent} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, historyBudgetPercent: value }))} /></label>
            <label className="field"><span>RAG budget percent</span><IntegerInput value={chatRuntimeForm.ragBudgetPercent} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, ragBudgetPercent: value }))} /></label>
            <label className="field"><span>MCP budget percent</span><IntegerInput value={chatRuntimeForm.mcpBudgetPercent} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, mcpBudgetPercent: value }))} /></label>
            <label className="field"><span>Compaction trigger percent</span><IntegerInput value={chatRuntimeForm.compactionTriggerPercent} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, compactionTriggerPercent: value }))} /></label>
            <label className="field"><span>Compaction target percent</span><IntegerInput value={chatRuntimeForm.compactionTargetPercent} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, compactionTargetPercent: value }))} /></label>
            <label className="field"><span>Preserve recent turns</span><IntegerInput value={chatRuntimeForm.preserveRecentTurns} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, preserveRecentTurns: value }))} /></label>
            <label className="field"><span>RAG top K</span><IntegerInput value={chatRuntimeForm.ragTopK} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, ragTopK: value }))} /></label>
            <label className="field"><span>Default context window tokens</span><IntegerInput value={chatRuntimeForm.defaultContextWindowTokens} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, defaultContextWindowTokens: value }))} /></label>
            <label className="field"><span>Max compaction summary chars</span><IntegerInput value={chatRuntimeForm.maxCompactionSummaryChars} onValueChange={(value) => setChatRuntimeForm((current) => ({ ...current, maxCompactionSummaryChars: value }))} /></label>
            <div className="form-actions">
              <button
                type="button"
                className="btn-link btn-secondary"
                disabled={busy}
                onClick={() => save(
                  () => updateSettingsRuntimeChat(chatRuntimeForm),
                  'Chat runtime settings updated.',
                )}
              >
                Save Chat Runtime
              </button>
            </div>
          </div>
        </article>
      ) : null}
    </section>
  )
}

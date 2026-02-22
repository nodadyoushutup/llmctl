import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import PersistedDetails from '../components/PersistedDetails'
import { HttpError } from '../lib/httpClient'
import { createQuickNode, getQuickNodeMeta, updateQuickNodeDefaults } from '../lib/studioApi'

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

function parseOptionalId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function toggleListValue(currentValues, value) {
  if (currentValues.includes(value)) {
    return currentValues.filter((entry) => entry !== value)
  }
  return [...currentValues, value]
}

function mergeAttachments(current, incoming) {
  const merged = [...current]
  const seen = new Set(merged.map((file) => `${file.name}:${file.size}:${file.lastModified}`))
  for (const file of incoming) {
    const key = `${file.name}:${file.size}:${file.lastModified}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    merged.push(file)
  }
  return merged
}

export default function QuickNodePage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [validationError, setValidationError] = useState('')
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [saving, setSaving] = useState(false)
  const [saveDefaultsBusy, setSaveDefaultsBusy] = useState(false)
  const [quickDefaultsDirty, setQuickDefaultsDirty] = useState(false)
  const [isControlsOpen, setIsControlsOpen] = useState(true)
  const [initialized, setInitialized] = useState(false)
  const [attachments, setAttachments] = useState([])
  const [form, setForm] = useState({
    prompt: '',
    agentId: '',
    modelId: '',
    mcpServerIds: [],
    ragCollections: [],
  })

  useEffect(() => {
    let cancelled = false
    getQuickNodeMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load quick node metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const agents = payload && Array.isArray(payload.agents) ? payload.agents : []
  const models = payload && Array.isArray(payload.models) ? payload.models : []
  const mcpServers = payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []
  const ragCollections = payload && Array.isArray(payload.rag_collections) ? payload.rag_collections : []
  const defaultModelId = payload && Number.isInteger(payload.default_model_id)
    ? payload.default_model_id
    : null
  const defaultAgentId = payload && Number.isInteger(payload.default_agent_id)
    ? payload.default_agent_id
    : null
  const selectedMcpServerIds = payload && Array.isArray(payload.selected_mcp_server_ids)
    ? payload.selected_mcp_server_ids
      .map((value) => Number.parseInt(String(value), 10))
      .filter((value) => Number.isInteger(value) && value > 0)
      .map((value) => String(value))
    : []
  const selectedRagCollections = payload && Array.isArray(payload.selected_rag_collections)
    ? payload.selected_rag_collections
      .map((value) => String(value || '').trim())
      .filter((value) => value)
    : []

  useEffect(() => {
    if (initialized || !payload) {
      return
    }
    setForm((current) => ({
      ...current,
      agentId: defaultAgentId ? String(defaultAgentId) : '',
      modelId: defaultModelId ? String(defaultModelId) : '',
      mcpServerIds: selectedMcpServerIds,
      ragCollections: selectedRagCollections,
    }))
    setQuickDefaultsDirty(false)
    setInitialized(true)
  }, [defaultAgentId, defaultModelId, initialized, payload, selectedMcpServerIds, selectedRagCollections])

  function setDefaultField(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
    setQuickDefaultsDirty(true)
  }

  function toggleDefaultList(field, value) {
    setForm((current) => ({
      ...current,
      [field]: toggleListValue(current[field], value),
    }))
    setQuickDefaultsDirty(true)
  }

  async function handleSaveDefaults() {
    setActionError('')
    setActionInfo('')
    setSaveDefaultsBusy(true)
    try {
      const response = await updateQuickNodeDefaults({
        defaultAgentId: parseOptionalId(form.agentId),
        defaultModelId: parseOptionalId(form.modelId),
        defaultMcpServerIds: form.mcpServerIds.map((value) => Number(value)),
        defaultRagCollections: form.ragCollections,
      })
      const defaults = response && typeof response === 'object' && response.quick_default_settings && typeof response.quick_default_settings === 'object'
        ? response.quick_default_settings
        : null
      if (defaults) {
        const nextPayload = payload && typeof payload === 'object'
          ? {
            ...payload,
            default_agent_id: defaults.default_agent_id ?? null,
            default_model_id: defaults.default_model_id ?? null,
            selected_mcp_server_ids: Array.isArray(defaults.default_mcp_server_ids) ? defaults.default_mcp_server_ids : [],
            selected_rag_collections: Array.isArray(defaults.default_rag_collections) ? defaults.default_rag_collections : [],
          }
          : null
        if (nextPayload) {
          setState((current) => ({ ...current, payload: nextPayload }))
        }
      }
      setActionInfo('Quick defaults saved.')
      setQuickDefaultsDirty(false)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to save quick defaults.'))
    } finally {
      setSaveDefaultsBusy(false)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setValidationError('')
    setActionError('')
    const prompt = String(form.prompt || '').trim()
    if (!prompt) {
      setValidationError('Prompt is required.')
      return
    }
    const modelId = parseOptionalId(form.modelId)
    if (!modelId) {
      setValidationError('Model is required.')
      return
    }
    setSaving(true)
    try {
      const payload = await createQuickNode({
        prompt,
        agentId: parseOptionalId(form.agentId),
        modelId,
        mcpServerIds: form.mcpServerIds.map((value) => Number(value)),
        ragCollections: form.ragCollections,
        attachments,
      })
      const taskId = payload && Number.isInteger(payload.task_id) ? payload.task_id : null
      if (taskId) {
        navigate(`/nodes/${taskId}`)
        return
      }
      navigate('/nodes')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to send quick node.'))
    } finally {
      setSaving(false)
    }
  }

  function handleAttachmentInputChange(event) {
    const files = Array.from(event.target.files || [])
    if (files.length === 0) {
      return
    }
    setAttachments((current) => mergeAttachments(current, files))
    event.target.value = ''
  }

  function handlePromptPaste(event) {
    const files = Array.from(event.clipboardData?.files || [])
    if (files.length === 0) {
      return
    }
    setAttachments((current) => mergeAttachments(current, files))
  }

  function handlePromptKeyDown(event) {
    if (event.isComposing || event.key !== 'Enter' || event.shiftKey || saving) {
      return
    }
    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  return (
    <section className="quick-node-shell" aria-label="Quick Node">
      {state.loading ? <p className="muted">Loading quick node metadata...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {validationError ? <p className="error-text">{validationError}</p> : null}
      <form className="quick-node-form" id="quick-node-form" onSubmit={handleSubmit}>
        <article className="quick-node-panel quick-node-controls">
          <PanelHeader
            title="Quick Node"
            actions={(
              <Link to="/nodes" className="icon-button" aria-label="Back to nodes" title="Back to nodes">
                <i className="fa-solid fa-list" />
              </Link>
            )}
          />
          <div className="quick-node-panel-body quick-node-controls-body">
            <p className="muted quick-node-panel-intro">
              Run one-off prompts with the default Quick Node profile, or pick an agent override.
            </p>
            <PersistedDetails
              className="chat-session-drawer quick-node-controls-drawer"
              storageKey="quick:controls"
              defaultOpen
              onToggle={(event) => {
                setIsControlsOpen(Boolean(event.currentTarget?.open))
              }}
            >
              <summary>
                <span className="chat-session-title">controls</span>
                <span className="chat-session-summary">
                  <button
                    type="button"
                    className="icon-button chat-session-summary-action"
                    aria-label="Save quick defaults"
                    title="Save quick defaults"
                    disabled={saveDefaultsBusy}
                    onClick={async (event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      const summary = event.currentTarget.closest('summary')
                      const drawer = summary?.parentElement
                      if (!summary || !drawer) {
                        return
                      }
                      if (!drawer.open) {
                        summary.click()
                        return
                      }
                      await handleSaveDefaults()
                    }}
                  >
                    <i className={`fa-solid ${isControlsOpen ? 'fa-floppy-disk' : 'fa-angle-down'}`} />
                  </button>
                </span>
              </summary>
              <div className="chat-session-content">
                <div className="chat-session-controls">
                  <label className="chat-control">
                    Agent override (optional)
                    <select
                      className="input"
                      value={form.agentId}
                      disabled={agents.length === 0}
                      onChange={(event) => setDefaultField('agentId', event.target.value)}
                    >
                      <option value="">Default Quick Node</option>
                      {agents.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name}
                        </option>
                      ))}
                    </select>
                    {agents.length > 0 ? (
                      <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                        Leave blank to use the hard-coded Quick Node profile.
                      </span>
                    ) : (
                      <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                        No override agents created yet. Quick Node default is still available.
                      </span>
                    )}
                  </label>

                  <label className="chat-control">
                    Model
                    <select
                      required
                      className="input"
                      value={form.modelId}
                      disabled={models.length === 0}
                      onChange={(event) => setDefaultField('modelId', event.target.value)}
                    >
                      <option value="">Select model</option>
                      {models.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} ({model.provider})
                        </option>
                      ))}
                    </select>
                    {models.length > 0 ? (
                      <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                        Defaults to Settings default model, otherwise the first model on this list.
                      </span>
                    ) : (
                      <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                        No models available. Create a model before sending a quick node.
                      </span>
                    )}
                  </label>

                  <label className="chat-control">
                    Context (optional)
                    <div className="chat-session-groups quick-node-context-groups">
                      <PersistedDetails
                        className="chat-picker chat-picker-group"
                        storageKey="quick:collections"
                      >
                        <summary>
                          <span className="chat-picker-summary">
                            <i className="fa-solid fa-database" />
                            <span>Collections</span>
                          </span>
                        </summary>
                        {ragCollections.length > 0 ? (
                          <div className="chat-checklist">
                            {ragCollections.map((collection) => {
                              const collectionId = String(collection?.id || '').trim()
                              if (!collectionId) {
                                return null
                              }
                              const checked = form.ragCollections.includes(collectionId)
                              return (
                                <label key={`quick-rag-${collectionId}`}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleDefaultList('ragCollections', collectionId)}
                                  />
                                  <span>{collection.name}</span>
                                </label>
                              )
                            })}
                          </div>
                        ) : (
                          <p className="muted chat-picker-empty">No collections available.</p>
                        )}
                      </PersistedDetails>

                      <PersistedDetails
                        className="chat-picker chat-picker-group"
                        storageKey="quick:mcp-servers"
                      >
                        <summary>
                          <span className="chat-picker-summary">
                            <i className="fa-solid fa-plug" />
                            <span>MCP Servers</span>
                          </span>
                        </summary>
                        {mcpServers.length > 0 ? (
                          <div className="chat-checklist">
                            {mcpServers.map((server) => {
                              const serverId = String(server.id)
                              const checked = form.mcpServerIds.includes(serverId)
                              return (
                                <label key={server.id}>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleDefaultList('mcpServerIds', serverId)}
                                  />
                                  <span>
                                    {server.name} <span className="muted">({server.server_key})</span>
                                  </span>
                                </label>
                              )
                            })}
                          </div>
                        ) : (
                          <p className="muted chat-picker-empty">No MCP servers available.</p>
                        )}
                      </PersistedDetails>

                    </div>
                    <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                      Integrations are auto-applied from selected MCP servers.
                    </span>
                    <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                      Collections and MCP servers are saved with Quick defaults.
                    </span>
                  </label>

                  <div className="chat-session-actions">
                    <p className="chat-session-dirty" aria-live="polite">
                      {quickDefaultsDirty ? 'Unsaved changes' : 'Defaults are saved'}
                    </p>
                  </div>
                </div>
              </div>
            </PersistedDetails>
          </div>
        </article>

        <article className="quick-node-panel quick-node-prompt">
          <PanelHeader
            title="Prompt"
            actions={(
              <button
                type="submit"
                className="icon-button icon-button-primary"
                aria-label={saving ? 'Sending to CLI' : 'Send to CLI'}
                title={saving ? 'Sending to CLI' : 'Send to CLI'}
                disabled={saving || models.length === 0}
              >
                <ActionIcon name="play" />
              </button>
            )}
          />
          <div className="quick-node-panel-body quick-node-prompt-body">
            <label className="label">
              Prompt
              <textarea
                required
                className="textarea"
                value={form.prompt}
                placeholder="Ask anything."
                onPaste={handlePromptPaste}
                onKeyDown={handlePromptKeyDown}
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>

            <label className="label">
              Attachments (optional)
              <input type="file" className="input" multiple onChange={handleAttachmentInputChange} />
              <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                Paste images into the prompt or choose files. Saved to <code>data/attachments</code>.
              </span>
              {attachments.length > 0 ? (
                <div className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                  {attachments.map((file) => file.name).join(', ')}
                </div>
              ) : null}
            </label>
          </div>
        </article>
      </form>
    </section>
  )
}

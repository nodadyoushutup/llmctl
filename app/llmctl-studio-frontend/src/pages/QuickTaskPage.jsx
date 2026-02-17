import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createQuickTask, getQuickTaskMeta } from '../lib/studioApi'

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

export default function QuickTaskPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const [form, setForm] = useState({
    prompt: '',
    agentId: '',
    modelId: '',
    mcpServerIds: [],
    integrationKeys: [],
  })

  useEffect(() => {
    let cancelled = false
    getQuickTaskMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load quick task metadata.') })
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
  const integrationOptions = payload && Array.isArray(payload.integration_options) ? payload.integration_options : []
  const defaultModelId = payload && Number.isInteger(payload.default_model_id)
    ? payload.default_model_id
    : null

  useEffect(() => {
    if (initialized || !payload) {
      return
    }
    const selectedIntegrationKeys = Array.isArray(payload.selected_integration_keys)
      ? payload.selected_integration_keys.map((value) => String(value))
      : []
    setForm((current) => ({
      ...current,
      modelId: defaultModelId ? String(defaultModelId) : '',
      integrationKeys: selectedIntegrationKeys,
    }))
    setInitialized(true)
  }, [defaultModelId, initialized, payload])

  async function handleSubmit(event) {
    event.preventDefault()
    setFormError('')
    const prompt = String(form.prompt || '').trim()
    if (!prompt) {
      setFormError('Prompt is required.')
      return
    }
    const modelId = parseOptionalId(form.modelId)
    if (!modelId) {
      setFormError('Model is required.')
      return
    }
    setSaving(true)
    try {
      const payload = await createQuickTask({
        prompt,
        agentId: parseOptionalId(form.agentId),
        modelId,
        mcpServerIds: form.mcpServerIds.map((value) => Number(value)),
        integrationKeys: form.integrationKeys,
      })
      const taskId = payload && Number.isInteger(payload.task_id) ? payload.task_id : null
      if (taskId) {
        navigate(`/nodes/${taskId}`)
        return
      }
      navigate('/nodes')
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to send quick task.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="quick-node-shell" aria-label="Quick task">
      {state.loading ? <p className="muted">Loading quick task metadata...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {formError ? <p className="error-text">{formError}</p> : null}
      <form className="quick-node-form" id="quick-task-form" onSubmit={handleSubmit}>
        <article className="quick-node-panel quick-node-controls">
          <div className="quick-node-controls-header">
            <div className="quick-node-controls-copy">
              <h2 className="section-title">Quick Node</h2>
              <p className="muted">
                Run one-off prompts with the default Quick Node profile, or pick an agent override.
              </p>
            </div>
            <Link to="/nodes" className="btn btn-secondary">
              Back to Nodes
            </Link>
          </div>

          <label className="label">
            Agent override (optional)
            <select
              className="input"
              value={form.agentId}
              disabled={agents.length === 0}
              onChange={(event) => setForm((current) => ({ ...current, agentId: event.target.value }))}
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

          <label className="label">
            Model
            <select
              required
              className="input"
              value={form.modelId}
              disabled={models.length === 0}
              onChange={(event) => setForm((current) => ({ ...current, modelId: event.target.value }))}
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

          <label className="label">
            MCP servers (optional)
            {mcpServers.length > 0 ? (
              <div className="quick-node-options-list">
                {mcpServers.map((server) => {
                  const serverId = String(server.id)
                  const checked = form.mcpServerIds.includes(serverId)
                  return (
                    <label key={server.id} className="quick-node-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setForm((current) => ({
                            ...current,
                            mcpServerIds: toggleListValue(current.mcpServerIds, serverId),
                          }))
                        }
                      />
                      <span>
                        {server.name} <span className="muted">({server.server_key})</span>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                No MCP servers available.
              </span>
            )}
          </label>

          <label className="label">
            Integrations (optional)
            {integrationOptions.length > 0 ? (
              <div className="quick-node-options-list">
                {integrationOptions.map((option) => {
                  const key = String(option.key)
                  const checked = form.integrationKeys.includes(key)
                  return (
                    <label key={key} className="quick-node-option">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setForm((current) => ({
                            ...current,
                            integrationKeys: toggleListValue(current.integrationKeys, key),
                          }))
                        }
                      />
                      <span>
                        {option.label}{' '}
                        <span className="muted">({option.connected ? 'configured' : 'not configured'})</span>
                      </span>
                    </label>
                  )
                })}
              </div>
            ) : (
              <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                No integrations available.
              </span>
            )}
            <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
              Selected integrations are injected into prompt context.
            </span>
          </label>
        </article>

        <article className="quick-node-panel quick-node-prompt">
          <div className="quick-node-prompt-body">
            <label className="label">
              Prompt
              <textarea
                required
                className="textarea"
                value={form.prompt}
                placeholder="Ask anything."
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>

            <label className="label">
              Attachments (optional)
              <input type="file" className="input" multiple disabled />
              <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                Attachment upload parity is still in progress. Quick Task currently submits prompt/config only.
              </span>
            </label>

            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving || models.length === 0}>
                {saving ? 'Sending...' : 'Send to CLI'}
              </button>
            </div>
          </div>
        </article>
      </form>
    </section>
  )
}

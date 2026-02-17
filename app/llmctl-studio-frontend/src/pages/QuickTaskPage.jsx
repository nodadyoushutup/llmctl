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
    <section className="stack" aria-label="Quick task">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Quick Task</h2>
            <p>Native React replacement for `/quick` one-off node execution.</p>
          </div>
          <div className="table-actions">
            <Link to="/nodes" className="btn-link btn-secondary">All Nodes</Link>
          </div>
        </div>
        {state.loading ? <p>Loading quick task metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {formError ? <p className="error-text">{formError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field field-span">
              <span>Prompt</span>
              <textarea
                required
                value={form.prompt}
                placeholder="Ask anything."
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Agent override (optional)</span>
              <select
                value={form.agentId}
                onChange={(event) => setForm((current) => ({ ...current, agentId: event.target.value }))}
              >
                <option value="">Default Quick Node</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Model</span>
              <select
                required
                value={form.modelId}
                onChange={(event) => setForm((current) => ({ ...current, modelId: event.target.value }))}
              >
                <option value="">Select model</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} ({model.provider})
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="field field-span">
              <span>MCP servers (optional)</span>
              {mcpServers.length > 0 ? (
                <div className="checkbox-grid">
                  {mcpServers.map((server) => {
                    const serverId = String(server.id)
                    const checked = form.mcpServerIds.includes(serverId)
                    return (
                      <label key={server.id} className="checkbox-item">
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
                        <span>{server.name} <span className="toolbar-meta">({server.server_key})</span></span>
                      </label>
                    )
                  })}
                </div>
              ) : (
                <p className="toolbar-meta">No MCP servers available.</p>
              )}
            </fieldset>
            <fieldset className="field field-span">
              <span>Integrations (optional)</span>
              {integrationOptions.length > 0 ? (
                <div className="checkbox-grid">
                  {integrationOptions.map((option) => {
                    const key = String(option.key)
                    const checked = form.integrationKeys.includes(key)
                    return (
                      <label key={key} className="checkbox-item">
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
                          <span className="toolbar-meta">({option.connected ? 'configured' : 'not configured'})</span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              ) : (
                <p className="toolbar-meta">No integrations available.</p>
              )}
            </fieldset>
            <p className="toolbar-meta">
              Attachment upload parity is still handled by the legacy form path. API-mode quick tasks currently submit prompt/config only.
            </p>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={saving || models.length === 0}>
                {saving ? 'Sending...' : 'Send to Worker'}
              </button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

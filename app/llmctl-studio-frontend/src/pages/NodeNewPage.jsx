import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createNode, getNodeMeta } from '../lib/studioApi'

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

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function formatScriptTypeLabel(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .trim()
}

export default function NodeNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const [form, setForm] = useState({
    agentId: '',
    prompt: '',
    integrationKeys: [],
    scriptIdsByType: {},
  })

  useEffect(() => {
    let cancelled = false
    getNodeMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load node metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const agents = useMemo(
    () => (payload && Array.isArray(payload.agents) ? payload.agents : []),
    [payload],
  )
  const scripts = useMemo(
    () => (payload && Array.isArray(payload.scripts) ? payload.scripts : []),
    [payload],
  )
  const scriptTypeFields = useMemo(
    () => (payload && payload.script_type_fields && typeof payload.script_type_fields === 'object'
      ? payload.script_type_fields
      : {}),
    [payload],
  )
  const integrationOptions = useMemo(
    () => (payload && Array.isArray(payload.integration_options) ? payload.integration_options : []),
    [payload],
  )
  const scriptTypeChoices = useMemo(
    () => (payload && Array.isArray(payload.script_type_choices) ? payload.script_type_choices : []),
    [payload],
  )

  const scriptTypeValues = useMemo(() => Object.keys(scriptTypeFields), [scriptTypeFields])
  const scriptLabelByType = useMemo(() => {
    const labels = {}
    for (const choice of scriptTypeChoices) {
      labels[String(choice.value)] = String(choice.label || choice.value)
    }
    return labels
  }, [scriptTypeChoices])

  const scriptsByType = useMemo(() => {
    const grouped = {}
    for (const scriptType of scriptTypeValues) {
      grouped[scriptType] = []
    }
    for (const script of scripts) {
      const key = String(script.script_type || '')
      if (!grouped[key]) {
        grouped[key] = []
      }
      grouped[key].push(script)
    }
    return grouped
  }, [scriptTypeValues, scripts])

  useEffect(() => {
    if (initialized || !payload) {
      return
    }
    const defaults = {}
    for (const scriptType of scriptTypeValues) {
      defaults[scriptType] = []
    }
    const selectedIntegrationKeys = Array.isArray(payload.selected_integration_keys)
      ? payload.selected_integration_keys.map((value) => String(value))
      : []
    setForm((current) => ({
      ...current,
      integrationKeys: selectedIntegrationKeys,
      scriptIdsByType: defaults,
    }))
    setInitialized(true)
  }, [initialized, payload, scriptTypeValues])

  function toggleIntegration(key) {
    setForm((current) => {
      const exists = current.integrationKeys.includes(key)
      return {
        ...current,
        integrationKeys: exists
          ? current.integrationKeys.filter((value) => value !== key)
          : [...current.integrationKeys, key],
      }
    })
  }

  function toggleScript(scriptType, scriptId) {
    setForm((current) => {
      const currentForType = Array.isArray(current.scriptIdsByType[scriptType])
        ? current.scriptIdsByType[scriptType]
        : []
      const exists = currentForType.includes(scriptId)
      const nextForType = exists
        ? currentForType.filter((value) => value !== scriptId)
        : [...currentForType, scriptId]
      return {
        ...current,
        scriptIdsByType: {
          ...current.scriptIdsByType,
          [scriptType]: nextForType,
        },
      }
    })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setFormError('')
    const parsedAgentId = parseId(form.agentId)
    if (!parsedAgentId) {
      setFormError('Select an agent.')
      return
    }
    const prompt = String(form.prompt || '').trim()
    if (!prompt) {
      setFormError('Prompt is required.')
      return
    }
    setSaving(true)
    try {
      const payload = await createNode({
        agentId: parsedAgentId,
        prompt,
        integrationKeys: form.integrationKeys,
        scriptIdsByType: form.scriptIdsByType,
      })
      const taskId = payload && Number.isInteger(payload.task_id) ? payload.task_id : null
      if (taskId) {
        navigate(`/nodes/${taskId}`)
        return
      }
      navigate('/nodes')
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to queue node.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Create node">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Create Node</h2>
            <p>Native React replacement for `/nodes/new` queue form.</p>
          </div>
          <div className="table-actions">
            <Link to="/nodes" className="btn-link btn-secondary">All Nodes</Link>
          </div>
        </div>
        {state.loading ? <p>Loading node metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {formError ? <p className="error-text">{formError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Agent</span>
              <select
                required
                value={form.agentId}
                onChange={(event) => setForm((current) => ({ ...current, agentId: event.target.value }))}
              >
                <option value="">Select agent</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
              {agents.length === 0 ? <span className="toolbar-meta">Create an agent first to queue a node.</span> : null}
            </label>
            <label className="field field-span">
              <span>Prompt</span>
              <textarea
                required
                value={form.prompt}
                placeholder="Write the node prompt."
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>
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
                          onChange={() => toggleIntegration(key)}
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
            <fieldset className="field field-span">
              <span>Scripts (optional)</span>
              {scriptTypeValues.length === 0 ? <p className="toolbar-meta">No script bindings available.</p> : null}
              {scriptTypeValues.map((scriptType) => {
                const choices = Array.isArray(scriptsByType[scriptType]) ? scriptsByType[scriptType] : []
                const label = scriptLabelByType[scriptType] || formatScriptTypeLabel(scriptType)
                return (
                  <div key={scriptType} className="stack-sm">
                    <strong>{label}</strong>
                    {choices.length === 0 ? (
                      <p className="toolbar-meta">No scripts for this type.</p>
                    ) : (
                      <div className="checkbox-grid">
                        {choices.map((script) => {
                          const scriptId = Number(script.id)
                          const checked = Array.isArray(form.scriptIdsByType[scriptType])
                            && form.scriptIdsByType[scriptType].includes(scriptId)
                          return (
                            <label key={script.id} className="checkbox-item">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleScript(scriptType, scriptId)}
                              />
                              <span>{script.file_name}</span>
                            </label>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </fieldset>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={saving || agents.length === 0}>
                {saving ? 'Queueing...' : 'Queue Node'}
              </button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

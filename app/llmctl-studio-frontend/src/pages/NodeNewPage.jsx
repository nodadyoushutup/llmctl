import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
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

export default function NodeNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [validationError, setValidationError] = useState('')
  const [, setActionError] = useFlashState('error')
  const [saving, setSaving] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const [attachments, setAttachments] = useState([])
  const [form, setForm] = useState({
    agentId: '',
    prompt: '',
    mcpServerIds: [],
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
  const mcpServers = useMemo(
    () => (payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []),
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
    const selectedMcpServerIds = Array.isArray(payload.selected_mcp_server_ids)
      ? payload.selected_mcp_server_ids
        .map((value) => String(value || '').trim())
        .filter((value) => value)
      : []
    setForm((current) => ({
      ...current,
      mcpServerIds: selectedMcpServerIds,
      scriptIdsByType: defaults,
    }))
    setInitialized(true)
  }, [initialized, payload, scriptTypeValues])

  function toggleMcpServer(serverId) {
    setForm((current) => {
      const exists = current.mcpServerIds.includes(serverId)
      return {
        ...current,
        mcpServerIds: exists
          ? current.mcpServerIds.filter((value) => value !== serverId)
          : [...current.mcpServerIds, serverId],
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
    setValidationError('')
    setActionError('')
    const parsedAgentId = parseId(form.agentId)
    if (!parsedAgentId) {
      setValidationError('Select an agent.')
      return
    }
    const prompt = String(form.prompt || '').trim()
    if (!prompt) {
      setValidationError('Prompt is required.')
      return
    }
    setSaving(true)
    try {
      const payload = await createNode({
        agentId: parsedAgentId,
        prompt,
        mcpServerIds: form.mcpServerIds.map((value) => Number(value)),
        scriptIdsByType: form.scriptIdsByType,
        attachments,
      })
      const taskId = payload && Number.isInteger(payload.task_id) ? payload.task_id : null
      if (taskId) {
        navigate(`/nodes/${taskId}`)
        return
      }
      navigate('/nodes')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to queue node.'))
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

  return (
    <section className="stack" aria-label="Create node">
      <article className="card">
        <PanelHeader
          title="Create Node"
          actions={(
            <div className="table-actions">
              <Link to="/nodes" className="btn-link btn-secondary">All Nodes</Link>
            </div>
          )}
        />
        <p className="muted">Queue a single run and trigger the celery worker.</p>
        {state.loading ? <p>Loading node metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {validationError ? <p className="error-text">{validationError}</p> : null}
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
                onPaste={handlePromptPaste}
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Attachments (optional)</span>
              <input type="file" multiple onChange={handleAttachmentInputChange} />
              <span className="toolbar-meta">Paste images into the prompt or choose files. Saved to <code>data/attachments</code>.</span>
              {attachments.length > 0 ? (
                <span className="toolbar-meta">{attachments.map((file) => file.name).join(', ')}</span>
              ) : null}
            </label>
            <fieldset className="field field-span">
              <span>MCP Servers (optional)</span>
              {mcpServers.length > 0 ? (
                <div className="checkbox-grid">
                  {mcpServers.map((server) => {
                    const serverId = String(server.id)
                    const checked = form.mcpServerIds.includes(serverId)
                    return (
                      <label key={serverId} className="checkbox-item">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleMcpServer(serverId)}
                        />
                        <span>
                          {server.name}{' '}
                          <span className="toolbar-meta">({String(server.server_key || '').trim() || 'custom'})</span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              ) : (
                <p className="toolbar-meta">No MCP servers available.</p>
              )}
              <span className="toolbar-meta">
                Integrations are auto-applied from selected MCP servers.
              </span>
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

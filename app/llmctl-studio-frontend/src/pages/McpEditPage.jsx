import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMcpEdit, updateMcp } from '../lib/studioApi'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
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

function parseConfig(configText) {
  if (!String(configText || '').trim()) {
    return {}
  }
  const parsed = JSON.parse(configText)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Config must be a JSON object.')
  }
  return parsed
}

export default function McpEditPage() {
  const navigate = useNavigate()
  const { mcpId } = useParams()
  const parsedMcpId = useMemo(() => parseId(mcpId), [mcpId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', serverKey: '', description: '', configText: '{}' })

  useEffect(() => {
    if (!parsedMcpId) {
      return
    }
    let cancelled = false
    getMcpEdit(parsedMcpId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const mcp = payload?.mcp_server && typeof payload.mcp_server === 'object' ? payload.mcp_server : {}
        setForm({
          name: String(mcp.name || ''),
          serverKey: String(mcp.server_key || ''),
          description: String(mcp.description || ''),
          configText: mcp.config_json || '{}',
        })
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load MCP edit metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMcpId])
  const invalidId = parsedMcpId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid MCP server id.' : state.error

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedMcpId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updateMcp(parsedMcpId, {
        name: form.name,
        serverKey: form.serverKey,
        description: form.description,
        config: parseConfig(form.configText),
      })
      navigate(`/mcps/${parsedMcpId}`)
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to update MCP server.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit MCP server">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Edit MCP Server</h2>
            <p>Update server details and config JSON.</p>
          </div>
          <div className="table-actions">
            {parsedMcpId ? <Link to={`/mcps/${parsedMcpId}`} className="btn-link btn-secondary">Back to MCP</Link> : null}
            <Link to="/mcps" className="btn-link btn-secondary">All MCP Servers</Link>
          </div>
        </div>
        {loading ? <p>Loading MCP server...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!loading && !error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Server key</span>
              <input
                type="text"
                required
                value={form.serverKey}
                onChange={(event) => setForm((current) => ({ ...current, serverKey: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description (optional)</span>
              <input
                type="text"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Config JSON</span>
              <textarea
                required
                value={form.configText}
                onChange={(event) => setForm((current) => ({ ...current, configText: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Save MCP Server</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

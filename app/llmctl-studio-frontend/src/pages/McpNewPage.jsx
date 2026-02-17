import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createMcp, getMcpMeta } from '../lib/studioApi'

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

export default function McpNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ name: '', serverKey: '', description: '', configText: '{}' })

  useEffect(() => {
    let cancelled = false
    getMcpMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load MCP metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const payload = await createMcp({
        name: form.name,
        serverKey: form.serverKey,
        description: form.description,
        config: parseConfig(form.configText),
      })
      const mcpId = payload?.mcp_server?.id
      if (mcpId) {
        navigate(`/mcps/${mcpId}`)
      } else {
        navigate('/mcps')
      }
    } catch (error) {
      setActionError(errorMessage(error, error instanceof Error ? error.message : 'Failed to create MCP server.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="New MCP server">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>New MCP Server</h2>
            <p>Native React replacement for `/mcps/new` custom MCP creation.</p>
          </div>
          <Link to="/mcps" className="btn-link btn-secondary">All MCP Servers</Link>
        </div>
        {state.loading ? <p>Loading MCP options...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
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
              <button type="submit" className="btn-link" disabled={busy}>Create MCP Server</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

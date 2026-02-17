import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteMcp, getMcps } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

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

function McpTable({ title, rows, onDelete, busyById, navigate, allowDelete }) {
  if (rows.length === 0) {
    return (
      <article className="card">
        <h2>{title}</h2>
        <p>No entries.</p>
      </article>
    )
  }
  return (
    <article className="card">
      <h2>{title}</h2>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Key</th>
              <th>Type</th>
              <th>Bindings</th>
              <th>Updated</th>
              <th className="table-actions-cell">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((mcp) => {
              const href = `/mcps/${mcp.id}`
              const busy = Boolean(busyById[mcp.id])
              return (
                <tr
                  key={mcp.id}
                  className="table-row-link"
                  data-href={href}
                  onClick={(event) => {
                    if (shouldIgnoreRowClick(event.target)) {
                      return
                    }
                    navigate(href)
                  }}
                >
                  <td>
                    <Link to={href}>{mcp.name || `MCP ${mcp.id}`}</Link>
                  </td>
                  <td>{mcp.server_key || '-'}</td>
                  <td>{mcp.is_integrated ? 'integrated' : 'custom'}</td>
                  <td>{mcp.binding_count ?? 0}</td>
                  <td>{mcp.updated_at || '-'}</td>
                  <td className="table-actions-cell">
                    <div className="table-actions">
                      {!mcp.is_integrated ? (
                        <Link
                          to={`/mcps/${mcp.id}/edit`}
                          className="icon-button"
                          aria-label="Edit MCP server"
                          title="Edit MCP server"
                        >
                          <ActionIcon name="edit" />
                        </Link>
                      ) : null}
                      {allowDelete && !mcp.is_integrated ? (
                        <button
                          type="button"
                          className="icon-button icon-button-danger"
                          aria-label="Delete MCP server"
                          title="Delete MCP server"
                          disabled={busy}
                          onClick={() => onDelete(mcp.id)}
                        >
                          <ActionIcon name="trash" />
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </article>
  )
}

export default function McpsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getMcps()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load MCP servers.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const integrated = payload && Array.isArray(payload.integrated_mcp_servers)
    ? payload.integrated_mcp_servers
    : []
  const custom = payload && Array.isArray(payload.custom_mcp_servers) ? payload.custom_mcp_servers : []

  function setBusy(mcpId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[mcpId] = true
      } else {
        delete next[mcpId]
      }
      return next
    })
  }

  async function handleDelete(mcpId) {
    if (!window.confirm('Delete this MCP server?')) {
      return
    }
    setActionError('')
    setBusy(mcpId, true)
    try {
      await deleteMcp(mcpId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete MCP server.'))
    } finally {
      setBusy(mcpId, false)
    }
  }

  return (
    <section className="stack" aria-label="MCP servers">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>MCP Servers</h2>
            <p>Native React replacement for `/mcps` list/detail/edit flows.</p>
          </div>
          <Link to="/mcps/new" className="btn-link">New MCP Server</Link>
        </div>
        {state.loading ? <p>Loading MCP servers...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
      </article>

      {!state.loading && !state.error ? (
        <McpTable
          title="Custom MCP servers"
          rows={custom}
          onDelete={handleDelete}
          busyById={busyById}
          navigate={navigate}
          allowDelete
        />
      ) : null}

      {!state.loading && !state.error ? (
        <McpTable
          title="Integrated MCP servers"
          rows={integrated}
          onDelete={handleDelete}
          busyById={busyById}
          navigate={navigate}
          allowDelete={false}
        />
      ) : null}
    </section>
  )
}

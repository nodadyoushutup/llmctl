import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMcp } from '../lib/studioApi'

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

export default function McpDetailPage() {
  const { mcpId } = useParams()
  const parsedMcpId = useMemo(() => parseId(mcpId), [mcpId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedMcpId) {
      return
    }
    let cancelled = false
    getMcp(parsedMcpId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load MCP server.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMcpId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const mcp = payload?.mcp_server && typeof payload.mcp_server === 'object' ? payload.mcp_server : null
  const nodes = Array.isArray(payload?.attached_nodes) ? payload.attached_nodes : []
  const tasks = Array.isArray(payload?.attached_tasks) ? payload.attached_tasks : []
  const invalidId = parsedMcpId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid MCP server id.' : state.error

  return (
    <section className="stack" aria-label="MCP detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{mcp ? mcp.name : 'MCP Server'}</h2>
            <p>{mcp?.description || 'Server metadata, config, and binding usage.'}</p>
          </div>
          <div className="table-actions">
            {mcp && !mcp.is_integrated ? <Link to={`/mcps/${mcp.id}/edit`} className="btn-link">Edit</Link> : null}
            <Link to="/mcps" className="btn-link btn-secondary">All MCP Servers</Link>
          </div>
        </div>
        {loading ? <p>Loading MCP server...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {mcp ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Server key</dt>
                <dd>{mcp.server_key || '-'}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{mcp.is_integrated ? 'integrated' : 'custom'}</dd>
              </div>
              <div>
                <dt>Bindings</dt>
                <dd>{mcp.binding_count ?? 0}</dd>
              </div>
            </dl>
            <pre>{mcp.config_json || '{}'}</pre>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Flowchart node bindings</h2>
        {nodes.length === 0 ? <p>No flowchart node bindings.</p> : (
          <ul>
            {nodes.map((node) => (
              <li key={node.id}>
                <Link to={`/flowcharts/${node.flowchart_id}`}>{node.flowchart_name || `Flowchart ${node.flowchart_id}`}</Link>
                {' '}
                / {node.title || node.node_type || `Node ${node.id}`}
              </li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Task bindings</h2>
        {tasks.length === 0 ? <p>No task bindings.</p> : (
          <ul>
            {tasks.map((task) => (
              <li key={task.id}>Task {task.id} ({task.status || 'unknown'})</li>
            ))}
          </ul>
        )}
      </article>
    </section>
  )
}

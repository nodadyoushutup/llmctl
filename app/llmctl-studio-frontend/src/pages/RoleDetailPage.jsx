import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getRole } from '../lib/studioApi'
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

export default function RoleDetailPage() {
  const navigate = useNavigate()
  const { roleId } = useParams()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  const parsedRoleId = useMemo(() => {
    const parsed = Number.parseInt(String(roleId || ''), 10)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null
  }, [roleId])

  useEffect(() => {
    if (!parsedRoleId) {
      return undefined
    }
    let cancelled = false
    getRole(parsedRoleId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            error: errorMessage(error, 'Failed to load role.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedRoleId])

  const role = state.payload?.role && typeof state.payload.role === 'object' ? state.payload.role : null
  const assignedAgents = Array.isArray(role?.assigned_agents) ? role.assigned_agents : []
  const detailsJson = String(role?.details_json || '{}')
  const resolvedError = !parsedRoleId ? 'Invalid role id.' : state.error

  function handleAgentRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Role detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{role ? role.name : 'Role'}</h2>
            {role?.description ? <p>{role.description}</p> : null}
          </div>
          <div className="table-actions">
            {role ? <Link to={`/roles/${role.id}/edit`} className="btn-link">Edit</Link> : null}
            <Link to="/roles" className="btn-link btn-secondary">All Roles</Link>
          </div>
        </div>
        {parsedRoleId && state.loading ? <p>Loading role...</p> : null}
        {resolvedError ? <p className="error-text">{resolvedError}</p> : null}
        {role ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Type</dt>
                <dd>{role.is_system ? 'system' : 'user'}</dd>
              </div>
              <div>
                <dt>Agent bindings</dt>
                <dd>{assignedAgents.length}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{role.created_at || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{role.updated_at || '-'}</dd>
              </div>
            </dl>
            <div>
              <h3>Details JSON</h3>
              <pre>{detailsJson}</pre>
            </div>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Assigned Agents</h2>
        {assignedAgents.length === 0 ? <p>No agents bound to this role.</p> : null}
        {assignedAgents.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {assignedAgents.map((agent) => {
                  const href = `/agents/${agent.id}`
                  return (
                    <tr
                      key={agent.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleAgentRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{agent.name || `Agent ${agent.id}`}</Link>
                      </td>
                      <td>{agent.description || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}

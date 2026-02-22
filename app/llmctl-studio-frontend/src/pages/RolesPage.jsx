import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { deleteRole, getRoles } from '../lib/studioApi'
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

export default function RolesPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, roles: [], error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async () => {
    try {
      const payload = await getRoles()
      const roles = Array.isArray(payload?.roles) ? payload.roles : []
      setState({ loading: false, roles, error: '' })
    } catch (error) {
      setState({ loading: false, roles: [], error: errorMessage(error, 'Failed to load roles.') })
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const roles = useMemo(() => state.roles, [state.roles])

  function setBusy(roleId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[roleId] = true
      } else {
        delete next[roleId]
      }
      return next
    })
  }

  async function handleDelete(role) {
    if (!role || role.is_system) {
      return
    }
    if (!window.confirm('Delete this role? Agents using it will be unbound.')) {
      return
    }
    setActionError('')
    setBusy(role.id, true)
    try {
      await deleteRole(role.id)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete role.'))
    } finally {
      setBusy(role.id, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack workflow-fixed-page" aria-label="Roles">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="Roles"
          actions={(
            <Link to="/roles/new" className="icon-button" aria-label="New role" title="New role">
              <ActionIcon name="plus" />
            </Link>
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <p className="panel-header-copy">
            Reusable role instructions that can be bound to agents.
          </p>
          {state.loading ? <p>Loading roles...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {!state.loading && !state.error && roles.length === 0 ? <p>No roles created yet.</p> : null}
          {!state.loading && !state.error && roles.length > 0 ? (
            <div className="table-wrap workflow-list-table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Agent bindings</th>
                    <th>Type</th>
                    <th className="table-actions-cell">Delete</th>
                  </tr>
                </thead>
                <tbody>
                  {roles.map((role) => {
                    const href = `/roles/${role.id}`
                    const busy = Boolean(busyById[role.id])
                    const isSystem = Boolean(role.is_system)
                    return (
                      <tr
                        key={role.id}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{role.name || `Role ${role.id}`}</Link>
                          <p className="muted" style={{ marginTop: '4px', fontSize: '12px' }}>
                            {role.description || '-'}
                          </p>
                        </td>
                        <td>{Number.isInteger(role.binding_count) ? role.binding_count : 0}</td>
                        <td>
                          <span className="chip">{isSystem ? 'system' : 'user'}</span>
                        </td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            {isSystem ? (
                              <span className="icon-button" aria-label="System role is read-only" title="System role is read-only">
                                <i className="fa-solid fa-lock" />
                              </span>
                            ) : (
                              <button
                                type="button"
                                className="icon-button icon-button-danger"
                                aria-label="Delete role"
                                title="Delete role"
                                disabled={busy}
                                onClick={() => handleDelete(role)}
                              >
                                <ActionIcon name="trash" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

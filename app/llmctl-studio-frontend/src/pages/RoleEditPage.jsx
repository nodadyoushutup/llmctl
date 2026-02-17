import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { deleteRole, getRoleEdit, updateRole } from '../lib/studioApi'

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

export default function RoleEditPage() {
  const navigate = useNavigate()
  const { roleId } = useParams()
  const parsedRoleId = useMemo(() => parseId(roleId), [roleId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    detailsJson: '{}',
  })

  useEffect(() => {
    if (!parsedRoleId) {
      return undefined
    }
    let cancelled = false
    getRoleEdit(parsedRoleId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const role = payload?.role && typeof payload.role === 'object' ? payload.role : null
        if (role) {
          setForm({
            name: String(role.name || ''),
            description: String(role.description || ''),
            detailsJson: String(role.details_json || '{}'),
          })
        }
        setState({ loading: false, payload, error: '' })
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
  const resolvedError = !parsedRoleId ? 'Invalid role id.' : state.error

  async function handleSave(event) {
    event.preventDefault()
    if (!parsedRoleId) {
      return
    }
    setFormError('')
    const description = String(form.description || '').trim()
    if (!description) {
      setFormError('Description is required.')
      return
    }
    setBusy(true)
    try {
      await updateRole(parsedRoleId, {
        name: String(form.name || '').trim(),
        description,
        detailsJson: String(form.detailsJson || '').trim() || '{}',
      })
      const payload = await getRoleEdit(parsedRoleId)
      const updatedRole = payload?.role && typeof payload.role === 'object' ? payload.role : null
      if (updatedRole) {
        setForm({
          name: String(updatedRole.name || ''),
          description: String(updatedRole.description || ''),
          detailsJson: String(updatedRole.details_json || '{}'),
        })
      }
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to update role.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!parsedRoleId || !role || role.is_system) {
      return
    }
    if (!window.confirm('Delete this role? Agents using it will be unbound.')) {
      return
    }
    setFormError('')
    setDeleting(true)
    try {
      await deleteRole(parsedRoleId)
      navigate('/roles')
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to delete role.'))
      setDeleting(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit role">
      <article className="card">
        <div className="title-row">
          <h2>{role ? `Edit ${role.name}` : 'Edit Role'}</h2>
          <div className="table-actions">
            {role ? <Link to={`/roles/${role.id}`} className="btn-link btn-secondary">Back to Role</Link> : null}
            <Link to="/roles" className="btn-link btn-secondary">All Roles</Link>
          </div>
        </div>
        {parsedRoleId && state.loading ? <p>Loading role...</p> : null}
        {resolvedError ? <p className="error-text">{resolvedError}</p> : null}
        {formError ? <p className="error-text">{formError}</p> : null}
        {!state.loading && !resolvedError && role ? (
          <form className="form-grid" onSubmit={handleSave}>
            <label className="field">
              <span>Name (optional)</span>
              <input
                type="text"
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description</span>
              <textarea
                required
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Details JSON</span>
              <textarea
                value={form.detailsJson}
                onChange={(event) => setForm((current) => ({ ...current, detailsJson: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy || deleting}>
                {busy ? 'Saving...' : 'Save Role'}
              </button>
              {!role.is_system ? (
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  onClick={handleDelete}
                  disabled={busy || deleting}
                >
                  {deleting ? 'Deleting...' : 'Delete Role'}
                </button>
              ) : null}
            </div>
          </form>
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
                {assignedAgents.map((agent) => (
                  <tr key={agent.id}>
                    <td>
                      <Link to={`/agents/${agent.id}`}>{agent.name || `Agent ${agent.id}`}</Link>
                    </td>
                    <td>{agent.description || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}

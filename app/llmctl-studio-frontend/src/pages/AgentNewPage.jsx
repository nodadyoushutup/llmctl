import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { createAgent, getAgentMeta } from '../lib/studioApi'

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

export default function AgentNewPage() {
  const navigate = useNavigate()
  const [roles, setRoles] = useState([])
  const [metaError, setMetaError] = useState('')
  const [validationError, setValidationError] = useState('')
  const [, setActionError] = useFlashState('error')
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    roleId: '',
  })

  useEffect(() => {
    let cancelled = false
    getAgentMeta()
      .then((payload) => {
        if (cancelled) {
          return
        }
        const nextRoles = payload && typeof payload === 'object' && Array.isArray(payload.roles)
          ? payload.roles
          : []
        setRoles(nextRoles)
      })
      .catch((error) => {
        if (!cancelled) {
          setMetaError(errorMessage(error, 'Failed to load role options.'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setValidationError('')
    setActionError('')
    const description = String(form.description || '').trim()
    if (!description) {
      setValidationError('Description is required.')
      return
    }
    const roleId = form.roleId ? Number.parseInt(form.roleId, 10) : null
    setSaving(true)
    try {
      const payload = await createAgent({
        name: String(form.name || '').trim(),
        description,
        roleId: Number.isInteger(roleId) && roleId > 0 ? roleId : null,
      })
      const createdId = payload && typeof payload === 'object' && payload.agent && payload.agent.id
      if (Number.isInteger(createdId) && createdId > 0) {
        navigate(`/agents/${createdId}/edit`)
        return
      }
      navigate('/agents')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to create agent.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Create Agent">
      <article className="card">
        <PanelHeader
          title="Create Agent"
          actions={<Link to="/agents" className="btn-link">All Agents</Link>}
        />
        {metaError ? <p className="error-text">{metaError}</p> : null}
        {validationError ? <p className="error-text">{validationError}</p> : null}
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Name (optional)</span>
            <input
              type="text"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Description</span>
            <textarea
              required
              value={form.description}
              onChange={(event) =>
                setForm((current) => ({ ...current, description: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>Role (optional)</span>
            <select
              value={form.roleId}
              onChange={(event) => setForm((current) => ({ ...current, roleId: event.target.value }))}
            >
              <option value="">No role</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                </option>
              ))}
            </select>
          </label>
          <div className="form-actions">
            <button type="submit" className="btn-link" disabled={saving}>
              {saving ? 'Creating...' : 'Create Agent'}
            </button>
            <button
              type="button"
              className="btn-link btn-secondary"
              onClick={() => setForm({ name: '', description: '', roleId: '' })}
              disabled={saving}
            >
              Reset
            </button>
          </div>
        </form>
      </article>
    </section>
  )
}

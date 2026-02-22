import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { createRole, getRoleMeta } from '../lib/studioApi'

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

export default function RoleNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, error: '' })
  const [validationError, setValidationError] = useState('')
  const [, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    detailsJson: '{}',
  })

  useEffect(() => {
    let cancelled = false
    getRoleMeta()
      .then(() => {
        if (!cancelled) {
          setState({ loading: false, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, error: errorMessage(error, 'Failed to load role metadata.') })
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
    setBusy(true)
    try {
      const payload = await createRole({
        name: String(form.name || '').trim(),
        description,
        detailsJson: String(form.detailsJson || '').trim() || '{}',
      })
      const createdId = payload?.role?.id
      if (Number.isInteger(createdId) && createdId > 0) {
        navigate(`/roles/${createdId}/edit`)
        return
      }
      navigate('/roles')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to create role.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Create role">
      <article className="card">
        <PanelHeader
          title="Create Role"
          actions={<Link to="/roles" className="btn-link btn-secondary">All Roles</Link>}
        />
        {state.loading ? <p>Loading role metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {validationError ? <p className="error-text">{validationError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
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
              <button type="submit" className="btn-link" disabled={busy}>
                {busy ? 'Creating...' : 'Create Role'}
              </button>
              <button
                type="button"
                className="btn-link btn-secondary"
                onClick={() => setForm({ name: '', description: '', detailsJson: '{}' })}
                disabled={busy}
              >
                Reset
              </button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getScriptEdit, updateScript } from '../lib/studioApi'

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

export default function ScriptEditPage() {
  const navigate = useNavigate()
  const { scriptId } = useParams()
  const parsedScriptId = useMemo(() => parseId(scriptId), [scriptId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ fileName: '', description: '', scriptType: '', content: '' })

  useEffect(() => {
    if (!parsedScriptId) {
      return
    }
    let cancelled = false
    getScriptEdit(parsedScriptId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const script = payload?.script && typeof payload.script === 'object' ? payload.script : {}
        const scriptTypes = Array.isArray(payload?.script_types) ? payload.script_types : []
        const firstType = scriptTypes[0]?.value || ''
        setForm({
          fileName: String(script.file_name || ''),
          description: String(script.description || ''),
          scriptType: String(script.script_type || firstType),
          content: String(script.content || ''),
        })
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load script edit metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedScriptId])
  const invalidId = parsedScriptId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid script id.' : state.error

  const scriptTypes = Array.isArray(state.payload?.script_types) ? state.payload.script_types : []

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedScriptId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updateScript(parsedScriptId, form)
      navigate(`/scripts/${parsedScriptId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update script.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit script">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Edit Script</h2>
            <p>Update file metadata and content.</p>
          </div>
          <div className="table-actions">
            {parsedScriptId ? <Link to={`/scripts/${parsedScriptId}`} className="btn-link btn-secondary">Back to Script</Link> : null}
            <Link to="/scripts" className="btn-link btn-secondary">All Scripts</Link>
          </div>
        </div>
        {loading ? <p>Loading script...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!loading && !error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>File name</span>
              <input
                type="text"
                required
                value={form.fileName}
                onChange={(event) => setForm((current) => ({ ...current, fileName: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Script type</span>
              <select
                value={form.scriptType}
                onChange={(event) => setForm((current) => ({ ...current, scriptType: event.target.value }))}
              >
                {scriptTypes.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
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
              <span>Content</span>
              <textarea
                required
                value={form.content}
                onChange={(event) => setForm((current) => ({ ...current, content: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Save Script</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

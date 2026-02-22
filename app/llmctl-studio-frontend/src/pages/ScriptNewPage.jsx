import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { createScript, getScriptMeta } from '../lib/studioApi'

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

export default function ScriptNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ fileName: '', description: '', scriptType: '', content: '' })

  useEffect(() => {
    let cancelled = false
    getScriptMeta()
      .then((payload) => {
        if (cancelled) {
          return
        }
        const scriptTypes = Array.isArray(payload?.script_types) ? payload.script_types : []
        const firstType = scriptTypes[0]?.value || ''
        setForm((current) => ({ ...current, scriptType: current.scriptType || firstType }))
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load script metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const scriptTypes = Array.isArray(state.payload?.script_types) ? state.payload.script_types : []

  async function handleSubmit(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const payload = await createScript(form)
      const scriptId = payload?.script?.id
      if (scriptId) {
        navigate(`/scripts/${scriptId}`)
      } else {
        navigate('/scripts')
      }
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to create script.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="New script">
      <article className="card">
        <PanelHeader
          title="New Script"
          titleTag="h2"
          actions={<Link to="/scripts" className="btn-link btn-secondary">All Scripts</Link>}
        />
        <p className="panel-header-copy">Upload a script file or paste content to attach to agents.</p>
        {state.loading ? <p>Loading script options...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
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
              <button type="submit" className="btn-link" disabled={busy}>Create Script</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getRagSourceEdit, updateRagSource } from '../lib/studioApi'

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

function sourceFormFromPayload(source) {
  return {
    name: String(source?.name || ''),
    kind: String(source?.kind || 'local'),
    localPath: String(source?.local_path || ''),
    gitRepo: String(source?.git_repo || ''),
    gitBranch: String(source?.git_branch || ''),
    driveFolderId: String(source?.drive_folder_id || ''),
    indexScheduleValue: String(source?.index_schedule_value || ''),
    indexScheduleUnit: String(source?.index_schedule_unit || ''),
    indexScheduleMode: String(source?.index_schedule_mode || 'fresh'),
  }
}

export default function RagSourceEditPage() {
  const navigate = useNavigate()
  const { sourceId } = useParams()
  const parsedSourceId = Number.parseInt(String(sourceId ?? ''), 10)
  const invalidId = !Number.isInteger(parsedSourceId) || parsedSourceId <= 0

  const [state, setState] = useState({ loading: !invalidId, payload: null, error: '' })
  const [form, setForm] = useState(sourceFormFromPayload(null))
  const [submitError, setSubmitError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (invalidId) {
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const payload = await getRagSourceEdit(parsedSourceId)
        if (active) {
          setState({ loading: false, payload, error: '' })
          setForm(sourceFormFromPayload(payload?.source || null))
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load source edit metadata.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [invalidId, parsedSourceId])

  async function handleSubmit(event) {
    event.preventDefault()
    if (invalidId) {
      return
    }
    setSubmitError('')
    setBusy(true)
    try {
      await updateRagSource(parsedSourceId, form)
      navigate(`/rag/sources/${parsedSourceId}`)
    } catch (error) {
      setSubmitError(errorMessage(error, 'Failed to update source.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null

  if (invalidId) {
    return (
      <section className="stack" aria-label="Edit RAG source">
        <article className="card">
          <h2>Edit RAG Source</h2>
          <p className="error-text">Source id must be a positive integer.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="stack" aria-label="Edit RAG source">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Edit RAG Source</h2>
            <p>Update source configuration and schedule settings.</p>
          </div>
          <div className="table-actions">
            <Link to={`/rag/sources/${parsedSourceId}`} className="btn-link btn-secondary">Back to Source</Link>
          </div>
        </div>
        {state.loading ? <p>Loading source edit metadata...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <p className="toolbar-meta">
            GitHub: {payload?.github_connected ? 'connected' : 'not connected'} | Google Drive: {payload?.google_drive_connected ? 'connected' : 'not connected'}
          </p>
        ) : null}
      </article>

      <article className="card">
        <form className="form-grid" onSubmit={handleSubmit}>
          <label>
            Name
            <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required />
          </label>
          <label>
            Kind
            <select value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value }))}>
              <option value="local">Local</option>
              <option value="github">GitHub</option>
              <option value="google_drive">Google Drive</option>
            </select>
          </label>

          {form.kind === 'local' ? (
            <label>
              Local path
              <input value={form.localPath} onChange={(event) => setForm((current) => ({ ...current, localPath: event.target.value }))} />
            </label>
          ) : null}

          {form.kind === 'github' ? (
            <>
              <label>
                GitHub repo
                <input value={form.gitRepo} onChange={(event) => setForm((current) => ({ ...current, gitRepo: event.target.value }))} />
              </label>
              <label>
                Git branch
                <input value={form.gitBranch} onChange={(event) => setForm((current) => ({ ...current, gitBranch: event.target.value }))} />
              </label>
            </>
          ) : null}

          {form.kind === 'google_drive' ? (
            <label>
              Google Drive folder ID
              <input value={form.driveFolderId} onChange={(event) => setForm((current) => ({ ...current, driveFolderId: event.target.value }))} />
            </label>
          ) : null}

          <div className="key-value-grid">
            <label>
              Schedule value
              <input type="number" min={1} value={form.indexScheduleValue} onChange={(event) => setForm((current) => ({ ...current, indexScheduleValue: event.target.value }))} />
            </label>
            <label>
              Schedule unit
              <select value={form.indexScheduleUnit} onChange={(event) => setForm((current) => ({ ...current, indexScheduleUnit: event.target.value }))}>
                <option value="">Not scheduled</option>
                <option value="minutes">Minutes</option>
                <option value="hours">Hours</option>
                <option value="days">Days</option>
                <option value="weeks">Weeks</option>
              </select>
            </label>
            <label>
              Index mode
              <select value={form.indexScheduleMode} onChange={(event) => setForm((current) => ({ ...current, indexScheduleMode: event.target.value }))}>
                <option value="fresh">Fresh</option>
                <option value="delta">Delta</option>
              </select>
            </label>
          </div>

          {submitError ? <p className="error-text">{submitError}</p> : null}
          <div className="table-actions">
            <button type="submit" className="btn-link" disabled={busy}>{busy ? 'Saving...' : 'Save Source'}</button>
          </div>
        </form>
      </article>
    </section>
  )
}

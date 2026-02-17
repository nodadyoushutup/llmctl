import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createRagSource, getRagSourceMeta } from '../lib/studioApi'

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

function buildInitialForm() {
  return {
    name: '',
    kind: 'local',
    localPath: '',
    gitRepo: '',
    gitBranch: 'main',
    driveFolderId: '',
    indexScheduleValue: '',
    indexScheduleUnit: '',
    indexScheduleMode: 'fresh',
  }
}

export default function RagSourceNewPage() {
  const navigate = useNavigate()
  const [metaState, setMetaState] = useState({ loading: true, payload: null, error: '' })
  const [form, setForm] = useState(buildInitialForm)
  const [submitError, setSubmitError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getRagSourceMeta()
        if (active) {
          setMetaState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setMetaState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load source form metadata.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitError('')
    setBusy(true)
    try {
      const result = await createRagSource(form)
      const sourceId = Number.parseInt(String(result?.source?.id ?? ''), 10)
      if (Number.isInteger(sourceId) && sourceId > 0) {
        navigate(`/rag/sources/${sourceId}`)
        return
      }
      navigate('/rag/sources')
    } catch (error) {
      setSubmitError(errorMessage(error, 'Failed to create source.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = metaState.payload && typeof metaState.payload === 'object' ? metaState.payload : null

  return (
    <section className="stack" aria-label="New RAG source">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>New RAG Source</h2>
            <p>Configure a source and optional indexing schedule.</p>
          </div>
          <div className="table-actions">
            <Link to="/rag/sources" className="btn-link btn-secondary">Back to Sources</Link>
          </div>
        </div>
        {metaState.loading ? <p>Loading source form metadata...</p> : null}
        {metaState.error ? <p className="error-text">{metaState.error}</p> : null}
        {!metaState.loading && !metaState.error ? (
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
              <input value={form.localPath} onChange={(event) => setForm((current) => ({ ...current, localPath: event.target.value }))} placeholder="/workspace/docs" />
            </label>
          ) : null}

          {form.kind === 'github' ? (
            <>
              <label>
                GitHub repo
                <input value={form.gitRepo} onChange={(event) => setForm((current) => ({ ...current, gitRepo: event.target.value }))} placeholder="org/repo" />
              </label>
              <label>
                Git branch
                <input value={form.gitBranch} onChange={(event) => setForm((current) => ({ ...current, gitBranch: event.target.value }))} placeholder="main" />
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
            <button type="submit" className="btn-link" disabled={busy}>{busy ? 'Creating...' : 'Create Source'}</button>
          </div>
        </form>
      </article>
    </section>
  )
}

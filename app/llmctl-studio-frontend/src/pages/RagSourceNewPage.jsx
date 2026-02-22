import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import {
  createRagSource,
  getRagSourceMeta,
  verifyRagGoogleDriveConnection,
} from '../lib/studioApi'

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
  const search = typeof window !== 'undefined' ? window.location.search : ''
  const initialKind = String(new URLSearchParams(search).get('kind') || '').trim().toLowerCase()
  const kind = initialKind === 'github' || initialKind === 'google_drive' ? initialKind : 'local'
  return {
    name: '',
    kind,
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
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [busy, setBusy] = useState(false)
  const [verifyBusy, setVerifyBusy] = useState(false)

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
    setActionError('')
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
      setActionError(errorMessage(error, 'Failed to create source.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyGoogleDrive() {
    const folderId = String(form.driveFolderId || '').trim()
    setActionError('')
    setActionInfo('')
    if (!folderId) {
      setActionError('Google Drive folder ID is required for verification.')
      return
    }

    setVerifyBusy(true)
    try {
      const payload = await verifyRagGoogleDriveConnection({ folderId })
      const folderName = String(payload?.folder_name || '').trim()
      const serviceAccountEmail = String(payload?.service_account_email || '').trim()
      const segments = ['Google Drive folder access verified.']
      if (folderName) {
        segments.push(`Folder: ${folderName}.`)
      }
      if (serviceAccountEmail) {
        segments.push(`Service account: ${serviceAccountEmail}.`)
      }
      setActionInfo(segments.join(' '))
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to verify Google Drive connection.'))
    } finally {
      setVerifyBusy(false)
    }
  }

  const payload = metaState.payload && typeof metaState.payload === 'object' ? metaState.payload : null

  return (
    <section className="stack" aria-label="New RAG source">
      <article className="card">
        <PanelHeader
          title="New RAG Source"
          actions={(
            <div className="table-actions">
              <Link to="/rag/sources" className="btn-link btn-secondary">Back to Sources</Link>
            </div>
          )}
        />
        <p className="muted">Configure a source and optional indexing schedule.</p>
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
            <>
              <label>
                Google Drive folder ID
                <input value={form.driveFolderId} onChange={(event) => setForm((current) => ({ ...current, driveFolderId: event.target.value }))} />
              </label>
              <div className="table-actions">
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  disabled={busy || verifyBusy}
                  onClick={handleVerifyGoogleDrive}
                >
                  {verifyBusy ? 'Verifying...' : 'Verify Connection'}
                </button>
              </div>
            </>
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

          <div className="table-actions">
            <button type="submit" className="btn-link" disabled={busy}>{busy ? 'Creating...' : 'Create Source'}</button>
          </div>
        </form>
      </article>
    </section>
  )
}

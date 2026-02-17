import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import {
  deleteRagSource,
  getRagSource,
  quickDeltaIndexRagSource,
  quickIndexRagSource,
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

export default function RagSourceDetailPage() {
  const navigate = useNavigate()
  const { sourceId } = useParams()
  const parsedSourceId = Number.parseInt(String(sourceId ?? ''), 10)
  const invalidId = !Number.isInteger(parsedSourceId) || parsedSourceId <= 0

  const [state, setState] = useState({ loading: !invalidId, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    if (invalidId) {
      return
    }
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getRagSource(parsedSourceId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load source detail.') })
    }
  }, [invalidId, parsedSourceId])

  useEffect(() => {
    if (invalidId) {
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const payload = await getRagSource(parsedSourceId)
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load source detail.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [invalidId, parsedSourceId])

  async function handleDelete() {
    if (invalidId) {
      return
    }
    if (!window.confirm('Delete this source?')) {
      return
    }
    setActionError('')
    setActionInfo('')
    setBusy(true)
    try {
      await deleteRagSource(parsedSourceId)
      navigate('/rag/sources')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete source.'))
    } finally {
      setBusy(false)
    }
  }

  async function queueQuick(mode) {
    if (invalidId) {
      return
    }
    setActionError('')
    setActionInfo('')
    setBusy(true)
    try {
      if (mode === 'delta') {
        await quickDeltaIndexRagSource(parsedSourceId)
        setActionInfo('Queued quick delta index run.')
      } else {
        await quickIndexRagSource(parsedSourceId)
        setActionInfo('Queued quick index run.')
      }
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to queue quick run.'))
    } finally {
      setBusy(false)
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const source = payload && payload.source && typeof payload.source === 'object' ? payload.source : null
  const fileTypes = payload && Array.isArray(payload.file_types) ? payload.file_types : []

  if (invalidId) {
    return (
      <section className="stack" aria-label="RAG source detail">
        <article className="card">
          <h2>RAG Source Detail</h2>
          <p className="error-text">Source id must be a positive integer.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="stack" aria-label="RAG source detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>RAG Source Detail</h2>
            <p>Native React replacement for `/rag/sources/:sourceId` detail, status, quick index, and delete actions.</p>
          </div>
          <div className="table-actions">
            <Link to="/rag/sources" className="btn-link btn-secondary">Back to Sources</Link>
            <Link to={`/rag/sources/${parsedSourceId}/edit`} className="btn-link btn-secondary">Edit</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
            <button type="button" className="btn-link" disabled={busy} onClick={() => queueQuick('fresh')}>Quick Index</button>
            <button type="button" className="btn-link" disabled={busy} onClick={() => queueQuick('delta')}>Quick Delta</button>
            <button type="button" className="btn-link" disabled={busy} onClick={handleDelete}>Delete</button>
          </div>
        </div>
        {state.loading ? <p>Loading source detail...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
      </article>

      {!state.loading && !state.error && source ? (
        <article className="card">
          <h2>{source.name || `Source ${parsedSourceId}`}</h2>
          <div className="key-value-grid">
            <p><strong>Kind:</strong> {source.kind || '-'}</p>
            <p><strong>Status:</strong> {source.status || '-'}</p>
            <p><strong>Collection:</strong> {source.collection || '-'}</p>
            <p><strong>Location:</strong> {source.location || '-'}</p>
            <p><strong>Schedule:</strong> {source.schedule_text || '-'}</p>
            <p><strong>Last indexed:</strong> {source.last_indexed_at || '-'}</p>
            <p><strong>Next index:</strong> {source.next_index_at || '-'}</p>
          </div>
          {source.last_error ? <p className="error-text">{source.last_error}</p> : null}
        </article>
      ) : null}

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Indexed File Types</h2>
          {fileTypes.length === 0 ? <p>No indexed file type metrics.</p> : null}
          {fileTypes.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {fileTypes.map((item, index) => (
                    <tr key={`${item?.type || 'type'}-${index}`}>
                      <td>{item?.type || '-'}</td>
                      <td>{item?.count ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

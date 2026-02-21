import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { deleteChromaCollection, getChromaCollection } from '../lib/studioApi'

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

export default function ChromaCollectionDetailPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const collectionName = useMemo(() => String(searchParams.get('name') || '').trim(), [searchParams])
  const missingName = collectionName.length === 0

  const [state, setState] = useState({ loading: !missingName, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')

  const refresh = useCallback(async () => {
    if (missingName) {
      return
    }
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getChromaCollection(collectionName)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load collection detail.') })
    }
  }, [collectionName, missingName])

  useEffect(() => {
    if (missingName) {
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const payload = await getChromaCollection(collectionName)
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load collection detail.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [collectionName, missingName])

  async function handleDelete() {
    if (missingName) {
      return
    }
    if (!window.confirm(`Delete collection '${collectionName}'?`)) {
      return
    }
    setActionError('')
    try {
      await deleteChromaCollection(collectionName, { next: 'detail' })
      navigate('/chroma/collections')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete collection.'))
    }
  }

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null

  if (missingName) {
    return (
      <section className="stack" aria-label="Chroma collection detail">
        <article className="card">
          <h2>Chroma Collection Detail</h2>
          <p className="error-text">Collection name is required.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="stack" aria-label="Chroma collection detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Chroma Collection Detail</h2>
            <p>Collection metadata and delete controls.</p>
          </div>
          <div className="table-actions">
            <Link to="/chroma/collections" className="btn-link btn-secondary">Back to Collections</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
            <button type="button" className="btn-link" onClick={handleDelete}>
              <i className="fa-solid fa-trash" aria-hidden="true" />
              Delete
            </button>
          </div>
        </div>
        {state.loading ? <p>Loading collection...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
      </article>

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>{payload?.collection_name || collectionName}</h2>
          <div className="key-value-grid">
            <p><strong>Count:</strong> {payload?.collection_count ?? '-'}</p>
            <p><strong>Host:</strong> {payload?.chroma_host || '-'}</p>
            <p><strong>Port:</strong> {payload?.chroma_port || '-'}</p>
            <p><strong>SSL:</strong> {payload?.chroma_ssl || '-'}</p>
          </div>
          <pre className="code-block">{payload?.collection_metadata_json || '{}'}</pre>
        </article>
      ) : null}
    </section>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteChromaCollection, getChromaCollections } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

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

export default function ChromaCollectionsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(20)
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busyByName, setBusyByName] = useState({})

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getChromaCollections({ page, perPage })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Chroma collections.') })
    }
  }, [page, perPage])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getChromaCollections({ page, perPage })
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Chroma collections.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [page, perPage])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const collections = payload && Array.isArray(payload.collections) ? payload.collections : []
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object' ? payload.pagination : null

  function setBusy(collectionName, busy) {
    setBusyByName((current) => {
      const next = { ...current }
      if (busy) {
        next[collectionName] = true
      } else {
        delete next[collectionName]
      }
      return next
    })
  }

  async function handleDelete(collectionName) {
    if (!window.confirm(`Delete collection '${collectionName}'?`)) {
      return
    }
    setActionError('')
    setBusy(collectionName, true)
    try {
      await deleteChromaCollection(collectionName, { next: 'list' })
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete collection.'))
    } finally {
      setBusy(collectionName, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Chroma collections">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Chroma Collections</h2>
            <p>Browse collections, inspect metadata, and remove stale datasets.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/integrations/chroma" className="btn-link btn-secondary">Chroma Settings</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            <label>
              Per page
              <select value={perPage} onChange={(event) => setPerPage(Number.parseInt(event.target.value, 10) || 20)}>
                {[10, 20, 50, 100].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
        {state.loading ? <p>Loading collections...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.chroma_error ? <p className="error-text">{String(payload.chroma_error)}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
      </article>

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Collections</h2>
          {collections.length === 0 ? <p>No collections found.</p> : null}
          {collections.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Count</th>
                    <th>Metadata</th>
                    <th className="table-actions-cell">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {collections.map((collection) => {
                    const name = String(collection?.name || '').trim()
                    const href = `/chroma/collections/detail?name=${encodeURIComponent(name)}`
                    return (
                      <tr key={name} className="table-row-link" data-href={href} onClick={(event) => handleRowClick(event, href)}>
                        <td><Link to={href}>{name || '-'}</Link></td>
                        <td>{collection?.count ?? '-'}</td>
                        <td><code>{collection?.metadata_preview || '{}'}</code></td>
                        <td className="table-actions-cell">
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete collection"
                            title="Delete collection"
                            disabled={Boolean(busyByName[name])}
                            onClick={() => handleDelete(name)}
                          >
                            <ActionIcon name="trash" />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          {pagination ? (
            <div className="toolbar">
              <div className="toolbar-group">
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={Number(pagination.page || 1) <= 1}
                >
                  Previous
                </button>
                <span className="toolbar-meta">Page {pagination.page || 1} of {pagination.total_pages || 1}</span>
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  onClick={() => setPage((current) => current + 1)}
                  disabled={Number(pagination.page || 1) >= Number(pagination.total_pages || 1)}
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

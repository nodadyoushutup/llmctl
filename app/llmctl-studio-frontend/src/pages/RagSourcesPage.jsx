import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import {
  deleteRagSource,
  getRagSources,
  quickDeltaIndexRagSource,
  quickIndexRagSource,
} from '../lib/studioApi'
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

export default function RagSourcesPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getRagSources()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load RAG sources.'),
      }))
    }
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getRagSources()
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load RAG sources.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const sources = payload && Array.isArray(payload.sources) ? payload.sources : []

  function setBusy(sourceId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[sourceId] = true
      } else {
        delete next[sourceId]
      }
      return next
    })
  }

  async function handleDelete(sourceId) {
    if (!window.confirm('Delete this RAG source?')) {
      return
    }
    setActionError('')
    setActionInfo('')
    setBusy(sourceId, true)
    try {
      await deleteRagSource(sourceId)
      setActionInfo('Source deleted.')
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete source.'))
    } finally {
      setBusy(sourceId, false)
    }
  }

  async function handleQuickRun(sourceId, mode) {
    setActionError('')
    setActionInfo('')
    setBusy(sourceId, true)
    try {
      if (mode === 'delta') {
        await quickDeltaIndexRagSource(sourceId)
        setActionInfo('Queued quick delta index run.')
      } else {
        await quickIndexRagSource(sourceId)
        setActionInfo('Queued quick index run.')
      }
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to queue quick run.'))
    } finally {
      setBusy(sourceId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="RAG sources">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>RAG Sources</h2>
            <p>Native React replacement for `/rag/sources*` list, detail navigation, and quick indexing flows.</p>
          </div>
          <div className="table-actions">
            <Link to="/rag/chat" className="btn-link btn-secondary">RAG Chat</Link>
            <Link to="/rag/sources/new" className="btn-link">New Source</Link>
          </div>
        </div>
        {state.loading ? <p>Loading RAG sources...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
      </article>

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Sources</h2>
          {sources.length === 0 ? <p>No sources found.</p> : null}
          {sources.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Kind</th>
                    <th>Status</th>
                    <th>Collection</th>
                    <th>Schedule</th>
                    <th>Indexed</th>
                    <th className="table-actions-cell">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => {
                    const sourceId = Number.parseInt(String(source.id ?? ''), 10)
                    const href = `/rag/sources/${sourceId}`
                    const busy = Boolean(busyById[sourceId])
                    return (
                      <tr key={sourceId} className="table-row-link" data-href={href} onClick={(event) => handleRowClick(event, href)}>
                        <td><Link to={href}>{source.name || `Source ${sourceId}`}</Link></td>
                        <td>{source.kind || '-'}</td>
                        <td>{source.status || '-'}</td>
                        <td>{source.collection || '-'}</td>
                        <td>{source.schedule_text || '-'}</td>
                        <td>{source.indexed_file_count ?? 0} files / {source.indexed_chunk_count ?? 0} chunks</td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            <button type="button" className="icon-button" title="Quick index" aria-label="Quick index" disabled={busy} onClick={() => handleQuickRun(sourceId, 'fresh')}>
                              <ActionIcon name="play" />
                            </button>
                            <button type="button" className="icon-button" title="Quick delta index" aria-label="Quick delta index" disabled={busy} onClick={() => handleQuickRun(sourceId, 'delta')}>
                              D
                            </button>
                            <Link to={`/rag/sources/${sourceId}/edit`} className="icon-button" title="Edit source" aria-label="Edit source">
                              <ActionIcon name="edit" />
                            </Link>
                            <button type="button" className="icon-button icon-button-danger" title="Delete source" aria-label="Delete source" disabled={busy} onClick={() => handleDelete(sourceId)}>
                              <ActionIcon name="trash" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

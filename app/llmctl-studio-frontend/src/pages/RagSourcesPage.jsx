import { useCallback, useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import TableListEmptyState from '../components/TableListEmptyState'
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

function sourceKindMeta(kind) {
  const normalized = String(kind || '').toLowerCase()
  if (normalized === 'github') {
    return { iconClass: 'fa-brands fa-github', label: 'GitHub source' }
  }
  if (normalized === 'google_drive') {
    return { iconClass: 'fa-brands fa-google-drive', label: 'Google Drive source' }
  }
  if (normalized === 'local') {
    return { iconClass: 'fa-solid fa-folder-open', label: 'Local folder source' }
  }
  return { iconClass: 'fa-solid fa-database', label: 'Source kind' }
}

export default function RagSourcesPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
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
    <section className="stack workflow-fixed-page" aria-label="RAG sources">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="RAG Sources"
          actions={(
            <Link to="/rag/sources/new" className="icon-button" aria-label="New source" title="New source">
              <ActionIcon name="plus" />
            </Link>
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <p className="panel-header-copy">
            Configure retrieval sources and run quick index operations.
          </p>
          {state.loading ? <p>Loading RAG sources...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {!state.loading && !state.error ? (
            <div className="workflow-list-table-shell">
              {sources.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Name</th>
                        <th>Location</th>
                        <th>Schedule</th>
                        <th>Last indexed</th>
                        <th>Status</th>
                        <th className="table-actions-cell">Index</th>
                        <th className="table-actions-cell">Delta</th>
                        <th className="table-actions-cell">Edit</th>
                        <th className="table-actions-cell">Delete</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sources.map((source) => {
                        const sourceId = Number.parseInt(String(source.id ?? ''), 10)
                        const href = `/rag/sources/${sourceId}`
                        const busy = Boolean(busyById[sourceId])
                        const kindMeta = sourceKindMeta(source.kind)
                        return (
                          <tr key={sourceId} className="table-row-link" data-href={href} onClick={(event) => handleRowClick(event, href)}>
                            <td className="source-kind-cell">
                              <span className="source-kind-icon" role="img" aria-label={kindMeta.label} title={kindMeta.label}>
                                <i className={kindMeta.iconClass} aria-hidden="true" />
                              </span>
                            </td>
                            <td><Link to={href}>{source.name || `Source ${sourceId}`}</Link></td>
                            <td className="mono">{source.location || source.local_path || source.git_repo || source.drive_folder_id || '-'}</td>
                            <td>{source.schedule_text || '-'}</td>
                            <td>{source.last_indexed_at || '-'}</td>
                            <td>{source.status || '-'}</td>
                            <td className="table-actions-cell">
                              <button type="button" className="icon-button" title="Quick index" aria-label="Quick index" disabled={busy} onClick={() => handleQuickRun(sourceId, 'fresh')}>
                                <ActionIcon name="play" />
                              </button>
                            </td>
                            <td className="table-actions-cell">
                              <button type="button" className="icon-button" title="Quick delta index" aria-label="Quick delta index" disabled={busy} onClick={() => handleQuickRun(sourceId, 'delta')}>
                                <i className="fa-solid fa-code-branch" aria-hidden="true" />
                              </button>
                            </td>
                            <td className="table-actions-cell">
                              <Link to={`/rag/sources/${sourceId}/edit`} className="icon-button" title="Edit source" aria-label="Edit source">
                                <ActionIcon name="edit" />
                              </Link>
                            </td>
                            <td className="table-actions-cell">
                              <button type="button" className="icon-button icon-button-danger" title="Delete source" aria-label="Delete source" disabled={busy} onClick={() => handleDelete(sourceId)}>
                                <ActionIcon name="trash" />
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <TableListEmptyState message="No sources found." />
              )}
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

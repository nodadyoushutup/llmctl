import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteFlowchart, getFlowcharts } from '../lib/studioApi'
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

export default function FlowchartsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getFlowcharts()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load flowcharts.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const flowcharts = payload && Array.isArray(payload.flowcharts) ? payload.flowcharts : []

  function setBusy(flowchartId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[flowchartId] = true
      } else {
        delete next[flowchartId]
      }
      return next
    })
  }

  async function handleDelete(flowchartId) {
    if (!window.confirm('Delete this flowchart?')) {
      return
    }
    setActionError('')
    setBusy(flowchartId, true)
    try {
      await deleteFlowchart(flowchartId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete flowchart.'))
    } finally {
      setBusy(flowchartId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Flowcharts">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Flowcharts</h2>
            <p>Native React replacement for `/flowcharts` list and row actions.</p>
          </div>
          <div className="table-actions">
            <Link to="/flowcharts/new" className="btn-link">New Flowchart</Link>
          </div>
        </div>
        {state.loading ? <p>Loading flowcharts...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
          <p className="toolbar-meta">Total flowcharts: {flowcharts.length}</p>
        ) : null}
        {!state.loading && !state.error && flowcharts.length === 0 ? <p>No flowcharts yet.</p> : null}
        {!state.loading && !state.error && flowcharts.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Flowchart</th>
                  <th>Description</th>
                  <th>Nodes</th>
                  <th>Edges</th>
                  <th>Runs</th>
                  <th>Updated</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {flowcharts.map((flowchart) => {
                  const href = `/flowcharts/${flowchart.id}`
                  const busy = Boolean(busyById[flowchart.id])
                  return (
                    <tr
                      key={flowchart.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{flowchart.name || `Flowchart ${flowchart.id}`}</Link>
                      </td>
                      <td>{flowchart.description || '-'}</td>
                      <td>{flowchart.node_count ?? 0}</td>
                      <td>{flowchart.edge_count ?? 0}</td>
                      <td>{flowchart.run_count ?? 0}</td>
                      <td>{flowchart.updated_at || '-'}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <Link
                            to={`/flowcharts/${flowchart.id}/edit`}
                            className="icon-button"
                            aria-label="Edit flowchart"
                            title="Edit flowchart"
                          >
                            <ActionIcon name="edit" />
                          </Link>
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete flowchart"
                            title="Delete flowchart"
                            disabled={busy}
                            onClick={() => handleDelete(flowchart.id)}
                          >
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
    </section>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import PanelHeader from '../components/PanelHeader'
import TableListEmptyState from '../components/TableListEmptyState'
import { HttpError } from '../lib/httpClient'
import { deleteRun, getRuns, stopAgent } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

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

function runStatusMeta(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'starting') {
    return { className: 'status-chip status-running', label: 'active' }
  }
  if (normalized === 'stopping') {
    return { className: 'status-chip status-warning', label: 'stopping' }
  }
  if (normalized === 'error' || normalized === 'failed') {
    return { className: 'status-chip status-failed', label: 'error' }
  }
  return { className: 'status-chip status-idle', label: 'off' }
}

function isRunActive(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'running' || normalized === 'starting' || normalized === 'stopping'
}

export default function RunsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 10)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getRuns({ page, perPage })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load autoruns.'),
      }))
    }
  }, [page, perPage])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const runs = payload && Array.isArray(payload.runs) ? payload.runs : []
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object'
    ? payload.pagination
    : null
  const totalPages = Number.isInteger(pagination?.total_pages) && pagination.total_pages > 0
    ? pagination.total_pages
    : 1
  const totalRuns = Number.isInteger(pagination?.total_runs) && pagination.total_runs >= 0
    ? pagination.total_runs
    : 0
  const perPageOptions = Array.isArray(pagination?.per_page_options) && pagination.per_page_options.length > 0
    ? pagination.per_page_options
    : [10, 25, 50]
  const paginationItems = Array.isArray(pagination?.items) ? pagination.items : []

  function updateParams(nextParams) {
    const updated = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(nextParams)) {
      if (value == null || value === '') {
        updated.delete(key)
      } else {
        updated.set(key, String(value))
      }
    }
    setSearchParams(updated)
  }

  function setBusy(runId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[runId] = true
      } else {
        delete next[runId]
      }
      return next
    })
  }

  async function handleDisableAutorun(run) {
    if (!run || !run.agent_id) {
      return
    }
    setActionError('')
    setBusy(run.id, true)
    try {
      await stopAgent(run.agent_id)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to disable autorun.'))
    } finally {
      setBusy(run.id, false)
    }
  }

  async function handleDelete(runId) {
    if (!window.confirm('Delete this autorun?')) {
      return
    }
    setActionError('')
    setBusy(runId, true)
    try {
      await deleteRun(runId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete autorun.'))
    } finally {
      setBusy(runId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack workflow-fixed-page" aria-label="Runs">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="Autoruns"
          actionsClassName="workflow-list-panel-header-actions"
          actions={(
            <div className="pagination-bar-actions">
              <HeaderPagination
                ariaLabel="Autoruns pages"
                canGoPrev={page > 1}
                canGoNext={page < totalPages}
                onPrev={() => updateParams({ page: page - 1 })}
                onNext={() => updateParams({ page: page + 1 })}
                currentPage={page}
                pageItems={paginationItems}
                onPageSelect={(itemPage) => updateParams({ page: itemPage })}
              />
              <div className="pagination-size">
                <label htmlFor="runs-per-page">Rows per page</label>
                <select
                  id="runs-per-page"
                  value={String(perPage)}
                  onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
                >
                  {perPageOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <p className="muted">
            Autoruns are created automatically when you enable autorun on an agent.
          </p>
          {state.loading ? <p>Loading autoruns...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {!state.loading && !state.error ? (
            <p className="toolbar-meta">Total autoruns: {totalRuns}</p>
          ) : null}
          {!state.loading && !state.error ? (
            <div className="workflow-list-table-shell">
              {runs.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Autorun</th>
                        <th>Agent</th>
                        <th>Status</th>
                        <th>Autorun task</th>
                        <th>Started</th>
                        <th>Finished</th>
                        <th className="table-actions-cell">Stop</th>
                        <th className="table-actions-cell">Delete</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => {
                        const href = `/runs/${run.id}`
                        const active = isRunActive(run.status)
                        const busy = Boolean(busyById[run.id])
                        const taskId = run.task_id || run.last_run_task_id || '-'
                        const status = runStatusMeta(run.status)
                        return (
                          <tr
                            key={run.id}
                            className="table-row-link"
                            data-href={href}
                            onClick={(event) => handleRowClick(event, href)}
                          >
                            <td>
                              <Link to={href}>{run.name || `Autorun ${run.id}`}</Link>
                            </td>
                            <td>
                              {run.agent_id ? <Link to={`/agents/${run.agent_id}`}>{run.agent_name || `Agent ${run.agent_id}`}</Link> : '-'}
                            </td>
                            <td>
                              <span className={status.className}>{status.label}</span>
                            </td>
                            <td className="muted" style={{ fontSize: '12px' }}>{taskId}</td>
                            <td className="muted">{run.last_started_at || '-'}</td>
                            <td className="muted">{run.last_stopped_at || '-'}</td>
                            <td className="table-actions-cell">
                              <div className="table-actions">
                                {active ? (
                                  <button
                                    type="button"
                                    className="icon-button"
                                    aria-label="Disable autorun"
                                    title="Disable autorun"
                                    disabled={busy}
                                    onClick={() => handleDisableAutorun(run)}
                                  >
                                    <ActionIcon name="stop" />
                                  </button>
                                ) : <span className="muted">-</span>}
                              </div>
                            </td>
                            <td className="table-actions-cell">
                              <div className="table-actions">
                                <button
                                  type="button"
                                  className="icon-button icon-button-danger"
                                  aria-label="Delete autorun"
                                  title="Delete autorun"
                                  disabled={busy}
                                  onClick={() => handleDelete(run.id)}
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
              ) : (
                <TableListEmptyState message="No autoruns recorded yet." />
              )}
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

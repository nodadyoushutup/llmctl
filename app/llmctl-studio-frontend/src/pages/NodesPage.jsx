import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import PanelHeader from '../components/PanelHeader'
import TableListEmptyState from '../components/TableListEmptyState'
import { HttpError } from '../lib/httpClient'
import { cancelNode, deleteNode, getNodes } from '../lib/studioApi'
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

function nodeStatusMeta(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running') {
    return { className: 'status-chip status-running', label: 'running' }
  }
  if (normalized === 'queued' || normalized === 'pending' || normalized === 'starting') {
    return { className: 'status-chip status-warning', label: normalized }
  }
  if (normalized === 'succeeded' || normalized === 'completed') {
    return { className: 'status-chip status-running', label: normalized }
  }
  if (normalized === 'failed' || normalized === 'error') {
    return { className: 'status-chip status-failed', label: normalized }
  }
  return { className: 'status-chip status-idle', label: normalized || 'idle' }
}

function canCancel(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'queued' || normalized === 'running' || normalized === 'pending'
}

function shouldAutoRefresh(tasks) {
  return tasks.some((task) => canCancel(task?.status))
}

export default function NodesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 10)
  const agentId = searchParams.get('agent_id') || ''
  const nodeType = searchParams.get('node_type') || ''
  const status = searchParams.get('status') || ''
  const flowchartNodeIdRaw = searchParams.get('flowchart_node_id') || ''
  const flowchartNodeId = parsePositiveInt(flowchartNodeIdRaw, 0)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getNodes({
        page,
        perPage,
        agentId,
        nodeType,
        status,
        flowchartNodeId: flowchartNodeId > 0 ? flowchartNodeId : '',
      })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load nodes.'),
      }))
    }
  }, [agentId, flowchartNodeId, nodeType, page, perPage, status])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const tasks = useMemo(
    () => (payload && Array.isArray(payload.tasks) ? payload.tasks : []),
    [payload],
  )
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object'
    ? payload.pagination
    : null
  const filterOptions = payload && payload.filter_options && typeof payload.filter_options === 'object'
    ? payload.filter_options
    : {}
  const filters = payload && payload.filters && typeof payload.filters === 'object'
    ? payload.filters
    : {}
  const resolvedFlowchartNodeId = Number.isInteger(filters.flowchart_node_id) && filters.flowchart_node_id > 0
    ? String(filters.flowchart_node_id)
    : (flowchartNodeId > 0 ? String(flowchartNodeId) : '')

  const totalPages = Number.isInteger(pagination?.total_pages) && pagination.total_pages > 0
    ? pagination.total_pages
    : 1
  const totalTasks = Number.isInteger(pagination?.total_tasks) && pagination.total_tasks >= 0
    ? pagination.total_tasks
    : 0
  const perPageOptions = Array.isArray(pagination?.per_page_options) && pagination.per_page_options.length > 0
    ? pagination.per_page_options
    : [10, 25, 50]
  const paginationItems = Array.isArray(pagination?.items) ? pagination.items : []

  const autoRefreshEnabled = useMemo(() => shouldAutoRefresh(tasks), [tasks])

  useEffect(() => {
    if (!autoRefreshEnabled) {
      return
    }
    const intervalId = window.setInterval(() => {
      refresh({ silent: true })
    }, 5000)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [autoRefreshEnabled, refresh])

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

  function setBusy(taskId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[taskId] = true
      } else {
        delete next[taskId]
      }
      return next
    })
  }

  async function handleCancel(taskId) {
    setActionError('')
    setBusy(taskId, true)
    try {
      await cancelNode(taskId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to cancel node.'))
    } finally {
      setBusy(taskId, false)
    }
  }

  async function handleDelete(taskId) {
    if (!window.confirm('Delete this node?')) {
      return
    }
    setActionError('')
    setBusy(taskId, true)
    try {
      await deleteNode(taskId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete node.'))
    } finally {
      setBusy(taskId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  const agentFilterOptions = Array.isArray(filterOptions.agent) ? filterOptions.agent : []
  const nodeTypeOptions = Array.isArray(filterOptions.node_type) ? filterOptions.node_type : []
  const statusOptions = Array.isArray(filterOptions.status) ? filterOptions.status : []

  return (
    <section className="stack workflow-fixed-page" aria-label="Nodes">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="Nodes"
          actionsClassName="workflow-list-panel-header-actions"
          actions={(
            <HeaderPagination
              ariaLabel="Nodes pages"
              canGoPrev={page > 1}
              canGoNext={page < totalPages}
              onPrev={() => updateParams({ page: page - 1 })}
              onNext={() => updateParams({ page: page + 1 })}
              currentPage={page}
              pageItems={paginationItems}
              onPageSelect={(itemPage) => updateParams({ page: itemPage })}
            />
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <div className="toolbar toolbar-wrap">
            <div className="toolbar-group">
              <label htmlFor="filter-agent">Agent</label>
              <select
                id="filter-agent"
                value={String(filters.agent_id ?? agentId)}
                onChange={(event) => updateParams({ agent_id: event.target.value, page: 1 })}
              >
                <option value="">All agents</option>
                {agentFilterOptions.map((option) => (
                  <option key={`agent-${option.value}`} value={String(option.value)}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="toolbar-group">
              <label htmlFor="filter-node-type">Type</label>
              <select
                id="filter-node-type"
                value={String(filters.node_type ?? nodeType)}
                onChange={(event) => updateParams({ node_type: event.target.value, page: 1 })}
              >
                <option value="">All types</option>
                {nodeTypeOptions.map((option) => (
                  <option key={`type-${option.value}`} value={String(option.value)}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="toolbar-group">
              <label htmlFor="filter-status">Status</label>
              <select
                id="filter-status"
                value={String(filters.status ?? status)}
                onChange={(event) => updateParams({ status: event.target.value, page: 1 })}
              >
                <option value="">All statuses</option>
                {statusOptions.map((option) => (
                  <option key={`status-${option.value}`} value={String(option.value)}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="toolbar-group">
              <label htmlFor="nodes-per-page">Rows per page</label>
              <select
                id="nodes-per-page"
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
            <div className="toolbar-group">
              <label htmlFor="filter-flowchart-node">Flowchart node</label>
              <input
                id="filter-flowchart-node"
                type="number"
                min="1"
                value={resolvedFlowchartNodeId}
                onChange={(event) => updateParams({ flowchart_node_id: event.target.value, page: 1 })}
                placeholder="Any"
              />
            </div>
          </div>
          {!state.loading && !state.error ? (
            <p className="toolbar-meta">Total nodes: {totalTasks}</p>
          ) : null}
          {state.loading ? <p>Loading nodes...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {autoRefreshEnabled ? (
            <p className="toolbar-meta">Active tasks detected. Refreshing every 5s.</p>
          ) : null}
          {!state.loading && !state.error ? (
            <div className="workflow-list-table-shell">
              {tasks.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Node</th>
                        <th>Agent</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Autorun task</th>
                        <th>Started</th>
                        <th>Finished</th>
                        <th className="table-actions-cell">Cancel</th>
                        <th className="table-actions-cell">Delete</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tasks.map((task) => {
                        const href = `/nodes/${task.id}`
                        const statusMeta = nodeStatusMeta(task.status)
                        const busy = Boolean(busyById[task.id])
                        const allowCancel = canCancel(task.status)
                        return (
                          <tr
                            key={task.id}
                            className="table-row-link"
                            data-href={href}
                            onClick={(event) => handleRowClick(event, href)}
                          >
                            <td>
                              <Link to={href}>{task.node_name || `Node ${task.id}`}</Link>
                              <div className="table-note">#{task.id}</div>
                            </td>
                            <td>{task.agent_name || '-'}</td>
                            <td className="muted">{task.node_type || '-'}</td>
                            <td>
                              <span className={statusMeta.className}>{statusMeta.label}</span>
                            </td>
                            <td className="muted" style={{ fontSize: '12px' }}>{task.run_task_id || '-'}</td>
                            <td className="muted">{task.started_at || '-'}</td>
                            <td className="muted">{task.finished_at || '-'}</td>
                            <td className="table-actions-cell">
                              <div className="table-actions">
                                {allowCancel ? (
                                  <button
                                    type="button"
                                    className="icon-button"
                                    aria-label="Cancel node"
                                    title="Cancel node"
                                    disabled={busy}
                                    onClick={() => handleCancel(task.id)}
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
                                  aria-label="Delete node"
                                  title="Delete node"
                                  disabled={busy}
                                  onClick={() => handleDelete(task.id)}
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
                <TableListEmptyState message="No nodes recorded yet." />
              )}
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

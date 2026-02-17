import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteRun, getRun, stopAgent } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
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
  if (normalized === 'queued' || normalized === 'pending') {
    return { className: 'status-chip status-warning', label: normalized }
  }
  if (normalized === 'succeeded' || normalized === 'completed') {
    return { className: 'status-chip status-success', label: normalized }
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

export default function RunDetailPage() {
  const navigate = useNavigate()
  const { runId } = useParams()
  const parsedRunId = useMemo(() => parseId(runId), [runId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!parsedRunId) {
      setState({ loading: false, payload: null, error: 'Invalid run id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getRun(parsedRunId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load autorun.'),
      }))
    }
  }, [parsedRunId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const run = payload && payload.run && typeof payload.run === 'object' ? payload.run : null
  const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
  const runTasks = payload && Array.isArray(payload.run_tasks) ? payload.run_tasks : []
  const status = runStatusMeta(run?.status)
  const active = isRunActive(run?.status)

  useEffect(() => {
    if (!active) {
      return
    }
    const intervalId = window.setInterval(() => {
      refresh({ silent: true })
    }, 5000)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [active, refresh])

  async function handleDisableAutorun() {
    if (!run || !run.agent_id) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await stopAgent(run.agent_id)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to disable autorun.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!run || !window.confirm('Delete this autorun?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteRun(run.id)
      navigate('/runs')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete autorun.'))
      setBusy(false)
    }
  }

  function handleTaskRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Autorun detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{run ? run.name || `Autorun ${run.id}` : 'Autorun'}</h2>
            <p>Autoruns are created automatically when you enable autorun on the agent.</p>
          </div>
          <div className="table-actions">
            <Link to="/runs" className="btn-link btn-secondary">All Autoruns</Link>
            {run && run.agent_id ? (
              <Link to={`/agents/${run.agent_id}`} className="btn-link btn-secondary">View Agent</Link>
            ) : null}
          </div>
        </div>
        {state.loading ? <p>Loading autorun...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {run ? (
          <div className="stack-sm">
            <div className="table-actions">
              <span className={status.className}>{status.label}</span>
              {active ? (
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Disable autorun"
                  title="Disable autorun"
                  disabled={busy}
                  onClick={handleDisableAutorun}
                >
                  <ActionIcon name="stop" />
                </button>
              ) : null}
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete autorun"
                title="Delete autorun"
                disabled={busy}
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
            </div>
            <dl className="kv-grid">
              <div>
                <dt>Agent</dt>
                <dd>{agent?.name || run.agent_name || '-'}</dd>
              </div>
              <div>
                <dt>Autorun node</dt>
                <dd>{payload?.run_task_id || '-'}</dd>
              </div>
              <div>
                <dt>Mode</dt>
                <dd>{payload?.run_is_forever ? 'forever' : `limit ${run.run_max_loops || 0}`}</dd>
              </div>
              <div>
                <dt>Loops completed</dt>
                <dd>{payload?.loops_completed ?? 0}</dd>
              </div>
              <div>
                <dt>Loops remaining</dt>
                <dd>{payload?.loops_remaining ?? '-'}</dd>
              </div>
              <div>
                <dt>Last started</dt>
                <dd>{run.last_started_at || '-'}</dd>
              </div>
              <div>
                <dt>Last stopped</dt>
                <dd>{run.last_stopped_at || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{run.updated_at || '-'}</dd>
              </div>
            </dl>
            {run.run_end_requested ? (
              <p className="toolbar-meta">End requested. This autorun will stop after the current node run.</p>
            ) : null}
            {active ? (
              <p className="toolbar-meta">Realtime updates active. Timed reload fallback starts only if socket connectivity fails.</p>
            ) : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Node runs</h2>
        {runTasks.length === 0 ? <p>No node runs recorded for this autorun yet.</p> : null}
        {runTasks.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Status</th>
                  <th>Runtime</th>
                  <th>Dispatch / Fallback</th>
                  <th>Started</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {runTasks.map((task) => {
                  const href = `/nodes/${task.id}`
                  const taskStatus = runStatusMeta(task.status)
                  return (
                    <tr
                      key={task.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleTaskRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{task.id}</Link>
                      </td>
                      <td>
                        <span className={taskStatus.className}>{task.status || '-'}</span>
                      </td>
                      <td>
                        <p className="table-note">{task.provider_route || '-'}</p>
                        <p className="table-note">dispatch id: {task.provider_dispatch_id || '-'}</p>
                        <p className="table-note">workspace: {task.workspace_identity || '-'}</p>
                      </td>
                      <td>
                        <p className="table-note">
                          {task.dispatch_status || '-'}
                          {task.dispatch_uncertain ? ' (uncertain)' : ''}
                        </p>
                        {task.fallback_attempted ? (
                          <p className="table-note">fallback: {task.fallback_reason || 'unknown'}</p>
                        ) : null}
                        {task.api_failure_category ? (
                          <p className="table-note">api failure: {task.api_failure_category}</p>
                        ) : null}
                      </td>
                      <td>{task.started_at || '-'}</td>
                      <td>{task.finished_at || '-'}</td>
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

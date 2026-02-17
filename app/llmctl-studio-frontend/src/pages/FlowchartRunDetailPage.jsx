import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import {
  cancelFlowchartRun,
  getFlowchartHistoryRun,
  getFlowchartRun,
} from '../lib/studioApi'
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

function runStatusClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'queued') {
    return 'status-chip status-running'
  }
  if (normalized === 'stopping') {
    return 'status-chip status-warning'
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'status-chip status-failed'
  }
  return 'status-chip status-idle'
}

function isRunActive(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'queued' || normalized === 'running' || normalized === 'stopping'
}

function sourceSummary(sources) {
  if (!Array.isArray(sources) || sources.length === 0) {
    return '-'
  }
  return sources
    .map((source) => {
      const edge = source?.source_edge_id ?? '-'
      const node = source?.source_node_id ?? '-'
      const nodeType = source?.source_node_type ? ` (${source.source_node_type})` : ''
      return `edge ${edge} from node ${node}${nodeType}`
    })
    .join('; ')
}

export default function FlowchartRunDetailPage() {
  const navigate = useNavigate()
  const { flowchartId, runId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])
  const parsedRunId = useMemo(() => parseId(runId), [runId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!parsedRunId) {
      setState({ loading: false, payload: null, error: 'Invalid flowchart run id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = parsedFlowchartId
        ? await getFlowchartHistoryRun(parsedFlowchartId, parsedRunId)
        : await getFlowchartRun(parsedRunId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load flowchart run detail.'),
      }))
    }
  }, [parsedFlowchartId, parsedRunId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const flowchart = payload?.flowchart && typeof payload.flowchart === 'object' ? payload.flowchart : null
  const flowchartRun = payload?.flowchart_run && typeof payload.flowchart_run === 'object'
    ? payload.flowchart_run
    : null
  const nodeRuns = Array.isArray(payload?.node_runs) ? payload.node_runs : []
  const active = isRunActive(flowchartRun?.status)

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

  async function handleStop(force) {
    if (!parsedRunId) {
      return
    }
    if (force && !window.confirm('Force stop this run now?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await cancelFlowchartRun(parsedRunId, { force })
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to stop flowchart run.'))
    } finally {
      setBusy(false)
    }
  }

  function handleNodeRunClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  const resolvedFlowchartId = flowchart?.id || flowchartRun?.flowchart_id || parsedFlowchartId

  return (
    <section className="stack" aria-label="Flowchart run detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{flowchartRun ? `Run ${flowchartRun.id}` : 'Flowchart Run'}</h2>
            <p>Native React replacement for flowchart run detail and run controls.</p>
          </div>
          <div className="table-actions">
            {resolvedFlowchartId ? (
              <Link to={`/flowcharts/${resolvedFlowchartId}`} className="btn-link btn-secondary">Open Flowchart</Link>
            ) : null}
            {resolvedFlowchartId ? (
              <Link to={`/flowcharts/${resolvedFlowchartId}/history`} className="btn-link btn-secondary">Run History</Link>
            ) : null}
            <Link to="/flowcharts" className="btn-link btn-secondary">All Flowcharts</Link>
          </div>
        </div>
        {state.loading ? <p>Loading flowchart run...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {flowchartRun ? (
          <div className="stack-sm">
            <div className="table-actions">
              <span className={runStatusClass(flowchartRun.status)}>{flowchartRun.status || '-'}</span>
              {active ? (
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  disabled={busy}
                  onClick={() => handleStop(false)}
                >
                  Stop After Current Node
                </button>
              ) : null}
              {active ? (
                <button
                  type="button"
                  className="btn-link"
                  disabled={busy}
                  onClick={() => handleStop(true)}
                >
                  Force Stop
                </button>
              ) : null}
            </div>
            <dl className="kv-grid">
              <div>
                <dt>Flowchart</dt>
                <dd>{flowchart?.name || `Flowchart ${flowchartRun.flowchart_id}`}</dd>
              </div>
              <div>
                <dt>Cycles</dt>
                <dd>{flowchartRun.cycle_count ?? '-'}</dd>
              </div>
              <div>
                <dt>Node runs</dt>
                <dd>{flowchartRun.node_run_count ?? nodeRuns.length}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{flowchartRun.created_at || '-'}</dd>
              </div>
              <div>
                <dt>Started</dt>
                <dd>{flowchartRun.started_at || '-'}</dd>
              </div>
              <div>
                <dt>Finished</dt>
                <dd>{flowchartRun.finished_at || '-'}</dd>
              </div>
            </dl>
            {active ? <p className="toolbar-meta">Polling every 5s while run is active.</p> : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Node Runs</h2>
        {nodeRuns.length === 0 ? <p>No node runs recorded for this run yet.</p> : null}
        {nodeRuns.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Node run</th>
                  <th>Cycle</th>
                  <th>Node</th>
                  <th>Status</th>
                  <th>Execution</th>
                  <th>Runtime</th>
                  <th>Dispatch / Fallback</th>
                  <th>Triggered by</th>
                  <th>Pulled context</th>
                  <th>Started</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {nodeRuns.map((nodeRun) => {
                  const hasTask = Number.isInteger(nodeRun.agent_task_id) && nodeRun.agent_task_id > 0
                  const href = hasTask ? `/nodes/${nodeRun.agent_task_id}` : null
                  return (
                    <tr
                      key={nodeRun.id}
                      className={href ? 'table-row-link' : undefined}
                      data-href={href || ''}
                      onClick={href ? (event) => handleNodeRunClick(event, href) : undefined}
                    >
                      <td>
                        {href ? <Link to={href}>{nodeRun.id}</Link> : nodeRun.id}
                      </td>
                      <td>{nodeRun.cycle_index ?? '-'}</td>
                      <td>
                        <strong>{nodeRun.node_title || `Node ${nodeRun.flowchart_node_id || '-'}`}</strong>
                        <p className="table-note">{nodeRun.node_type || '-'}</p>
                      </td>
                      <td>
                        <span className={runStatusClass(nodeRun.status)}>{nodeRun.status || '-'}</span>
                      </td>
                      <td>{nodeRun.execution_index ?? '-'}</td>
                      <td>
                        <p className="table-note">{nodeRun.provider_route || '-'}</p>
                        <p className="table-note">dispatch id: {nodeRun.provider_dispatch_id || '-'}</p>
                        <p className="table-note">workspace: {nodeRun.workspace_identity || '-'}</p>
                      </td>
                      <td>
                        <p className="table-note">
                          {nodeRun.dispatch_status || '-'}
                          {nodeRun.dispatch_uncertain ? ' (uncertain)' : ''}
                        </p>
                        {nodeRun.fallback_attempted ? (
                          <p className="table-note">fallback: {nodeRun.fallback_reason || 'unknown'}</p>
                        ) : null}
                        {nodeRun.api_failure_category ? (
                          <p className="table-note">api failure: {nodeRun.api_failure_category}</p>
                        ) : null}
                        {nodeRun.cli_fallback_used ? (
                          <p className="table-note">
                            cli fallback: {nodeRun.cli_preflight_passed ? 'preflight ok' : 'preflight unknown'}
                          </p>
                        ) : null}
                      </td>
                      <td>
                        <p className="table-note">{sourceSummary(nodeRun.trigger_sources)}</p>
                      </td>
                      <td>
                        <p className="table-note">{sourceSummary(nodeRun.pulled_dotted_sources)}</p>
                      </td>
                      <td>{nodeRun.started_at || '-'}</td>
                      <td>{nodeRun.finished_at || '-'}</td>
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

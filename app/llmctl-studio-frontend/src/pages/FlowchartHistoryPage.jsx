import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getFlowchartHistory } from '../lib/studioApi'
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

function statusClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'queued') {
    return 'status status-running'
  }
  if (normalized === 'stopping') {
    return 'status status-warning'
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'status status-failed'
  }
  return 'status status-idle'
}

export default function FlowchartHistoryPage() {
  const navigate = useNavigate()
  const { flowchartId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedFlowchartId) {
      return
    }
    let cancelled = false
    getFlowchartHistory(parsedFlowchartId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load flowchart history.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedFlowchartId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const flowchart = payload?.flowchart && typeof payload.flowchart === 'object' ? payload.flowchart : null
  const runs = Array.isArray(payload?.runs) ? payload.runs : []
  const invalidId = parsedFlowchartId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid flowchart id.' : state.error

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Flowchart history">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}`} className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back to flowchart
              </Link>
            ) : null}
          </div>
        </div>
        <div className="card-header">
          <h2 className="section-title">Flowchart History</h2>
        </div>
        <p className="muted" style={{ marginTop: '12px' }}>
          {flowchart
            ? `${flowchart.name}. Each run begins at Start. If execution routes back to Start, the current run completes and a new run is queued.`
            : 'Each run begins at Start. If execution routes back to Start, the current run completes and a new run is queued.'}
        </p>
        {loading ? <p>Loading run history...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!loading && !error && runs.length === 0 ? (
          <p className="muted" style={{ marginTop: '16px' }}>No flowchart history yet.</p>
        ) : null}
        {!loading && !error && runs.length > 0 ? (
          <div style={{ marginTop: '20px', overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Cycles</th>
                  <th>Node runs</th>
                  <th>Created</th>
                  <th>Started</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const href = `/flowcharts/${parsedFlowchartId}/history/${run.id}`
                  return (
                    <tr
                      key={run.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>run {run.id}</Link>
                      </td>
                      <td>
                        <span className={statusClass(run.status)}>{run.status || '-'}</span>
                      </td>
                      <td className="muted">{run.cycle_count ?? 0}</td>
                      <td className="muted">{run.node_run_count ?? 0}</td>
                      <td className="muted">{run.created_at || '-'}</td>
                      <td className="muted">{run.started_at || '-'}</td>
                      <td className="muted">{run.finished_at || '-'}</td>
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

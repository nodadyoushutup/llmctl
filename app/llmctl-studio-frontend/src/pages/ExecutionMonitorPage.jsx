import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getNodeStatus, getRun } from '../lib/studioApi'

function parsePositiveInt(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function summarizeRun(payload) {
  if (!payload || typeof payload !== 'object' || !payload.run || typeof payload.run !== 'object') {
    return null
  }
  const run = payload.run
  return {
    id: run.id,
    name: run.name || `Run ${run.id}`,
    status: run.status || 'unknown',
    loopsCompleted: payload.loops_completed ?? 0,
    loopsRemaining: payload.loops_remaining,
  }
}

function summarizeNode(payload) {
  if (!payload || typeof payload !== 'object') {
    return null
  }
  return {
    id: payload.id,
    status: payload.status || 'unknown',
    currentStage: payload.current_stage || '-',
    startedAt: payload.started_at || '-',
    finishedAt: payload.finished_at || '-',
  }
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

export default function ExecutionMonitorPage() {
  const urlParams = new URLSearchParams(window.location.search)
  const initialRunId = urlParams.get('runId') || ''
  const initialNodeId = urlParams.get('nodeId') || ''
  const autoRunId = parsePositiveInt(initialRunId)
  const autoNodeId = parsePositiveInt(initialNodeId)

  const [runIdInput, setRunIdInput] = useState(initialRunId)
  const [nodeIdInput, setNodeIdInput] = useState(initialNodeId)
  const [runState, setRunState] = useState({
    loading: autoRunId !== null,
    payload: null,
    error: '',
  })
  const [nodeState, setNodeState] = useState({
    loading: autoNodeId !== null,
    payload: null,
    error: '',
  })

  async function handleRunLoad(event) {
    event.preventDefault()
    const runId = parsePositiveInt(runIdInput)
    if (!runId) {
      setRunState({ loading: false, payload: null, error: 'Enter a valid run id.' })
      return
    }
    setRunState({ loading: true, payload: null, error: '' })
    try {
      const payload = await getRun(runId)
      setRunState({ loading: false, payload, error: '' })
    } catch (error) {
      setRunState({
        loading: false,
        payload: null,
        error: errorMessage(error, 'Failed to load run detail.'),
      })
    }
  }

  async function handleNodeLoad(event) {
    event.preventDefault()
    const nodeId = parsePositiveInt(nodeIdInput)
    if (!nodeId) {
      setNodeState({ loading: false, payload: null, error: 'Enter a valid node id.' })
      return
    }
    setNodeState({ loading: true, payload: null, error: '' })
    try {
      const payload = await getNodeStatus(nodeId)
      setNodeState({ loading: false, payload, error: '' })
    } catch (error) {
      setNodeState({
        loading: false,
        payload: null,
        error: errorMessage(error, 'Failed to load node status.'),
      })
    }
  }

  const runSummary = summarizeRun(runState.payload)
  const nodeSummary = summarizeNode(nodeState.payload)

  useEffect(() => {
    if (!autoRunId) {
      return
    }
    let cancelled = false
    getRun(autoRunId)
      .then((payload) => {
        if (!cancelled) {
          setRunState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setRunState({
            loading: false,
            payload: null,
            error: errorMessage(error, 'Failed to load run detail.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [autoRunId])

  useEffect(() => {
    if (!autoNodeId) {
      return
    }
    let cancelled = false
    getNodeStatus(autoNodeId)
      .then((payload) => {
        if (!cancelled) {
          setNodeState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setNodeState({
            loading: false,
            payload: null,
            error: errorMessage(error, 'Failed to load node status.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [autoNodeId])

  return (
    <section className="stack" aria-label="Execution monitor">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Execution Monitor</h2>
            <p>Inspect run and node execution status by id using live API responses.</p>
          </div>
          <div className="table-actions">
            <Link className="btn btn-secondary" to="/runs">Autoruns</Link>
            <Link className="btn btn-secondary" to="/nodes">Nodes</Link>
          </div>
        </div>
      </article>

      <section className="card-grid" aria-label="Execution reads">
        <article className="card">
          <h2>Run detail</h2>
          <form className="inline-form" onSubmit={handleRunLoad}>
            <label htmlFor="run-id-input">Run ID</label>
            <input
              id="run-id-input"
              type="number"
              min="1"
              value={runIdInput}
              onChange={(event) => setRunIdInput(event.target.value)}
            />
            <button type="submit" disabled={runState.loading}>
              {runState.loading ? 'Loading...' : 'Load run'}
            </button>
          </form>
          {runState.error ? <p className="error-text">{runState.error}</p> : null}
          {runSummary ? (
            <dl className="kv-grid">
              <div>
                <dt>ID</dt>
                <dd>{runSummary.id}</dd>
              </div>
              <div>
                <dt>Name</dt>
                <dd>{runSummary.name}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{runSummary.status}</dd>
              </div>
              <div>
                <dt>Loops completed</dt>
                <dd>{runSummary.loopsCompleted}</dd>
              </div>
              <div>
                <dt>Loops remaining</dt>
                <dd>{runSummary.loopsRemaining ?? 'forever'}</dd>
              </div>
            </dl>
          ) : null}
          {runState.payload ? (
            <details>
              <summary>Raw payload</summary>
              <pre>{JSON.stringify(runState.payload, null, 2)}</pre>
            </details>
          ) : null}
        </article>

        <article className="card">
          <h2>Node status</h2>
          <form className="inline-form" onSubmit={handleNodeLoad}>
            <label htmlFor="node-id-input">Node ID</label>
            <input
              id="node-id-input"
              type="number"
              min="1"
              value={nodeIdInput}
              onChange={(event) => setNodeIdInput(event.target.value)}
            />
            <button type="submit" disabled={nodeState.loading}>
              {nodeState.loading ? 'Loading...' : 'Load node'}
            </button>
          </form>
          {nodeState.error ? <p className="error-text">{nodeState.error}</p> : null}
          {nodeSummary ? (
            <dl className="kv-grid">
              <div>
                <dt>ID</dt>
                <dd>{nodeSummary.id}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{nodeSummary.status}</dd>
              </div>
              <div>
                <dt>Current stage</dt>
                <dd>{nodeSummary.currentStage}</dd>
              </div>
              <div>
                <dt>Started</dt>
                <dd>{nodeSummary.startedAt}</dd>
              </div>
              <div>
                <dt>Finished</dt>
                <dd>{nodeSummary.finishedAt}</dd>
              </div>
            </dl>
          ) : null}
          {nodeState.payload ? (
            <details>
              <summary>Raw payload</summary>
              <pre>{JSON.stringify(nodeState.payload, null, 2)}</pre>
            </details>
          ) : null}
        </article>
      </section>
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getFlowchartEdit, updateFlowchart } from '../lib/studioApi'

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

function parseOptionalPositiveInt(value) {
  const cleaned = String(value || '').trim()
  if (!cleaned) {
    return null
  }
  const parsed = Number.parseInt(cleaned, 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function FlowchartEditPage() {
  const navigate = useNavigate()
  const { flowchartId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    maxNodeExecutions: '',
    maxRuntimeMinutes: '',
    maxParallelNodes: '1',
  })

  useEffect(() => {
    if (!parsedFlowchartId) {
      return
    }
    let cancelled = false
    getFlowchartEdit(parsedFlowchartId)
      .then((payload) => {
        if (cancelled) {
          return
        }
        const flowchart = payload?.flowchart && typeof payload.flowchart === 'object' ? payload.flowchart : null
        setForm({
          name: flowchart?.name ? String(flowchart.name) : '',
          description: flowchart?.description ? String(flowchart.description) : '',
          maxNodeExecutions: flowchart?.max_node_executions ? String(flowchart.max_node_executions) : '',
          maxRuntimeMinutes: flowchart?.max_runtime_minutes ? String(flowchart.max_runtime_minutes) : '',
          maxParallelNodes: flowchart?.max_parallel_nodes ? String(flowchart.max_parallel_nodes) : '1',
        })
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load flowchart metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedFlowchartId])

  const flowchart = state.payload?.flowchart && typeof state.payload.flowchart === 'object'
    ? state.payload.flowchart
    : null
  const invalidId = parsedFlowchartId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid flowchart id.' : state.error

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedFlowchartId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updateFlowchart(parsedFlowchartId, {
        name: form.name,
        description: form.description,
        maxNodeExecutions: parseOptionalPositiveInt(form.maxNodeExecutions),
        maxRuntimeMinutes: parseOptionalPositiveInt(form.maxRuntimeMinutes),
        maxParallelNodes: parseOptionalPositiveInt(form.maxParallelNodes) || 1,
      })
      navigate(`/flowcharts/${parsedFlowchartId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update flowchart.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit flowchart">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{flowchart ? `Edit ${flowchart.name}` : 'Edit Flowchart'}</h2>
            <p>Native React replacement for `/flowcharts/:flowchartId/edit` metadata edits.</p>
          </div>
          <div className="table-actions">
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}`} className="btn-link btn-secondary">Back to Flowchart</Link>
            ) : null}
            <Link to="/flowcharts" className="btn-link btn-secondary">All Flowcharts</Link>
          </div>
        </div>
        {loading ? <p>Loading flowchart metadata...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!loading && !error ? (
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="field">
              <span>Name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description (optional)</span>
              <textarea
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Max node executions (optional)</span>
              <input
                type="number"
                min="1"
                step="1"
                value={form.maxNodeExecutions}
                onChange={(event) => setForm((current) => ({ ...current, maxNodeExecutions: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Max runtime minutes (optional)</span>
              <input
                type="number"
                min="1"
                step="1"
                value={form.maxRuntimeMinutes}
                onChange={(event) => setForm((current) => ({ ...current, maxRuntimeMinutes: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Max parallel nodes</span>
              <input
                type="number"
                min="1"
                step="1"
                required
                value={form.maxParallelNodes}
                onChange={(event) => setForm((current) => ({ ...current, maxParallelNodes: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={busy}>Save Flowchart</button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

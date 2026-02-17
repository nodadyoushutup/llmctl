import { useEffect, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { createFlowchart, getFlowchartMeta } from '../lib/studioApi'

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

export default function FlowchartNewPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    maxNodeExecutions: '',
    maxRuntimeMinutes: '',
    maxParallelNodes: '1',
  })

  useEffect(() => {
    let cancelled = false
    getFlowchartMeta()
      .then((payload) => {
        if (cancelled) {
          return
        }
        const defaults = payload?.defaults && typeof payload.defaults === 'object' ? payload.defaults : null
        setForm((current) => ({
          ...current,
          maxNodeExecutions: defaults?.max_node_executions ? String(defaults.max_node_executions) : '',
          maxRuntimeMinutes: defaults?.max_runtime_minutes ? String(defaults.max_runtime_minutes) : '',
          maxParallelNodes: defaults?.max_parallel_nodes ? String(defaults.max_parallel_nodes) : '1',
        }))
        setState({ loading: false, payload, error: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load flowchart defaults.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setActionError('')
    setBusy(true)
    try {
      const payload = await createFlowchart({
        name: form.name,
        description: form.description,
        maxNodeExecutions: parseOptionalPositiveInt(form.maxNodeExecutions),
        maxRuntimeMinutes: parseOptionalPositiveInt(form.maxRuntimeMinutes),
        maxParallelNodes: parseOptionalPositiveInt(form.maxParallelNodes) || 1,
      })
      const flowchartId = payload?.flowchart?.id
      if (flowchartId) {
        navigate(`/flowcharts/${flowchartId}`)
        return
      }
      navigate('/flowcharts')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to create flowchart.'))
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Create flowchart">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <Link to="/flowcharts" className="btn btn-secondary">
            <i className="fa-solid fa-arrow-left" />
            back to flowcharts
          </Link>
        </div>
        <div className="card-header">
          <h2 className="section-title">Create Flowchart</h2>
        </div>
        <p className="muted" style={{ marginTop: '12px' }}>
          Start with workflow metadata now. Add nodes and edges in the visual editor after creation.
        </p>
        {state.loading ? <p>Loading flowchart defaults...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error ? (
          <form className="form-grid" style={{ marginTop: '20px' }} onSubmit={handleSubmit}>
            <label className="field">
              <span>name</span>
              <input
                type="text"
                placeholder="Release readiness"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>description (optional)</span>
              <textarea
                placeholder="Flowchart for validating and shipping weekly release."
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>max node executions (optional)</span>
              <input
                type="number"
                min="1"
                step="1"
                value={form.maxNodeExecutions}
                onChange={(event) => setForm((current) => ({ ...current, maxNodeExecutions: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>max runtime minutes (optional)</span>
              <input
                type="number"
                min="1"
                step="1"
                value={form.maxRuntimeMinutes}
                onChange={(event) => setForm((current) => ({ ...current, maxRuntimeMinutes: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>max parallel nodes</span>
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
              <button type="submit" className="btn btn-primary" disabled={busy}>
                <i className="fa-solid fa-plus" />
                create flowchart
              </button>
              <Link to="/flowcharts" className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                cancel
              </Link>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

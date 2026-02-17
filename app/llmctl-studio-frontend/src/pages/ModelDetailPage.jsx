import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getModel } from '../lib/studioApi'

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

export default function ModelDetailPage() {
  const { modelId } = useParams()
  const parsedModelId = useMemo(() => parseId(modelId), [modelId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedModelId) {
      return
    }
    let cancelled = false
    getModel(parsedModelId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load model.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedModelId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const model = payload?.model && typeof payload.model === 'object' ? payload.model : null
  const templates = Array.isArray(payload?.attached_templates) ? payload.attached_templates : []
  const nodes = Array.isArray(payload?.attached_nodes) ? payload.attached_nodes : []
  const tasks = Array.isArray(payload?.attached_tasks) ? payload.attached_tasks : []
  const invalidId = parsedModelId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid model id.' : state.error

  return (
    <section className="stack" aria-label="Model detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{model ? model.name : 'Model'}</h2>
            <p>{model?.description || 'Model settings and binding usage.'}</p>
          </div>
          <div className="table-actions">
            {model ? <Link to={`/models/${model.id}/edit`} className="btn-link">Edit</Link> : null}
            <Link to="/models" className="btn-link btn-secondary">All Models</Link>
          </div>
        </div>
        {loading ? <p>Loading model...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {model ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Provider</dt>
                <dd>{model.provider_label || model.provider || '-'}</dd>
              </div>
              <div>
                <dt>Configured model</dt>
                <dd>{model.model_name || '-'}</dd>
              </div>
              <div>
                <dt>Default</dt>
                <dd>{model.is_default ? 'Yes' : 'No'}</dd>
              </div>
            </dl>
            <pre>{model.config_json || '{}'}</pre>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Template bindings</h2>
        {templates.length === 0 ? <p>No template bindings.</p> : (
          <ul>
            {templates.map((template) => (
              <li key={template.id}>
                <Link to={`/task-templates/${template.id}`}>{template.name || `Template ${template.id}`}</Link>
              </li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Flowchart node bindings</h2>
        {nodes.length === 0 ? <p>No flowchart node bindings.</p> : (
          <ul>
            {nodes.map((node) => (
              <li key={node.id}>
                <Link to={`/flowcharts/${node.flowchart_id}`}>{node.flowchart_name || `Flowchart ${node.flowchart_id}`}</Link>
                {' '}
                / {node.title || node.node_type || `Node ${node.id}`}
              </li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Task bindings</h2>
        {tasks.length === 0 ? <p>No task bindings.</p> : (
          <ul>
            {tasks.map((task) => (
              <li key={task.id}>Task {task.id} ({task.status || 'unknown'})</li>
            ))}
          </ul>
        )}
      </article>
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getScript } from '../lib/studioApi'

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

export default function ScriptDetailPage() {
  const { scriptId } = useParams()
  const parsedScriptId = useMemo(() => parseId(scriptId), [scriptId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedScriptId) {
      return
    }
    let cancelled = false
    getScript(parsedScriptId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load script.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedScriptId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const script = payload?.script && typeof payload.script === 'object' ? payload.script : null
  const attachedTasks = Array.isArray(payload?.attached_tasks) ? payload.attached_tasks : []
  const attachedTemplates = Array.isArray(payload?.attached_templates) ? payload.attached_templates : []
  const attachedNodes = Array.isArray(payload?.attached_nodes) ? payload.attached_nodes : []
  const invalidId = parsedScriptId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid script id.' : state.error

  return (
    <section className="stack" aria-label="Script detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{script ? script.file_name : 'Script'}</h2>
            <p>{script?.description || 'Native React replacement for `/scripts/:scriptId` detail and bindings.'}</p>
          </div>
          <div className="table-actions">
            {script ? <Link to={`/scripts/${script.id}/edit`} className="btn-link">Edit</Link> : null}
            <Link to="/scripts" className="btn-link btn-secondary">All Scripts</Link>
          </div>
        </div>
        {loading ? <p>Loading script...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {script ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Script type</dt>
                <dd>{script.script_type_label || script.script_type || '-'}</dd>
              </div>
              <div>
                <dt>Bindings</dt>
                <dd>{script.binding_count ?? 0}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{script.updated_at || '-'}</dd>
              </div>
            </dl>
            <pre>{script.content || ''}</pre>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Task bindings</h2>
        {attachedTasks.length === 0 ? <p>No task bindings.</p> : (
          <ul>
            {attachedTasks.map((task) => (
              <li key={task.id}>Task {task.id} ({task.status || 'unknown'})</li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Template bindings</h2>
        {attachedTemplates.length === 0 ? <p>No template bindings.</p> : (
          <ul>
            {attachedTemplates.map((template) => (
              <li key={template.id}>
                <Link to={`/task-templates/${template.id}`}>{template.name || `Template ${template.id}`}</Link>
              </li>
            ))}
          </ul>
        )}
      </article>

      <article className="card">
        <h2>Flowchart node bindings</h2>
        {attachedNodes.length === 0 ? <p>No flowchart node bindings.</p> : (
          <ul>
            {attachedNodes.map((node) => (
              <li key={node.id}>
                <Link to={`/flowcharts/${node.flowchart_id}`}>{node.flowchart_name || `Flowchart ${node.flowchart_id}`}</Link>
                {' '}
                / {node.title || node.node_type || `Node ${node.id}`}
              </li>
            ))}
          </ul>
        )}
      </article>
    </section>
  )
}

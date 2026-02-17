import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteTaskTemplate, getTaskTemplate } from '../lib/studioApi'

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

export default function TaskTemplateDetailPage() {
  const navigate = useNavigate()
  const { templateId } = useParams()
  const parsedTemplateId = useMemo(() => parseId(templateId), [templateId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!parsedTemplateId) {
      return
    }
    let cancelled = false
    getTaskTemplate(parsedTemplateId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load task template.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedTemplateId])

  const invalidId = parsedTemplateId == null
  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const template = payload && payload.template && typeof payload.template === 'object'
    ? payload.template
    : null
  const attachments = template && Array.isArray(template.attachments) ? template.attachments : []
  const taskCount = Number.isInteger(payload?.task_count) ? payload.task_count : 0
  const agentsById = payload && payload.agents_by_id && typeof payload.agents_by_id === 'object'
    ? payload.agents_by_id
    : {}

  async function handleDelete() {
    if (!template || !window.confirm('Delete this task template?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteTaskTemplate(template.id)
      navigate('/task-templates')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete task template.'))
    }
  }

  return (
    <section className="stack" aria-label="Task template detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{template ? template.name : 'Task Template'}</h2>
            <p>Native React detail view for `/task-templates/:templateId`.</p>
          </div>
          <div className="table-actions">
            {template ? (
              <Link to={`/task-templates/${template.id}/edit`} className="btn-link btn-secondary">
                Edit
              </Link>
            ) : null}
            <Link to="/task-templates" className="btn-link btn-secondary">All Workflow Nodes</Link>
            {template ? (
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete task template"
                title="Delete task template"
                disabled={busy}
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
            ) : null}
          </div>
        </div>
        {(!invalidId && state.loading) ? <p>Loading task template...</p> : null}
        {(invalidId || state.error) ? (
          <p className="error-text">{invalidId ? 'Invalid task template id.' : state.error}</p>
        ) : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {template ? (
          <>
            <dl className="kv-grid">
              <div>
                <dt>Agent</dt>
                <dd>{agentsById[String(template.agent_id)] || 'Unassigned'}</dd>
              </div>
              <div>
                <dt>Description</dt>
                <dd>{template.description || '-'}</dd>
              </div>
              <div>
                <dt>Node runs</dt>
                <dd>{taskCount}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{template.created_at || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{template.updated_at || '-'}</dd>
              </div>
            </dl>
            <h3>Prompt</h3>
            <pre>{template.prompt || ''}</pre>
            <h3>Attachments</h3>
            {attachments.length === 0 ? <p>No attachments.</p> : null}
            {attachments.length > 0 ? (
              <ul>
                {attachments.map((attachment) => (
                  <li key={attachment.id}>
                    {attachment.file_name}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}
      </article>
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
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
    if (!template || !window.confirm('Delete this task?')) {
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

  const agentName = agentsById[String(template?.agent_id)] || agentsById[template?.agent_id] || 'Unassigned'

  return (
    <section className="stack" aria-label="Task template detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            <Link to="/task-templates" className="btn btn-secondary">
              <i className="fa-solid fa-arrow-left" />
              back to tasks
            </Link>
            {template ? (
              <Link to={`/task-templates/${template.id}/edit`} className="btn btn-secondary">
                <i className="fa-solid fa-pen-to-square" />
                edit
              </Link>
            ) : null}
            {template ? (
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy}
                onClick={handleDelete}
              >
                <i className="fa-solid fa-trash" />
                delete
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
            <div className="card-header">
              <div>
                <p className="eyebrow">task {template.id}</p>
                <h2 className="section-title">{template.name}</h2>
              </div>
            </div>

            <div className="grid grid-2" style={{ marginTop: '20px' }}>
              <div className="subcard">
                <p className="eyebrow">details</p>
                <div className="stack" style={{ marginTop: '12px', fontSize: '12px' }}>
                  <p className="muted">Agent: {agentName}</p>
                  <p className="muted">Description: {template.description || '-'}</p>
                  <p className="muted">Created: {template.created_at || '-'}</p>
                  <p className="muted">Updated: {template.updated_at || '-'}</p>
                  <p className="muted">Node runs: {taskCount}</p>
                  {attachments.length > 0 ? (
                    <>
                      <p className="muted">Attachments:</p>
                      {attachments.map((attachment) => (
                        <p key={attachment.id} className="muted">
                          {attachment.file_name}
                          {attachment.file_path ? ` (${attachment.file_path})` : ''}
                        </p>
                      ))}
                    </>
                  ) : (
                    <p className="muted">Attachments: -</p>
                  )}
                </div>
              </div>
              <div className="subcard">
                <p className="eyebrow">prompt</p>
                <pre style={{ marginTop: '12px', whiteSpace: 'pre-wrap' }}>{template.prompt || ''}</pre>
              </div>
            </div>
          </>
        ) : null}
      </article>
    </section>
  )
}

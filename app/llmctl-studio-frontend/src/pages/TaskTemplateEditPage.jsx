import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import {
  getTaskTemplateEdit,
  removeTaskTemplateAttachment,
  updateTaskTemplate,
} from '../lib/studioApi'

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

export default function TaskTemplateEditPage() {
  const navigate = useNavigate()
  const { templateId } = useParams()
  const parsedTemplateId = useMemo(() => parseId(templateId), [templateId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [busyAttachmentId, setBusyAttachmentId] = useState(null)
  const [selectedFiles, setSelectedFiles] = useState([])
  const [form, setForm] = useState({
    name: '',
    description: '',
    prompt: '',
    agentId: '',
  })

  useEffect(() => {
    if (!parsedTemplateId) {
      setState({ loading: false, payload: null, error: 'Invalid task template id.' })
      return
    }
    let cancelled = false
    getTaskTemplateEdit(parsedTemplateId)
      .then((payload) => {
        if (!cancelled) {
          const template = payload && payload.template && typeof payload.template === 'object'
            ? payload.template
            : null
          setState({ loading: false, payload, error: '' })
          if (template) {
            setForm({
              name: String(template.name || ''),
              description: String(template.description || ''),
              prompt: String(template.prompt || ''),
              agentId: template.agent_id ? String(template.agent_id) : '',
            })
          }
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load task template edit data.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedTemplateId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const template = payload && payload.template && typeof payload.template === 'object'
    ? payload.template
    : null
  const agents = payload && Array.isArray(payload.agents) ? payload.agents : []
  const attachments = template && Array.isArray(template.attachments) ? template.attachments : []

  async function refresh() {
    if (!parsedTemplateId) {
      return
    }
    try {
      const payload = await getTaskTemplateEdit(parsedTemplateId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        ...current,
        error: errorMessage(error, 'Failed to refresh task template data.'),
      }))
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedTemplateId) {
      return
    }
    setFormError('')
    setSaving(true)
    try {
      await updateTaskTemplate(parsedTemplateId, {
        name: form.name,
        description: form.description,
        prompt: form.prompt,
        agentId: form.agentId ? Number.parseInt(form.agentId, 10) : null,
      })
      navigate(`/task-templates/${parsedTemplateId}`)
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to update task template.'))
    } finally {
      setSaving(false)
    }
  }

  async function handleRemoveAttachment(attachmentId) {
    if (!parsedTemplateId || !window.confirm('Remove this attachment?')) {
      return
    }
    setFormError('')
    setBusyAttachmentId(attachmentId)
    try {
      await removeTaskTemplateAttachment(parsedTemplateId, attachmentId)
      await refresh()
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to remove attachment.'))
    } finally {
      setBusyAttachmentId(null)
    }
  }

  return (
    <section className="stack" aria-label="Edit task template">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            {template ? (
              <Link to={`/task-templates/${template.id}`} className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back to task
              </Link>
            ) : null}
            <Link to="/task-templates" className="btn btn-secondary">
              <i className="fa-solid fa-list" />
              all tasks
            </Link>
          </div>
        </div>

        <div className="card-header">
          <div>
            {template ? <p className="eyebrow">task {template.id}</p> : null}
            <h2 className="section-title">Edit Task</h2>
          </div>
        </div>

        <p className="muted" style={{ marginTop: '12px' }}>
          Update task metadata without running a node.
        </p>

        {state.loading ? <p style={{ marginTop: '20px' }}>Loading task template...</p> : null}
        {state.error ? <p className="error-text" style={{ marginTop: '12px' }}>{state.error}</p> : null}
        {formError ? <p className="error-text" style={{ marginTop: '12px' }}>{formError}</p> : null}

        {!state.loading && !state.error ? (
          <form className="form-grid" style={{ marginTop: '20px' }} onSubmit={handleSubmit}>
            <label className="field">
              <span>name</span>
              <input
                type="text"
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>description (optional)</span>
              <input
                type="text"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>agent</span>
              <select
                value={form.agentId}
                onChange={(event) => setForm((current) => ({ ...current, agentId: event.target.value }))}
              >
                <option value="">No agent (optional)</option>
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
              {agents.length === 0 ? (
                <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                  Create an agent when you want to attach one.
                </span>
              ) : null}
            </label>
            <label className="field field-span">
              <span>prompt</span>
              <textarea
                value={form.prompt}
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>attachments (optional)</span>
              <input
                type="file"
                multiple
                onChange={(event) => setSelectedFiles(Array.from(event.target.files || []))}
              />
              <span className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                Paste images into the prompt or choose files. Saved to <code>data/attachments</code>.
              </span>
              <div className="muted" style={{ fontSize: '12px', marginTop: '6px' }}>
                {selectedFiles.length > 0
                  ? selectedFiles.map((file) => file.name).join(', ')
                  : ''}
              </div>
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                <i className="fa-solid fa-floppy-disk" />
                {saving ? 'saving...' : 'save'}
              </button>
              {template ? (
                <Link className="btn btn-secondary" to={`/task-templates/${template.id}`}>
                  <i className="fa-solid fa-arrow-left" />
                  cancel
                </Link>
              ) : null}
            </div>
          </form>
        ) : null}

        {attachments.length > 0 ? (
          <div className="stack" style={{ marginTop: '12px' }}>
            <p className="muted" style={{ fontSize: '12px' }}>Existing attachments:</p>
            {attachments.map((attachment) => (
              <div key={attachment.id} className="row" style={{ gap: '8px', alignItems: 'center' }}>
                <p className="muted" style={{ fontSize: '12px', margin: 0 }}>
                  {attachment.file_name}
                  {attachment.file_path ? ` (${attachment.file_path})` : ''}
                </p>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ padding: '4px 10px' }}
                  disabled={busyAttachmentId === attachment.id}
                  onClick={() => handleRemoveAttachment(attachment.id)}
                >
                  remove
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </article>
    </section>
  )
}

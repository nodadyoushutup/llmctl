import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
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
        <div className="title-row">
          <h2>{template ? `Edit ${template.name}` : 'Edit Task Template'}</h2>
          <div className="table-actions">
            {template ? (
              <Link to={`/task-templates/${template.id}`} className="btn-link btn-secondary">
                Back to Task Template
              </Link>
            ) : null}
            <Link to="/task-templates" className="btn-link btn-secondary">All Workflow Nodes</Link>
          </div>
        </div>
        {state.loading ? <p>Loading task template...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {formError ? <p className="error-text">{formError}</p> : null}
        {!state.loading && !state.error ? (
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
            <label className="field">
              <span>Description (optional)</span>
              <input
                type="text"
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Agent</span>
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
            </label>
            <label className="field field-span">
              <span>Prompt</span>
              <textarea
                required
                value={form.prompt}
                onChange={(event) => setForm((current) => ({ ...current, prompt: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={saving}>
                {saving ? 'Saving...' : 'Save Task Template'}
              </button>
            </div>
          </form>
        ) : null}
      </article>
      {attachments.length > 0 ? (
        <article className="card">
          <h2>Existing Attachments</h2>
          <ul className="stack-sm">
            {attachments.map((attachment) => (
              <li key={attachment.id} className="title-row">
                <span>{attachment.file_name}</span>
                <button
                  type="button"
                  className="icon-button icon-button-danger"
                  aria-label="Remove attachment"
                  title="Remove attachment"
                  disabled={busyAttachmentId === attachment.id}
                  onClick={() => handleRemoveAttachment(attachment.id)}
                >
                  <ActionIcon name="trash" />
                </button>
              </li>
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  )
}

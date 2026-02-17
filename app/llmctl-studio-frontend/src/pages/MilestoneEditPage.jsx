import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMilestoneEdit, updateMilestone } from '../lib/studioApi'

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

function toDateInput(value) {
  const normalized = String(value || '').trim()
  if (!normalized || normalized === '-') {
    return ''
  }
  return normalized.slice(0, 10)
}

export default function MilestoneEditPage() {
  const navigate = useNavigate()
  const { milestoneId } = useParams()
  const parsedMilestoneId = useMemo(() => parseId(milestoneId), [milestoneId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    status: '',
    priority: '',
    owner: '',
    startDate: '',
    dueDate: '',
    progressPercent: 0,
    health: '',
    successCriteria: '',
    dependencies: '',
    links: '',
    latestUpdate: '',
  })

  useEffect(() => {
    if (!parsedMilestoneId) {
      setState({ loading: false, payload: null, error: 'Invalid milestone id.' })
      return
    }
    let cancelled = false
    getMilestoneEdit(parsedMilestoneId)
      .then((payload) => {
        if (!cancelled) {
          const milestone = payload && payload.milestone && typeof payload.milestone === 'object'
            ? payload.milestone
            : null
          setState({ loading: false, payload, error: '' })
          if (milestone) {
            setForm({
              name: String(milestone.name || ''),
              description: String(milestone.description || ''),
              status: String(milestone.status || ''),
              priority: String(milestone.priority || ''),
              owner: String(milestone.owner || ''),
              startDate: toDateInput(milestone.start_date),
              dueDate: toDateInput(milestone.due_date),
              progressPercent: Number.isInteger(milestone.progress_percent) ? milestone.progress_percent : 0,
              health: String(milestone.health || ''),
              successCriteria: String(milestone.success_criteria || ''),
              dependencies: String(milestone.dependencies || ''),
              links: String(milestone.links || ''),
              latestUpdate: String(milestone.latest_update || ''),
            })
          }
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load milestone edit data.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMilestoneId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const milestone = payload && payload.milestone && typeof payload.milestone === 'object'
    ? payload.milestone
    : null
  const options = payload && payload.options && typeof payload.options === 'object'
    ? payload.options
    : {}
  const statusOptions = Array.isArray(options.status) ? options.status : []
  const priorityOptions = Array.isArray(options.priority) ? options.priority : []
  const healthOptions = Array.isArray(options.health) ? options.health : []

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedMilestoneId) {
      return
    }
    setFormError('')
    setSaving(true)
    try {
      await updateMilestone(parsedMilestoneId, form)
      navigate(`/milestones/${parsedMilestoneId}`)
    } catch (error) {
      setFormError(errorMessage(error, 'Failed to update milestone.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit milestone">
      <article className="card">
        <div className="title-row">
          <h2>{milestone ? `Edit ${milestone.name}` : 'Edit Milestone'}</h2>
          <div className="table-actions">
            {milestone ? (
              <Link to={`/milestones/${milestone.id}`} className="btn-link btn-secondary">
                Back to Milestone
              </Link>
            ) : null}
            <Link to="/milestones" className="btn-link btn-secondary">All Milestones</Link>
          </div>
        </div>
        {state.loading ? <p>Loading milestone...</p> : null}
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
              <span>Status</span>
              <select
                value={form.status}
                onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Priority</span>
              <select
                value={form.priority}
                onChange={(event) => setForm((current) => ({ ...current, priority: event.target.value }))}
              >
                {priorityOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Health</span>
              <select
                value={form.health}
                onChange={(event) => setForm((current) => ({ ...current, health: event.target.value }))}
              >
                {healthOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Owner</span>
              <input
                type="text"
                value={form.owner}
                onChange={(event) => setForm((current) => ({ ...current, owner: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Start date</span>
              <input
                type="date"
                value={form.startDate}
                onChange={(event) => setForm((current) => ({ ...current, startDate: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Due date</span>
              <input
                type="date"
                value={form.dueDate}
                onChange={(event) => setForm((current) => ({ ...current, dueDate: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Progress %</span>
              <input
                type="number"
                min="0"
                max="100"
                value={form.progressPercent}
                onChange={(event) => setForm((current) => ({ ...current, progressPercent: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Description</span>
              <textarea
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Success criteria</span>
              <textarea
                value={form.successCriteria}
                onChange={(event) => setForm((current) => ({ ...current, successCriteria: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Dependencies</span>
              <textarea
                value={form.dependencies}
                onChange={(event) => setForm((current) => ({ ...current, dependencies: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Links</span>
              <textarea
                value={form.links}
                onChange={(event) => setForm((current) => ({ ...current, links: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>Latest update</span>
              <textarea
                value={form.latestUpdate}
                onChange={(event) => setForm((current) => ({ ...current, latestUpdate: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={saving}>
                {saving ? 'Saving...' : 'Save Milestone'}
              </button>
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
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
  const [, setActionError] = useFlashState('error')
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
    setActionError('')
    setSaving(true)
    try {
      await updateMilestone(parsedMilestoneId, {
        ...form,
        progressPercent: Number.parseInt(form.progressPercent, 10) || 0,
      })
      navigate(`/milestones/${parsedMilestoneId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update milestone.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit milestone">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            {milestone ? (
              <Link to={`/milestones/${milestone.id}`} className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back
              </Link>
            ) : null}
            <Link to="/milestones" className="btn btn-secondary">
              <i className="fa-solid fa-list" />
              all milestones
            </Link>
          </div>
        </div>

        <div className="card-header">
          <div>
            {milestone ? <p className="eyebrow">milestone {milestone.id}</p> : null}
            <h2 className="section-title">Edit Milestone</h2>
          </div>
        </div>

        <p className="muted" style={{ marginTop: '12px' }}>
          Update milestone planning, ownership, and delivery details.
        </p>

        {state.loading ? <p style={{ marginTop: '20px' }}>Loading milestone...</p> : null}
        {state.error ? <p className="error-text" style={{ marginTop: '12px' }}>{state.error}</p> : null}

        {!state.loading && !state.error ? (
          <form className="form-grid" style={{ marginTop: '20px' }} onSubmit={handleSubmit}>
            <label className="field">
              <span>name</span>
              <input
                type="text"
                required
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>status</span>
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
              <span>priority</span>
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
              <span>health</span>
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
              <span>owner</span>
              <input
                type="text"
                value={form.owner}
                onChange={(event) => setForm((current) => ({ ...current, owner: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>start date</span>
              <input
                type="date"
                value={form.startDate}
                onChange={(event) => setForm((current) => ({ ...current, startDate: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>due date</span>
              <input
                type="date"
                value={form.dueDate}
                onChange={(event) => setForm((current) => ({ ...current, dueDate: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>progress %</span>
              <input
                type="number"
                min="0"
                max="100"
                value={form.progressPercent}
                onChange={(event) => setForm((current) => ({ ...current, progressPercent: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>description</span>
              <textarea
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>success criteria</span>
              <textarea
                value={form.successCriteria}
                onChange={(event) => setForm((current) => ({ ...current, successCriteria: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>dependencies</span>
              <textarea
                value={form.dependencies}
                onChange={(event) => setForm((current) => ({ ...current, dependencies: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>links</span>
              <textarea
                value={form.links}
                onChange={(event) => setForm((current) => ({ ...current, links: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>latest update</span>
              <textarea
                value={form.latestUpdate}
                onChange={(event) => setForm((current) => ({ ...current, latestUpdate: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                <i className="fa-solid fa-floppy-disk" />
                {saving ? 'saving...' : 'save'}
              </button>
              {milestone ? (
                <Link className="btn btn-secondary" to={`/milestones/${milestone.id}`}>
                  <i className="fa-solid fa-arrow-left" />
                  cancel
                </Link>
              ) : null}
            </div>
          </form>
        ) : null}
      </article>
    </section>
  )
}

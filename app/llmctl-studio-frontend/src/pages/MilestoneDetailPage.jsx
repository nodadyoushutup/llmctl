import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deleteMilestone, getMilestone } from '../lib/studioApi'

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

export default function MilestoneDetailPage() {
  const navigate = useNavigate()
  const { milestoneId } = useParams()
  const parsedMilestoneId = useMemo(() => parseId(milestoneId), [milestoneId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!parsedMilestoneId) {
      return
    }
    let cancelled = false
    getMilestone(parsedMilestoneId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load milestone.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMilestoneId])

  const invalidId = parsedMilestoneId == null
  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const milestone = payload && payload.milestone && typeof payload.milestone === 'object'
    ? payload.milestone
    : null

  async function handleDelete() {
    if (!milestone || !window.confirm('Delete this milestone?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteMilestone(milestone.id)
      navigate('/milestones')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete milestone.'))
    }
  }

  return (
    <section className="stack" aria-label="Milestone detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{milestone ? milestone.name : 'Milestone'}</h2>
            <p>Native React detail view for `/milestones/:milestoneId`.</p>
          </div>
          <div className="table-actions">
            {milestone ? (
              <Link to={`/milestones/${milestone.id}/edit`} className="btn-link btn-secondary">
                Edit
              </Link>
            ) : null}
            <Link to="/milestones" className="btn-link btn-secondary">All Milestones</Link>
            {milestone ? (
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete milestone"
                title="Delete milestone"
                disabled={busy}
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
            ) : null}
          </div>
        </div>
        {(!invalidId && state.loading) ? <p>Loading milestone...</p> : null}
        {(invalidId || state.error) ? (
          <p className="error-text">{invalidId ? 'Invalid milestone id.' : state.error}</p>
        ) : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {milestone ? (
          <>
            <div className="table-actions">
              <span className={milestone.status_class || 'status-chip status-idle'}>
                {milestone.status_label || milestone.status || '-'}
              </span>
              <span className={milestone.health_class || 'status-chip status-idle'}>
                health: {milestone.health_label || milestone.health || '-'}
              </span>
            </div>
            <dl className="kv-grid">
              <div>
                <dt>Owner</dt>
                <dd>{milestone.owner || '-'}</dd>
              </div>
              <div>
                <dt>Priority</dt>
                <dd>{milestone.priority_label || '-'}</dd>
              </div>
              <div>
                <dt>Progress</dt>
                <dd>{milestone.progress_percent ?? 0}%</dd>
              </div>
              <div>
                <dt>Start date</dt>
                <dd>{milestone.start_date || '-'}</dd>
              </div>
              <div>
                <dt>Due date</dt>
                <dd>{milestone.due_date || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{milestone.updated_at || '-'}</dd>
              </div>
            </dl>
            <p><strong>Description:</strong> {milestone.description || '-'}</p>
            <p><strong>Success criteria:</strong> {milestone.success_criteria || '-'}</p>
            <p><strong>Dependencies:</strong> {milestone.dependencies || '-'}</p>
            <p><strong>Links:</strong> {milestone.links || '-'}</p>
            <p><strong>Latest update:</strong> {milestone.latest_update || '-'}</p>
          </>
        ) : null}
      </article>
    </section>
  )
}

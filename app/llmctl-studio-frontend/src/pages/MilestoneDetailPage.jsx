import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
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
  const [actionError, setActionError] = useFlashState('error')
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

  const statusClass = milestone?.status_class || 'status status-idle'
  const healthClass = milestone?.health_class || 'status status-idle'

  return (
    <section className="stack" aria-label="Milestone detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            <Link to="/milestones" className="btn btn-secondary">
              <i className="fa-solid fa-arrow-left" />
              back
            </Link>
            {milestone ? (
              <Link to={`/milestones/${milestone.id}/edit`} className="btn btn-secondary">
                <i className="fa-solid fa-pen-to-square" />
                edit
              </Link>
            ) : null}
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
            <div className="card-header">
              <div>
                <p className="eyebrow">milestone</p>
                <h2 className="section-title">{milestone.name}</h2>
              </div>
              <div className="row" style={{ gap: '8px' }}>
                <span className={statusClass}>{milestone.status_label || milestone.status || '-'}</span>
                <span className={healthClass}>health: {milestone.health_label || milestone.health || '-'}</span>
              </div>
            </div>

            <div className="grid grid-2" style={{ marginTop: '20px' }}>
              <div className="subcard">
                <p className="eyebrow">details</p>
                <div className="stack" style={{ marginTop: '12px', fontSize: '12px' }}>
                  <p className="muted">Owner: {milestone.owner || '-'}</p>
                  <p className="muted">Priority: {milestone.priority_label || '-'}</p>
                  <p className="muted">Progress: {milestone.progress_percent ?? 0}%</p>
                  <p className="muted">Start date: {milestone.start_date || '-'}</p>
                  <p className="muted">Due date: {milestone.due_date || '-'}</p>
                  <p className="muted">Created: {milestone.created_at || '-'}</p>
                  <p className="muted">Updated: {milestone.updated_at || '-'}</p>
                </div>
              </div>
              <div className="subcard">
                <p className="eyebrow">description</p>
                {milestone.description ? (
                  <p className="muted" style={{ marginTop: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                    {milestone.description}
                  </p>
                ) : (
                  <p className="muted" style={{ marginTop: '12px' }}>No description yet.</p>
                )}
              </div>
            </div>

            <div className="grid grid-2" style={{ marginTop: '16px' }}>
              <div className="subcard">
                <p className="eyebrow">success criteria</p>
                <p className="muted" style={{ marginTop: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                  {milestone.success_criteria || 'No success criteria yet.'}
                </p>
              </div>
              <div className="subcard">
                <p className="eyebrow">latest update</p>
                <p className="muted" style={{ marginTop: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                  {milestone.latest_update || 'No updates yet.'}
                </p>
              </div>
            </div>

            <div className="grid grid-2" style={{ marginTop: '16px' }}>
              <div className="subcard">
                <p className="eyebrow">dependencies</p>
                <p className="muted" style={{ marginTop: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                  {milestone.dependencies || 'No dependencies noted.'}
                </p>
              </div>
              <div className="subcard">
                <p className="eyebrow">links</p>
                <p className="muted" style={{ marginTop: '12px', fontSize: '12px', whiteSpace: 'pre-wrap' }}>
                  {milestone.links || 'No links added.'}
                </p>
              </div>
            </div>
          </>
        ) : null}
      </article>
    </section>
  )
}

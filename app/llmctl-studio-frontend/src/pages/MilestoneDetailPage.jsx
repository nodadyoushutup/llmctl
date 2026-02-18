import { useEffect, useMemo, useState } from 'react'
import { useFlash, useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import ArtifactHistoryTable from '../components/ArtifactHistoryTable'
import { deleteMilestone, deleteMilestoneArtifact, getMilestone, getMilestoneArtifacts } from '../lib/studioApi'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function parseNonNegativeInt(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null
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
  const flash = useFlash()
  const { milestoneId } = useParams()
  const parsedMilestoneId = useMemo(() => parseId(milestoneId), [milestoneId])
  const [state, setState] = useState({ loading: true, payload: null, artifactsPayload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [deletingArtifactId, setDeletingArtifactId] = useState(null)

  useEffect(() => {
    if (!parsedMilestoneId) {
      return
    }
    let cancelled = false
    Promise.allSettled([
      getMilestone(parsedMilestoneId),
      getMilestoneArtifacts(parsedMilestoneId, { limit: 25 }),
    ])
      .then(([payloadResult, artifactsResult]) => {
        if (payloadResult.status !== 'fulfilled') {
          throw payloadResult.reason
        }
        if (!cancelled) {
          setState({
            loading: false,
            payload: payloadResult.value,
            artifactsPayload: artifactsResult.status === 'fulfilled' ? artifactsResult.value : { items: [] },
            error: '',
          })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            artifactsPayload: null,
            error: errorMessage(error, 'Failed to load milestone.'),
          })
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
  const artifactsPayload = state.artifactsPayload && typeof state.artifactsPayload === 'object'
    ? state.artifactsPayload
    : null
  const artifacts = artifactsPayload && Array.isArray(artifactsPayload.items) ? artifactsPayload.items : []
  const totalArtifactCount = parseNonNegativeInt(artifactsPayload?.total_count) ?? artifacts.length
  const latestArtifact = artifacts.length > 0 ? artifacts[0] : null
  const latestArtifactAction = String(latestArtifact?.payload?.action || '').trim() || '-'

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

  async function handleDeleteArtifact(artifact) {
    if (!milestone) {
      return
    }
    const artifactId = parseId(artifact?.id)
    if (artifactId == null) {
      return
    }
    setDeletingArtifactId(artifactId)
    try {
      await deleteMilestoneArtifact(milestone.id, artifactId)
      setState((current) => {
        const currentArtifactsPayload = current.artifactsPayload && typeof current.artifactsPayload === 'object'
          ? current.artifactsPayload
          : {}
        const currentItems = Array.isArray(currentArtifactsPayload.items)
          ? currentArtifactsPayload.items
          : []
        return {
          ...current,
          artifactsPayload: {
            ...currentArtifactsPayload,
            items: currentItems.filter((item) => parseId(item?.id) !== artifactId),
          },
        }
      })
      flash.success(`Artifact ${artifactId} deleted.`)
    } catch (error) {
      flash.error(errorMessage(error, 'Failed to delete artifact history item.'))
    } finally {
      setDeletingArtifactId(null)
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
                <p className="eyebrow">artifact summary</p>
                <div className="stack" style={{ marginTop: '12px', fontSize: '12px' }}>
                  <p className="muted">Triggered runs: {totalArtifactCount}</p>
                  <p className="muted">Latest artifact action: {latestArtifactAction}</p>
                  <p className="muted">Latest artifact created: {latestArtifact?.created_at || '-'}</p>
                  <p className="muted">Canonical milestone updates are recorded per artifact.</p>
                </div>
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

            <div className="subcard" style={{ marginTop: '20px' }}>
              <p className="eyebrow">{`artifact history · ${totalArtifactCount} total`}</p>
              <ArtifactHistoryTable
                artifacts={artifacts}
                emptyMessage="No artifact history yet for this milestone."
                hrefForArtifact={(artifact) => `/milestones/${milestone.id}/artifacts/${artifact.id}`}
                onDeleteArtifact={handleDeleteArtifact}
                deletingArtifactId={deletingArtifactId}
              />
            </div>
          </>
        ) : null}
      </article>
    </section>
  )
}

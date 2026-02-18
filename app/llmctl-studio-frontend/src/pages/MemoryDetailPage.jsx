import { useEffect, useMemo, useState } from 'react'
import ActionIcon from '../components/ActionIcon'
import ArtifactHistoryTable from '../components/ArtifactHistoryTable'
import { useFlash, useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { deleteMemory, deleteMemoryArtifact, getMemory, getMemoryHistory } from '../lib/studioApi'

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

export default function MemoryDetailPage() {
  const navigate = useNavigate()
  const flash = useFlash()
  const { memoryId } = useParams()
  const [searchParams] = useSearchParams()
  const parsedMemoryId = useMemo(() => parseId(memoryId), [memoryId])
  const selectedFlowchartNodeId = useMemo(
    () => parseId(searchParams.get('flowchart_node_id')),
    [searchParams],
  )
  const [state, setState] = useState({ loading: true, memoryPayload: null, historyPayload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [deletingArtifactId, setDeletingArtifactId] = useState(null)

  useEffect(() => {
    if (!parsedMemoryId) {
      return
    }
    let cancelled = false
    const historyPromise = selectedFlowchartNodeId
      ? getMemoryHistory(parsedMemoryId, { flowchartNodeId: selectedFlowchartNodeId })
      : getMemoryHistory(parsedMemoryId)
    Promise.all([getMemory(parsedMemoryId), historyPromise])
      .then(([memoryPayload, historyPayload]) => {
        if (!cancelled) {
          setState({ loading: false, memoryPayload, historyPayload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            memoryPayload: null,
            historyPayload: null,
            error: errorMessage(error, 'Failed to load memory.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMemoryId, selectedFlowchartNodeId])

  const invalidId = parsedMemoryId == null
  const payload = state.memoryPayload && typeof state.memoryPayload === 'object' ? state.memoryPayload : null
  const historyPayload = state.historyPayload && typeof state.historyPayload === 'object'
    ? state.historyPayload
    : null
  const memory = payload && payload.memory && typeof payload.memory === 'object' ? payload.memory : null
  const artifacts = historyPayload && Array.isArray(historyPayload.artifacts) ? historyPayload.artifacts : []

  async function handleDelete() {
    if (!memory || !window.confirm('Delete this memory?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteMemory(memory.id)
      flash.success('Memory deleted.')
      navigate('/memories')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete memory.'))
    }
  }

  async function handleDeleteArtifact(artifact) {
    if (!memory) {
      return
    }
    const artifactId = parseId(artifact?.id)
    if (artifactId == null) {
      return
    }
    setDeletingArtifactId(artifactId)
    try {
      await deleteMemoryArtifact(memory.id, artifactId)
      setState((current) => {
        const currentHistory = current.historyPayload && typeof current.historyPayload === 'object'
          ? current.historyPayload
          : null
        const currentArtifacts = currentHistory && Array.isArray(currentHistory.artifacts)
          ? currentHistory.artifacts
          : []
        return {
          ...current,
          historyPayload: {
            ...(currentHistory || {}),
            artifacts: currentArtifacts.filter((item) => parseId(item?.id) !== artifactId),
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

  return (
    <section className="stack" aria-label="Memory detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            <Link to="/memories" className="icon-button" aria-label="Back to memories" title="Back to memories">
              <i className="fa-solid fa-arrow-left" />
            </Link>
            {memory ? (
              <Link
                to={`/memories/${memory.id}/edit`}
                className="icon-button"
                aria-label="Edit memory"
                title="Edit memory"
              >
                <ActionIcon name="edit" />
              </Link>
            ) : null}
            {memory ? (
              <button
                type="button"
                className="icon-button icon-button-danger"
                disabled={busy}
                aria-label="Delete memory"
                title="Delete memory"
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
            ) : null}
          </div>
        </div>

        {(!invalidId && state.loading) ? <p>Loading memory...</p> : null}
        {(invalidId || state.error) ? (
          <p className="error-text">{invalidId ? 'Invalid memory id.' : state.error}</p>
        ) : null}

        {memory ? (
          <>
            <div className="card-header">
              <div>
                <p className="eyebrow">memory {memory.id}</p>
                <h2 className="section-title">Memory</h2>
              </div>
            </div>

            <div className="grid grid-2" style={{ marginTop: '20px' }}>
              <div className="subcard">
                <p className="eyebrow">details</p>
                <div className="stack" style={{ marginTop: '12px', fontSize: '12px' }}>
                  <p className="muted">Created: {memory.created_at || '-'}</p>
                  <p className="muted">Updated: {memory.updated_at || '-'}</p>
                </div>
              </div>
              <div className="subcard">
                <p className="eyebrow">description</p>
                <p className="muted" style={{ marginTop: '12px', whiteSpace: 'pre-wrap' }}>
                  {memory.description || '-'}
                </p>
              </div>
            </div>
            <div className="subcard" style={{ marginTop: '20px' }}>
              <p className="eyebrow">
                {selectedFlowchartNodeId ? `artifact history (node ${selectedFlowchartNodeId})` : 'artifact history'}
              </p>
              <ArtifactHistoryTable
                artifacts={artifacts}
                emptyMessage="No artifact history yet for this memory."
                hrefForArtifact={(artifact) => `/memories/${memory.id}/artifacts/${artifact.id}`}
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

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { deleteMemory, getMemory } from '../lib/studioApi'

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
  const { memoryId } = useParams()
  const parsedMemoryId = useMemo(() => parseId(memoryId), [memoryId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!parsedMemoryId) {
      return
    }
    let cancelled = false
    getMemory(parsedMemoryId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load memory.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMemoryId])

  const invalidId = parsedMemoryId == null
  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const memory = payload && payload.memory && typeof payload.memory === 'object' ? payload.memory : null

  async function handleDelete() {
    if (!memory || !window.confirm('Delete this memory?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteMemory(memory.id)
      navigate('/memories')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete memory.'))
    }
  }

  return (
    <section className="stack" aria-label="Memory detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            <Link to="/memories" className="btn btn-secondary">
              <i className="fa-solid fa-arrow-left" />
              back
            </Link>
            {memory ? (
              <Link to={`/memories/${memory.id}/edit`} className="btn btn-secondary">
                <i className="fa-solid fa-pen-to-square" />
                edit
              </Link>
            ) : null}
            {memory ? (
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

        {(!invalidId && state.loading) ? <p>Loading memory...</p> : null}
        {(invalidId || state.error) ? (
          <p className="error-text">{invalidId ? 'Invalid memory id.' : state.error}</p>
        ) : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}

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
          </>
        ) : null}
      </article>
    </section>
  )
}

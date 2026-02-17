import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
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

  const refresh = useCallback(async () => {
    if (!parsedMemoryId) {
      setState({ loading: false, payload: null, error: 'Invalid memory id.' })
      return
    }
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getMemory(parsedMemoryId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load memory.') })
    }
  }, [parsedMemoryId])

  useEffect(() => {
    refresh()
  }, [refresh])

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
        <div className="title-row">
          <div>
            <h2>Memory</h2>
            <p>Native React detail view for `/memories/:memoryId`.</p>
          </div>
          <div className="table-actions">
            {memory ? <Link to={`/memories/${memory.id}/edit`} className="btn-link btn-secondary">Edit</Link> : null}
            <Link to="/memories" className="btn-link btn-secondary">All Memories</Link>
            {memory ? (
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete memory"
                title="Delete memory"
                disabled={busy}
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
            ) : null}
          </div>
        </div>
        {state.loading ? <p>Loading memory...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {memory ? (
          <dl className="kv-grid">
            <div>
              <dt>Created</dt>
              <dd>{memory.created_at || '-'}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{memory.updated_at || '-'}</dd>
            </div>
            <div>
              <dt>Description</dt>
              <dd>{memory.description || '-'}</dd>
            </div>
          </dl>
        ) : null}
      </article>
    </section>
  )
}

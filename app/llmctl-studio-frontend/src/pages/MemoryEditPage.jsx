import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMemoryEdit, updateMemory } from '../lib/studioApi'

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

export default function MemoryEditPage() {
  const navigate = useNavigate()
  const { memoryId } = useParams()
  const parsedMemoryId = useMemo(() => parseId(memoryId), [memoryId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [saving, setSaving] = useState(false)
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!parsedMemoryId) {
      setState({ loading: false, payload: null, error: 'Invalid memory id.' })
      return
    }
    let cancelled = false
    getMemoryEdit(parsedMemoryId)
      .then((payload) => {
        if (!cancelled) {
          const memory = payload && payload.memory && typeof payload.memory === 'object'
            ? payload.memory
            : null
          setState({ loading: false, payload, error: '' })
          if (memory) {
            setDescription(String(memory.description || ''))
          }
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load memory edit data.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedMemoryId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const memory = payload && payload.memory && typeof payload.memory === 'object' ? payload.memory : null

  async function handleSubmit(event) {
    event.preventDefault()
    if (!parsedMemoryId) {
      return
    }
    setActionError('')
    setSaving(true)
    try {
      await updateMemory(parsedMemoryId, { description })
      navigate(`/memories/${parsedMemoryId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update memory.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="stack" aria-label="Edit memory">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <div className="table-actions">
            {memory ? (
              <Link to={`/memories/${memory.id}`} className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back to memory
              </Link>
            ) : null}
            <Link to="/memories" className="btn btn-secondary">
              <i className="fa-solid fa-list" />
              all memories
            </Link>
          </div>
        </div>

        <div className="card-header">
          <div>
            {memory ? <p className="eyebrow">memory {memory.id}</p> : null}
            <h2 className="section-title">Edit Memory</h2>
          </div>
        </div>

        <p className="muted" style={{ marginTop: '12px' }}>
          Update the stored memory description.
        </p>

        {state.loading ? <p style={{ marginTop: '20px' }}>Loading memory...</p> : null}
        {state.error ? <p className="error-text" style={{ marginTop: '12px' }}>{state.error}</p> : null}

        {!state.loading && !state.error ? (
          <form className="form-grid" style={{ marginTop: '20px' }} onSubmit={handleSubmit}>
            <label className="field field-span">
              <span>description</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={saving}>
                <i className="fa-solid fa-floppy-disk" />
                {saving ? 'saving...' : 'save'}
              </button>
              {memory ? (
                <Link className="btn btn-secondary" to={`/memories/${memory.id}`}>
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

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { getMemories } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
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

export default function MemoriesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 20)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getMemories({ page, perPage })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load memories.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [page, perPage])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const memories = payload && Array.isArray(payload.memories) ? payload.memories : []
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object'
    ? payload.pagination
    : null
  const totalPages = Number.isInteger(pagination?.total_pages) && pagination.total_pages > 0
    ? pagination.total_pages
    : 1
  const totalCount = Number.isInteger(pagination?.total_count) ? pagination.total_count : 0

  function updateParams(nextParams) {
    const updated = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(nextParams)) {
      if (value == null || value === '') {
        updated.delete(key)
      } else {
        updated.set(key, String(value))
      }
    }
    setSearchParams(updated)
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Memories">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Memories</h2>
            <p>Native React replacement for `/memories` list and detail navigation.</p>
          </div>
          <Link to="/memories/new" className="btn-link btn-secondary">Create Policy</Link>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            <button
              type="button"
              className="btn-link btn-secondary"
              disabled={page <= 1}
              onClick={() => updateParams({ page: page - 1, per_page: perPage })}
            >
              Prev
            </button>
            <span className="toolbar-meta">Page {Math.min(page, totalPages)} / {totalPages}</span>
            <button
              type="button"
              className="btn-link btn-secondary"
              disabled={page >= totalPages}
              onClick={() => updateParams({ page: page + 1, per_page: perPage })}
            >
              Next
            </button>
          </div>
          <span className="toolbar-meta">Total memories: {totalCount}</span>
        </div>
        {state.loading ? <p>Loading memories...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && memories.length === 0 ? (
          <p>No memories found yet. Add a Memory node in a flowchart to create one.</p>
        ) : null}
        {!state.loading && !state.error && memories.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Created</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {memories.map((memory) => {
                  const href = `/memories/${memory.id}`
                  return (
                    <tr
                      key={memory.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{memory.description}</Link>
                      </td>
                      <td>{memory.created_at || '-'}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <Link
                            to={`/memories/${memory.id}/edit`}
                            className="icon-button"
                            aria-label="Edit memory"
                            title="Edit memory"
                          >
                            <ActionIcon name="edit" />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}

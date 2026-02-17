import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getMilestones } from '../lib/studioApi'
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

export default function MilestonesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 20)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getMilestones({ page, perPage })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load milestones.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [page, perPage])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const milestones = payload && Array.isArray(payload.milestones) ? payload.milestones : []
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
    <section className="stack" aria-label="Milestones">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Milestones</h2>
            <p>Native React replacement for `/milestones` list and detail navigation.</p>
          </div>
          <Link to="/milestones/new" className="btn-link btn-secondary">Create Policy</Link>
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
          <span className="toolbar-meta">Total milestones: {totalCount}</span>
        </div>
        {state.loading ? <p>Loading milestones...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && milestones.length === 0 ? (
          <p>No milestones found yet. Add a Milestone node in a flowchart to create one.</p>
        ) : null}
        {!state.loading && !state.error && milestones.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Owner</th>
                  <th>Progress</th>
                  <th>Due date</th>
                </tr>
              </thead>
              <tbody>
                {milestones.map((milestone) => {
                  const href = `/milestones/${milestone.id}`
                  return (
                    <tr
                      key={milestone.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{milestone.name}</Link>
                      </td>
                      <td>
                        <span className={milestone.status_class || 'status-chip status-idle'}>
                          {milestone.status_label || milestone.status || '-'}
                        </span>
                      </td>
                      <td>{milestone.priority_label || '-'}</td>
                      <td>{milestone.owner || '-'}</td>
                      <td>{milestone.progress_percent ?? 0}%</td>
                      <td>{milestone.due_date || '-'}</td>
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

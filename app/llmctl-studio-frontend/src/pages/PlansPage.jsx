import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { getPlans } from '../lib/studioApi'
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

export default function PlansPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 20)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getPlans({ page, perPage })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load plans.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [page, perPage])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const plans = payload && Array.isArray(payload.plans) ? payload.plans : []
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object'
    ? payload.pagination
    : null
  const totalPages = Number.isInteger(pagination?.total_pages) && pagination.total_pages > 0
    ? pagination.total_pages
    : 1
  const paginationItems = Array.isArray(pagination?.items) ? pagination.items : []

  function truncateText(value, max = 140) {
    const text = String(value || '').trim()
    if (!text || text.length <= max) {
      return text
    }
    return `${text.slice(0, max - 3)}...`
  }

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
    <section className="stack" aria-label="Plans">
      <article className="card workflow-list-card">
        <div className="pagination-bar pagination-bar-header">
          <nav className="pagination" aria-label="Plans pages">
            {page > 1 ? (
              <button
                type="button"
                className="pagination-btn"
                onClick={() => updateParams({ page: page - 1, per_page: perPage })}
              >
                Prev
              </button>
            ) : (
              <span className="pagination-btn is-disabled" aria-disabled="true">Prev</span>
            )}
            <div className="pagination-pages">
              {paginationItems.map((item, index) => {
                const itemType = String(item?.type || '')
                if (itemType === 'gap') {
                  return <span key={`gap-${index}`} className="pagination-ellipsis">&hellip;</span>
                }
                const itemPage = Number.parseInt(String(item?.page || ''), 10)
                if (!Number.isInteger(itemPage) || itemPage <= 0) {
                  return null
                }
                if (itemPage === page) {
                  return <span key={itemPage} className="pagination-link is-active" aria-current="page">{itemPage}</span>
                }
                return (
                  <button
                    key={itemPage}
                    type="button"
                    className="pagination-link"
                    onClick={() => updateParams({ page: itemPage, per_page: perPage })}
                  >
                    {itemPage}
                  </button>
                )
              })}
            </div>
            {page < totalPages ? (
              <button
                type="button"
                className="pagination-btn"
                onClick={() => updateParams({ page: page + 1, per_page: perPage })}
              >
                Next
              </button>
            ) : (
              <span className="pagination-btn is-disabled" aria-disabled="true">Next</span>
            )}
          </nav>
        </div>
        <div className="card-header">
          <div>
            <h2 className="section-title">Plans</h2>
          </div>
        </div>
        <p className="muted" style={{ marginTop: '12px' }}>
          Track multi-stage plans and task completion with explicit completion timestamps.
        </p>
        {state.loading ? <p>Loading plans...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && plans.length === 0 ? (
          <p className="muted" style={{ marginTop: '16px' }}>
            No plans found yet. Add a Plan node in a flowchart to create one.
          </p>
        ) : null}
        {!state.loading && !state.error && plans.length > 0 ? (
          <div className="workflow-list-table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>Completed</th>
                  <th>Stages</th>
                  <th>Tasks</th>
                  <th className="table-actions-cell">Edit</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => {
                  const href = `/plans/${plan.id}`
                  return (
                    <tr
                      key={plan.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{plan.name}</Link>
                        {plan.description ? <p className="table-note">{truncateText(plan.description)}</p> : null}
                      </td>
                      <td className="muted">{plan.completed_at || '-'}</td>
                      <td className="muted">{plan.stage_count || 0}</td>
                      <td className="muted">{plan.task_count || 0}</td>
                      <td className="table-actions-cell">
                        <Link
                          to={`/plans/${plan.id}/edit`}
                          className="icon-button"
                          aria-label="Edit plan"
                          title="Edit plan"
                        >
                          <ActionIcon name="edit" />
                        </Link>
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

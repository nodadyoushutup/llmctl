import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { deletePlan, getPlans } from '../lib/studioApi'
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
  const [actionError, setActionError] = useState('')
  const [busyPlanId, setBusyPlanId] = useState(null)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getPlans({ page, perPage })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load plans.'),
      }))
    }
  }, [page, perPage])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const plans = payload && Array.isArray(payload.plans) ? payload.plans : []
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

  async function handleDelete(planId) {
    if (!window.confirm('Delete this plan?')) {
      return
    }
    setActionError('')
    setBusyPlanId(planId)
    try {
      await deletePlan(planId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete plan.'))
    } finally {
      setBusyPlanId(null)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Plans">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Plans</h2>
            <p>Native React replacement for `/plans` list and plan actions.</p>
          </div>
          <Link to="/plans/new" className="btn-link btn-secondary">Create Policy</Link>
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
          <span className="toolbar-meta">Total plans: {totalCount}</span>
        </div>
        {state.loading ? <p>Loading plans...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {!state.loading && !state.error && plans.length === 0 ? (
          <p>No plans found yet. Add a Plan node in a flowchart to create one.</p>
        ) : null}
        {!state.loading && !state.error && plans.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Plan</th>
                  <th>Completed</th>
                  <th>Stages</th>
                  <th>Tasks</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => {
                  const href = `/plans/${plan.id}`
                  const busy = busyPlanId === plan.id
                  return (
                    <tr
                      key={plan.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link to={href}>{plan.name}</Link>
                        {plan.description ? <p className="table-note">{plan.description}</p> : null}
                      </td>
                      <td>{plan.completed_at || '-'}</td>
                      <td>{plan.stage_count || 0}</td>
                      <td>{plan.task_count || 0}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <Link
                            to={`/plans/${plan.id}/edit`}
                            className="icon-button"
                            aria-label="Edit plan"
                            title="Edit plan"
                          >
                            <ActionIcon name="save" />
                          </Link>
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete plan"
                            title="Delete plan"
                            disabled={busy}
                            onClick={() => handleDelete(plan.id)}
                          >
                            <ActionIcon name="trash" />
                          </button>
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

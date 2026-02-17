import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getTaskTemplates } from '../lib/studioApi'
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

export default function TaskTemplatesPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePositiveInt(searchParams.get('per_page'), 20)

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getTaskTemplates({ page, perPage })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load workflow nodes.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [page, perPage])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const taskNodes = payload && Array.isArray(payload.task_nodes) ? payload.task_nodes : []
  const pagination = payload && payload.pagination && typeof payload.pagination === 'object'
    ? payload.pagination
    : null
  const totalPages = Number.isInteger(pagination?.total_pages) && pagination.total_pages > 0
    ? pagination.total_pages
    : 1
  const paginationItems = Array.isArray(pagination?.items) ? pagination.items : []

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
    <section className="stack" aria-label="Task templates">
      <article className="card workflow-list-card">
        <div className="pagination-bar pagination-bar-header">
          <nav className="pagination" aria-label="Tasks pages">
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
            <h2 className="section-title">Workflow Nodes</h2>
          </div>
        </div>
        {state.loading ? <p>Loading workflow nodes...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && taskNodes.length === 0 ? (
          <p className="muted">
            No workflow nodes found yet. Add a Task or RAG node in any flowchart.
          </p>
        ) : null}
        {!state.loading && !state.error && taskNodes.length > 0 ? (
          <div className="workflow-list-table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Flowchart</th>
                  <th>Prompt</th>
                </tr>
              </thead>
              <tbody>
                {taskNodes.map((node) => {
                  const href = `/flowcharts/${node.flowchart_id}?node=${node.node_id}`
                  return (
                    <tr
                      key={`${node.flowchart_id}-${node.node_id}`}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <p>
                          <a href={href}>{node.task_name}</a>
                        </p>
                      </td>
                      <td className="muted">{node.node_type || '-'}</td>
                      <td className="muted">{node.flowchart_name || '-'}</td>
                      <td className="muted">{node.prompt_preview || '-'}</td>
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

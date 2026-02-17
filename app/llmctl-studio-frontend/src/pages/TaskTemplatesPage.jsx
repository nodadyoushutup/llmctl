import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
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

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getTaskTemplates({ page, perPage })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load workflow nodes.') })
    }
  }, [page, perPage])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const taskNodes = payload && Array.isArray(payload.task_nodes) ? payload.task_nodes : []
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
    <section className="stack" aria-label="Task templates">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Workflow Nodes</h2>
            <p>Native React replacement for `/task-templates` node list surface.</p>
          </div>
          <Link to="/task-templates/new" className="btn-link btn-secondary">Create Policy</Link>
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
          <span className="toolbar-meta">Total nodes: {totalCount}</span>
        </div>
        {state.loading ? <p>Loading workflow nodes...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && taskNodes.length === 0 ? (
          <p>No workflow nodes found yet. Add a Task or RAG node in any flowchart.</p>
        ) : null}
        {!state.loading && !state.error && taskNodes.length > 0 ? (
          <div className="table-wrap">
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
                        <a href={href}>{node.task_name}</a>
                      </td>
                      <td>{node.node_type || '-'}</td>
                      <td>{node.flowchart_name || '-'}</td>
                      <td>{node.prompt_preview || '-'}</td>
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

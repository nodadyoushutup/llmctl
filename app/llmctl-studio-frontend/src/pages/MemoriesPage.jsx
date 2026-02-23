import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import PanelHeader from '../components/PanelHeader'
import TableListEmptyState from '../components/TableListEmptyState'
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
  const paginationItems = Array.isArray(pagination?.items) ? pagination.items : []

  function truncateText(value, max = 180) {
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
    <section className="stack workflow-fixed-page" aria-label="Memories">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="Memories"
          actionsClassName="workflow-list-panel-header-actions"
          actions={(
            <HeaderPagination
              ariaLabel="Memories pages"
              canGoPrev={page > 1}
              canGoNext={page < totalPages}
              onPrev={() => updateParams({ page: page - 1, per_page: perPage })}
              onNext={() => updateParams({ page: page + 1, per_page: perPage })}
              currentPage={page}
              pageItems={paginationItems}
              onPageSelect={(itemPage) => updateParams({ page: itemPage, per_page: perPage })}
            />
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          {state.loading ? <p>Loading memories...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {!state.loading && !state.error ? (
            <div className="workflow-list-table-shell">
              {memories.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Description</th>
                        <th>Flowchart</th>
                        <th>Created</th>
                        <th className="table-actions-cell">Edit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {memories.map((memory) => {
                        const memoryId = parsePositiveInt(memory?.id, 0)
                        if (memoryId < 1) {
                          return null
                        }
                        const flowchartNodeId = parsePositiveInt(memory?.flowchart_node_id, 0)
                        const href = flowchartNodeId > 0
                          ? `/memories/${memoryId}?flowchart_node_id=${flowchartNodeId}`
                          : `/memories/${memoryId}`
                        const rowKey = flowchartNodeId > 0 ? `${memoryId}-${flowchartNodeId}` : String(memoryId)
                        return (
                          <tr
                            key={rowKey}
                            className="table-row-link"
                            data-href={href}
                            onClick={(event) => handleRowClick(event, href)}
                          >
                            <td>
                              <p>{truncateText(memory.description)}</p>
                            </td>
                            <td>
                              <p>{memory.flowchart_name || '-'}</p>
                            </td>
                            <td>
                              <p className="muted" style={{ fontSize: '12px' }}>{memory.created_at || '-'}</p>
                            </td>
                            <td className="table-actions-cell">
                              <button
                                type="button"
                                className="icon-button"
                                aria-label="Edit memory"
                                title="Edit memory"
                                onClick={() => navigate(`/memories/${memoryId}/edit`)}
                              >
                                <ActionIcon name="edit" />
                              </button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <TableListEmptyState message="No memory nodes found yet. Add a Memory node in a flowchart to create one." />
              )}
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

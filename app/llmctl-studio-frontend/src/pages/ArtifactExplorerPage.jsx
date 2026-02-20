import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getNodeArtifacts } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const ARTIFACT_TYPE_OPTIONS = [
  { value: 'task', label: 'Task' },
  { value: 'plan', label: 'Plan' },
  { value: 'milestone', label: 'Milestone' },
  { value: 'memory', label: 'Memory' },
  { value: 'decision', label: 'Decision' },
  { value: 'rag', label: 'RAG' },
]

const NODE_TYPE_OPTIONS = [
  { value: '', label: 'all node types' },
  { value: 'start', label: 'Start' },
  { value: 'task', label: 'Task' },
  { value: 'plan', label: 'Plan' },
  { value: 'milestone', label: 'Milestone' },
  { value: 'memory', label: 'Memory' },
  { value: 'decision', label: 'Decision' },
  { value: 'rag', label: 'RAG' },
  { value: 'flowchart', label: 'Flowchart' },
  { value: 'end', label: 'End' },
]

const SUPPORTED_ARTIFACT_TYPES = new Set(ARTIFACT_TYPE_OPTIONS.map((option) => option.value))
const SUPPORTED_NODE_TYPES = new Set(NODE_TYPE_OPTIONS.filter((option) => option.value).map((option) => option.value))

function parsePositiveInt(value, fallback = null) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  if (!Number.isInteger(parsed) || parsed < 1) {
    return fallback
  }
  return parsed
}

function normalizeArtifactType(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized || normalized === 'all') {
    return ''
  }
  if (SUPPORTED_ARTIFACT_TYPES.has(normalized)) {
    return normalized
  }
  return null
}

function normalizeNodeType(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) {
    return ''
  }
  if (SUPPORTED_NODE_TYPES.has(normalized)) {
    return normalized
  }
  return ''
}

function typeLabel(type) {
  const normalized = String(type || '').trim().toLowerCase()
  const option = ARTIFACT_TYPE_OPTIONS.find((item) => item.value === normalized)
  return option ? option.label : 'Artifacts'
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

export default function ArtifactExplorerPage() {
  const navigate = useNavigate()
  const params = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  const routeArtifactType = normalizeArtifactType(params.artifactType)
  const nodeTypeFilter = normalizeNodeType(searchParams.get('node_type'))
  const runIdFilter = parsePositiveInt(searchParams.get('flowchart_run_id'))
  const limit = parsePositiveInt(searchParams.get('limit'), 50) || 50
  const offset = parsePositiveInt(searchParams.get('offset'), 0) || 0

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (routeArtifactType === null) {
      setState({ loading: false, payload: null, error: 'Unsupported artifact type route.' })
      return
    }
    let cancelled = false
    getNodeArtifacts({
      limit,
      offset,
      artifactType: routeArtifactType,
      nodeType: nodeTypeFilter,
      flowchartRunId: runIdFilter,
      order: 'desc',
    })
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            loading: false,
            payload: null,
            error: errorMessage(error, 'Failed to load artifacts.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [limit, nodeTypeFilter, offset, routeArtifactType, runIdFilter])

  const title = useMemo(() => {
    if (!routeArtifactType) {
      return 'Artifacts'
    }
    return `${typeLabel(routeArtifactType)} Artifacts`
  }, [routeArtifactType])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const items = payload && Array.isArray(payload.items) ? payload.items : []
  const totalCount = parsePositiveInt(payload?.total_count, 0) || 0
  const canGoPrev = offset > 0
  const canGoNext = offset + items.length < totalCount

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

  function applyFilters(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const nextNodeType = normalizeNodeType(formData.get('node_type'))
    const nextRunId = parsePositiveInt(formData.get('flowchart_run_id'))
    updateParams({
      node_type: nextNodeType,
      flowchart_run_id: nextRunId,
      offset: 0,
      limit,
    })
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams())
  }

  function handleRowClick(event, href) {
    if (!href || shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack workflow-fixed-page" aria-label={title}>
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title={title}
          actionsClassName="workflow-list-panel-header-actions"
          actions={(
            <nav className="pagination" aria-label="Artifact pages">
              {canGoPrev ? (
                <button
                  type="button"
                  className="pagination-btn"
                  onClick={() => updateParams({ offset: Math.max(0, offset - limit), limit })}
                >
                  Prev
                </button>
              ) : (
                <span className="pagination-btn is-disabled" aria-disabled="true">Prev</span>
              )}
              {canGoNext ? (
                <button
                  type="button"
                  className="pagination-btn"
                  onClick={() => updateParams({ offset: offset + limit, limit })}
                >
                  Next
                </button>
              ) : (
                <span className="pagination-btn is-disabled" aria-disabled="true">Next</span>
              )}
            </nav>
          )}
        />

        <div className="panel-card-body workflow-fixed-panel-body">
          <form className="form-grid" onSubmit={applyFilters}>
            <div className="toolbar toolbar-wrap" style={{ margin: 0 }}>
              <div className="toolbar-group">
                <label htmlFor="artifact-node-type-filter">Node type</label>
                <select
                  id="artifact-node-type-filter"
                  name="node_type"
                  defaultValue={nodeTypeFilter}
                >
                  {NODE_TYPE_OPTIONS.map((option) => (
                    <option key={`node-type-${option.value || 'all'}`} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="toolbar-group">
                <label htmlFor="artifact-run-id-filter">Run id</label>
                <input
                  id="artifact-run-id-filter"
                  name="flowchart_run_id"
                  defaultValue={runIdFilter || ''}
                  placeholder="all runs"
                  inputMode="numeric"
                />
              </div>
            </div>
            <div className="toolbar" style={{ justifyContent: 'flex-start', margin: 0 }}>
              <button type="submit" className="btn-link btn-secondary">
                <i className="fa-solid fa-filter" />
                filter
              </button>
              <button type="button" className="btn-link" onClick={resetFilters}>
                <i className="fa-solid fa-rotate-right" />
                reset
              </button>
              <span className="muted">{`${items.length} shown / ${totalCount} total`}</span>
            </div>
          </form>

          {state.loading ? <p>Loading artifacts...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {!state.loading && !state.error && items.length === 0 ? (
            <p className="muted">No artifacts found for this filter set.</p>
          ) : null}

          {!state.loading && !state.error && items.length > 0 ? (
            <div className="table-wrap workflow-list-table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Artifact</th>
                    <th>Type</th>
                    <th>Node type</th>
                    <th>Ref</th>
                    <th>Flowchart</th>
                    <th>Run</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((artifact) => {
                    const artifactId = parsePositiveInt(artifact?.id)
                    if (!artifactId) {
                      return null
                    }
                    const href = `/artifacts/item/${artifactId}`
                    const action = String((artifact?.payload || {}).action || '').trim()
                    return (
                      <tr
                        key={`artifact-${artifactId}`}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{`Artifact ${artifactId}`}</Link>
                          {action ? <p className="table-note">{action}</p> : null}
                        </td>
                        <td>{artifact.artifact_type || '-'}</td>
                        <td>{artifact.node_type || '-'}</td>
                        <td>{artifact.ref_id || '-'}</td>
                        <td>{artifact.flowchart_id || '-'}</td>
                        <td>{artifact.flowchart_run_id || '-'}</td>
                        <td>{artifact.created_at || '-'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

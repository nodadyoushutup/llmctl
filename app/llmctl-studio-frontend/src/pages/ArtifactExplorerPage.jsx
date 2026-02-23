import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import HeaderPagination from '../components/HeaderPagination'
import TableListEmptyState from '../components/TableListEmptyState'
import TwoColumnListShell from '../components/TwoColumnListShell'
import { HttpError } from '../lib/httpClient'
import { getNodeArtifacts } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const ARTIFACT_TYPE_OPTIONS = [
  { value: 'task', label: 'Task', icon: 'fa-solid fa-list-check' },
  { value: 'plan', label: 'Plan', icon: 'fa-solid fa-map' },
  { value: 'milestone', label: 'Milestone', icon: 'fa-solid fa-flag-checkered' },
  { value: 'memory', label: 'Memory', icon: 'fa-solid fa-brain' },
  { value: 'decision', label: 'Decision', icon: 'fa-solid fa-code-branch' },
  { value: 'rag', label: 'RAG', icon: 'fa-solid fa-database' },
]

const SUPPORTED_ARTIFACT_TYPES = new Set(ARTIFACT_TYPE_OPTIONS.map((option) => option.value))

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
  const flowchartIdFilter = parsePositiveInt(searchParams.get('flowchart_id'))
  const flowchartNodeIdFilter = parsePositiveInt(searchParams.get('flowchart_node_id'))
  const limit = parsePositiveInt(searchParams.get('limit'), 50) || 50
  const offset = parsePositiveInt(searchParams.get('offset'), 0) || 0

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (routeArtifactType === null) {
      setState({ loading: false, payload: null, error: 'Unsupported artifact type route.' })
      return
    }
    let cancelled = false
    const request = {
      limit,
      offset,
      artifactType: routeArtifactType,
      order: 'desc',
    }
    if (flowchartIdFilter) {
      request.flowchartId = flowchartIdFilter
    }
    if (flowchartNodeIdFilter) {
      request.flowchartNodeId = flowchartNodeIdFilter
    }
    getNodeArtifacts({
      ...request,
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
  }, [flowchartIdFilter, flowchartNodeIdFilter, limit, offset, routeArtifactType])

  const title = useMemo(() => {
    if (!routeArtifactType) {
      return 'Artifacts'
    }
    return `${typeLabel(routeArtifactType)} Artifacts`
  }, [routeArtifactType])
  const artifactTypeSidebarItems = useMemo(() => {
    const scopedParams = new URLSearchParams()
    if (flowchartIdFilter) {
      scopedParams.set('flowchart_id', String(flowchartIdFilter))
    }
    if (flowchartNodeIdFilter) {
      scopedParams.set('flowchart_node_id', String(flowchartNodeIdFilter))
    }
    const queryString = scopedParams.toString()
    const querySuffix = queryString ? `?${queryString}` : ''
    return ARTIFACT_TYPE_OPTIONS.map((option) => ({
      id: option.value,
      label: option.label,
      icon: option.icon,
      to: `/artifacts/type/${option.value}${querySuffix}`,
    }))
  }, [flowchartIdFilter, flowchartNodeIdFilter])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const items = payload && Array.isArray(payload.items) ? payload.items : []
  const totalCount = parsePositiveInt(payload?.total_count, 0) || 0
  const hasItems = !state.loading && !state.error && items.length > 0
  const canGoPrev = offset > 0
  const canGoNext = offset + items.length < totalCount
  const currentPage = Math.floor(offset / limit) + 1
  const totalPages = Math.max(1, Math.ceil(totalCount / limit))

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
    if (!href || shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <TwoColumnListShell
      ariaLabel={title}
      className="provider-fixed-page"
      sidebarAriaLabel="Artifact types"
      sidebarTitle="Artifacts"
      sidebarItems={artifactTypeSidebarItems}
      activeSidebarId={routeArtifactType || ''}
      mainTitle={title}
      mainActions={(
        <div className="artifact-explorer-header-actions">
          <span className="panel-header-meta artifact-explorer-header-count">{`${items.length} shown / ${totalCount} total`}</span>
          <HeaderPagination
            ariaLabel="Artifact pages"
            canGoPrev={canGoPrev}
            canGoNext={canGoNext}
            onPrev={() => updateParams({ offset: Math.max(0, offset - limit), limit })}
            onNext={() => updateParams({ offset: offset + limit, limit })}
            currentPage={currentPage}
            totalPages={totalPages}
          />
        </div>
      )}
    >
      {state.loading ? <p>Loading artifacts...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}

      {!state.loading && !state.error ? (
        <div className="workflow-list-table-shell artifact-explorer-results-shell">
          {hasItems ? (
            <div className="table-wrap">
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
          ) : (
            <TableListEmptyState
              className="artifact-explorer-empty-state"
              message="No artifacts found for this filter set."
            />
          )}
        </div>
      ) : null}
    </TwoColumnListShell>
  )
}

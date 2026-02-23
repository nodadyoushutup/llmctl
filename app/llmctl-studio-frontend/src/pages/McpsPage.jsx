import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import TableListEmptyState from '../components/TableListEmptyState'
import TwoColumnListShell from '../components/TwoColumnListShell'
import { HttpError } from '../lib/httpClient'
import { deleteMcp, getMcps } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const SECTION_IDS = ['integrated', 'custom']
const MCP_PER_PAGE_OPTIONS = [10, 25, 50]

function normalizeSection(raw) {
  const normalized = String(raw || '').trim().toLowerCase()
  if (SECTION_IDS.includes(normalized)) {
    return normalized
  }
  return 'integrated'
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function parsePerPage(value) {
  const parsed = parsePositiveInt(value, 25)
  return MCP_PER_PAGE_OPTIONS.includes(parsed) ? parsed : 25
}

function sectionPath(sectionId, currentSearchParams) {
  const nextSearchParams = new URLSearchParams(currentSearchParams)
  nextSearchParams.delete('page')
  const nextSearch = nextSearchParams.toString()
  if (sectionId === 'custom') {
    return nextSearch ? `/mcps/custom?${nextSearch}` : '/mcps/custom'
  }
  return nextSearch ? `/mcps?${nextSearch}` : '/mcps'
}

function sectionTitle(sectionId) {
  if (sectionId === 'custom') {
    return 'Custom MCP Servers'
  }
  return 'Integrated MCP Servers'
}

function sectionDescription(sectionId) {
  if (sectionId === 'custom') {
    return 'User-managed MCP servers available for flowchart node bindings.'
  }
  return 'System-integrated MCP servers available for flowchart node bindings.'
}

function sectionIcon(sectionId) {
  if (sectionId === 'custom') {
    return 'fa-solid fa-sliders'
  }
  return 'fa-solid fa-puzzle-piece'
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

function McpTable({ rows, onDelete, busyById, navigate, allowDelete }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>MCP Server</th>
          <th>Key</th>
          <th>Description</th>
          <th>Bindings</th>
          {allowDelete ? <th className="table-actions-cell">Delete</th> : null}
        </tr>
      </thead>
      <tbody>
        {rows.map((mcp) => {
          const href = `/mcps/${mcp.id}`
          const busy = Boolean(busyById[mcp.id])
          return (
            <tr
              key={mcp.id}
              className="table-row-link"
              data-href={href}
              onClick={(event) => {
                if (shouldIgnoreRowClick(event.target)) {
                  return
                }
                navigate(href)
              }}
            >
              <td>
                <Link to={href}>{mcp.name || `MCP ${mcp.id}`}</Link>
              </td>
              <td>{mcp.server_key || '-'}</td>
              <td className="muted">{mcp.description || '-'}</td>
              <td className="muted">{mcp.binding_count ?? 0}</td>
              {allowDelete ? (
                <td className="table-actions-cell">
                  <div className="table-actions">
                    <button
                      type="button"
                      className="icon-button icon-button-danger"
                      aria-label="Delete MCP server"
                      title="Delete MCP server"
                      disabled={busy}
                      onClick={() => onDelete(mcp.id)}
                    >
                      <ActionIcon name="trash" />
                    </button>
                  </div>
                </td>
              ) : null}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default function McpsPage({ section = 'integrated' }) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePerPage(searchParams.get('per_page'))
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [busyById, setBusyById] = useState({})
  const activeSection = useMemo(() => normalizeSection(section), [section])

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getMcps()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load MCP servers.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const integrated = payload && Array.isArray(payload.integrated_mcp_servers)
    ? payload.integrated_mcp_servers
    : []
  const custom = payload && Array.isArray(payload.custom_mcp_servers) ? payload.custom_mcp_servers : []
  const rows = activeSection === 'custom' ? custom : integrated
  const allowDelete = activeSection === 'custom'
  const totalRows = rows.length
  const totalPages = Math.max(1, Math.ceil(totalRows / perPage))
  const currentPage = Math.min(page, totalPages)
  const pageStart = (currentPage - 1) * perPage
  const visibleRows = rows.slice(pageStart, pageStart + perPage)
  const sectionCountLabel = `${totalRows} server${totalRows === 1 ? '' : 's'}`
  const sidebarItems = SECTION_IDS.map((itemId) => ({
    id: itemId,
    to: sectionPath(itemId, searchParams),
    label: itemId === 'custom' ? 'Custom' : 'Integrated',
    icon: sectionIcon(itemId),
  }))

  const updateParams = useCallback((nextParams) => {
    const updated = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(nextParams)) {
      if (value == null || value === '') {
        updated.delete(key)
      } else {
        updated.set(key, String(value))
      }
    }
    if (parsePositiveInt(updated.get('page'), 1) === 1) {
      updated.delete('page')
    }
    if (parsePerPage(updated.get('per_page')) === 25) {
      updated.delete('per_page')
    }
    setSearchParams(updated)
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (state.loading) {
      return
    }
    if (page === currentPage) {
      return
    }
    updateParams({ page: currentPage })
  }, [currentPage, page, state.loading, updateParams])

  function setBusy(mcpId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[mcpId] = true
      } else {
        delete next[mcpId]
      }
      return next
    })
  }

  async function handleDelete(mcpId) {
    if (!window.confirm('Delete this MCP server?')) {
      return
    }
    setActionError('')
    setActionInfo('')
    setBusy(mcpId, true)
    try {
      await deleteMcp(mcpId)
      await refresh({ silent: true })
      setActionInfo('MCP server deleted.')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete MCP server.'))
    } finally {
      setBusy(mcpId, false)
    }
  }

  return (
    <TwoColumnListShell
      ariaLabel="MCP servers"
      className="provider-fixed-page"
      sidebarAriaLabel="MCP server types"
      sidebarTitle="MCP Server Types"
      sidebarItems={sidebarItems}
      activeSidebarId={activeSection}
      mainTitle={sectionTitle(activeSection)}
      mainActions={(
        <div className="pagination-bar-actions">
          <HeaderPagination
            ariaLabel="MCP server pages"
            canGoPrev={currentPage > 1}
            canGoNext={currentPage < totalPages}
            onPrev={() => updateParams({ page: currentPage - 1 })}
            onNext={() => updateParams({ page: currentPage + 1 })}
            currentPage={currentPage}
            totalPages={totalPages}
          />
          <div className="pagination-size">
            <label htmlFor="mcps-per-page">Rows per page</label>
            <select
              id="mcps-per-page"
              value={String(perPage)}
              onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
            >
              {MCP_PER_PAGE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <p className="panel-header-meta">{sectionCountLabel}</p>
          <Link to="/mcps/new" className="icon-button" aria-label="New MCP server" title="New MCP server">
            <ActionIcon name="plus" />
          </Link>
        </div>
      )}
    >
      <p className="panel-header-copy">{sectionDescription(activeSection)}</p>
      {state.loading ? <p>Loading MCP servers...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {!state.loading && !state.error ? (
        <div className="workflow-list-table-shell">
          {totalRows > 0 ? (
            <div className="table-wrap">
              <McpTable
                rows={visibleRows}
                onDelete={handleDelete}
                busyById={busyById}
                navigate={navigate}
                allowDelete={allowDelete}
              />
            </div>
          ) : (
            <TableListEmptyState message="No MCP servers found for this section." />
          )}
        </div>
      ) : null}
    </TwoColumnListShell>
  )
}

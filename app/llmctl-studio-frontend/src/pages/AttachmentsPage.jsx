import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import TableListEmptyState from '../components/TableListEmptyState'
import TwoColumnListShell from '../components/TwoColumnListShell'
import { useFlash } from '../lib/flashMessages'
import { HttpError } from '../lib/httpClient'
import { deleteAttachment, getAttachments } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const ATTACHMENT_SCOPE_OPTIONS = [
  { id: 'chat', label: 'Chat', icon: 'fa-solid fa-comments', title: 'Chat Attachments' },
  { id: 'quick', label: 'Quick', icon: 'fa-solid fa-comment-dots', title: 'Quick Attachments' },
  { id: 'flowchart', label: 'Flowchart', icon: 'fa-solid fa-diagram-project', title: 'Flowchart Attachments' },
]
const ATTACHMENT_PER_PAGE_OPTIONS = [10, 25, 50]

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function parsePerPage(value) {
  const parsed = parsePositiveInt(value, 25)
  return ATTACHMENT_PER_PAGE_OPTIONS.includes(parsed) ? parsed : 25
}

function parseScope(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return ATTACHMENT_SCOPE_OPTIONS.some((item) => item.id === normalized) ? normalized : 'chat'
}

function scopeHref(currentSearchParams, scopeId) {
  const next = new URLSearchParams(currentSearchParams)
  next.set('node_type', scopeId)
  next.delete('page')
  const query = next.toString()
  return query ? `/attachments?${query}` : '/attachments'
}

function formatSize(sizeBytes) {
  const value = Number(sizeBytes)
  if (!Number.isFinite(value) || value < 0) {
    return '-'
  }
  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
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

function scopeBindingCount(attachment, scopeId) {
  if (scopeId === 'chat') {
    return Number.parseInt(String(attachment.chat_binding_count || 0), 10) || 0
  }
  if (scopeId === 'quick') {
    return Number.parseInt(String(attachment.quick_binding_count || 0), 10) || 0
  }
  if (scopeId === 'flowchart') {
    return Number.parseInt(String(attachment.flowchart_binding_count || 0), 10) || 0
  }
  return Number.parseInt(String(attachment.binding_count || 0), 10) || 0
}

export default function AttachmentsPage() {
  const navigate = useNavigate()
  const flash = useFlash()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePerPage(searchParams.get('per_page'))
  const activeScope = parseScope(searchParams.get('node_type'))
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [busyById, setBusyById] = useState({})

  const activeScopeMeta = useMemo(
    () => ATTACHMENT_SCOPE_OPTIONS.find((item) => item.id === activeScope) || ATTACHMENT_SCOPE_OPTIONS[0],
    [activeScope],
  )

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
    if (parseScope(updated.get('node_type')) === 'chat') {
      updated.delete('node_type')
    }
    setSearchParams(updated)
  }, [searchParams, setSearchParams])

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getAttachments({
        nodeType: activeScope,
        page,
        perPage,
      })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load attachments.'),
      }))
    }
  }, [activeScope, page, perPage])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const attachments = payload && Array.isArray(payload.items)
    ? payload.items
    : payload && Array.isArray(payload.attachments)
      ? payload.attachments
      : []
  const totalRowsRaw = Number.parseInt(String(payload?.total_count ?? attachments.length), 10)
  const totalRows = Number.isInteger(totalRowsRaw) && totalRowsRaw >= 0 ? totalRowsRaw : attachments.length
  const totalPages = Math.max(1, Math.ceil(totalRows / perPage))
  const currentPage = Math.min(page, totalPages)
  const sidebarItems = ATTACHMENT_SCOPE_OPTIONS.map((item) => ({
    id: item.id,
    to: scopeHref(searchParams, item.id),
    label: item.label,
    icon: item.icon,
  }))

  useEffect(() => {
    if (state.loading || page === currentPage) {
      return
    }
    updateParams({ page: currentPage })
  }, [currentPage, page, state.loading, updateParams])

  function setBusy(attachmentId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[attachmentId] = true
      } else {
        delete next[attachmentId]
      }
      return next
    })
  }

  async function handleDelete(attachmentId) {
    if (!window.confirm('Delete this attachment?')) {
      return
    }
    setBusy(attachmentId, true)
    try {
      await deleteAttachment(attachmentId)
      await refresh({ silent: true })
      flash.success('Attachment deleted.')
    } catch (error) {
      flash.error(errorMessage(error, 'Failed to delete attachment.'))
    } finally {
      setBusy(attachmentId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <TwoColumnListShell
      ariaLabel="Attachments"
      className="provider-fixed-page"
      sidebarAriaLabel="Attachment scopes"
      sidebarTitle="Node Types"
      sidebarItems={sidebarItems}
      activeSidebarId={activeScope}
      mainTitle={activeScopeMeta.title}
      mainActions={(
        <div className="pagination-bar-actions">
          <HeaderPagination
            ariaLabel="Attachments pages"
            canGoPrev={currentPage > 1}
            canGoNext={currentPage < totalPages}
            onPrev={() => updateParams({ page: currentPage - 1 })}
            onNext={() => updateParams({ page: currentPage + 1 })}
            currentPage={currentPage}
            totalPages={totalPages}
          />
          <div className="pagination-size">
            <label htmlFor="attachments-per-page">Rows per page</label>
            <select
              id="attachments-per-page"
              value={String(perPage)}
              onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
            >
              {ATTACHMENT_PER_PAGE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <p className="panel-header-meta">{totalRows} attachments</p>
        </div>
      )}
    >
      {state.loading ? <p>Loading attachments...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {!state.loading && !state.error ? (
        <div className="workflow-list-table-shell">
          {attachments.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Type</th>
                    <th>Size</th>
                    <th>Linked</th>
                    <th>Created</th>
                    <th className="table-actions-cell">Delete</th>
                  </tr>
                </thead>
                <tbody>
                  {attachments.map((attachment) => {
                    const href = `/attachments/${attachment.id}`
                    const busy = Boolean(busyById[attachment.id])
                    return (
                      <tr
                        key={attachment.id}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{attachment.file_name || `Attachment ${attachment.id}`}</Link>
                        </td>
                        <td>{attachment.content_type || '-'}</td>
                        <td>{formatSize(attachment.size_bytes)}</td>
                        <td>{scopeBindingCount(attachment, activeScope)}</td>
                        <td>{attachment.created_at || attachment.updated_at || '-'}</td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              aria-label="Delete attachment"
                              title="Delete attachment"
                              disabled={busy}
                              onClick={() => handleDelete(attachment.id)}
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
          ) : (
            <TableListEmptyState message="No attachments found for this node type." />
          )}
        </div>
      ) : null}
    </TwoColumnListShell>
  )
}

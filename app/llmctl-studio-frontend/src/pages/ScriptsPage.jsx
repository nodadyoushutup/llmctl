import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import HeaderPagination from '../components/HeaderPagination'
import TableListEmptyState from '../components/TableListEmptyState'
import TwoColumnListShell from '../components/TwoColumnListShell'
import { HttpError } from '../lib/httpClient'
import { deleteScript, getScripts } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const SCRIPT_PER_PAGE_OPTIONS = [10, 25, 50]
const FALLBACK_SCRIPT_TYPES = [
  { value: 'pre_init', label: 'Pre-Init Script' },
  { value: 'init', label: 'Init Script' },
  { value: 'post_init', label: 'Post-Init Script' },
  { value: 'post_run', label: 'Post-Autorun Script' },
]

const SCRIPT_TYPE_NAV_META = {
  pre_init: { label: 'Pre Init', icon: 'fa-solid fa-hourglass-start' },
  init: { label: 'Init', icon: 'fa-solid fa-play' },
  post_init: { label: 'Post Init', icon: 'fa-solid fa-hourglass-end' },
  post_run: { label: 'Post Run', icon: 'fa-solid fa-flag-checkered' },
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function parsePerPage(value) {
  const parsed = parsePositiveInt(value, 25)
  return SCRIPT_PER_PAGE_OPTIONS.includes(parsed) ? parsed : 25
}

function resolveScriptTypeNavMeta(value, fallbackLabel) {
  const normalized = String(value || '').trim().toLowerCase()
  const mapped = SCRIPT_TYPE_NAV_META[normalized]
  if (mapped) {
    return mapped
  }
  return {
    label: String(fallbackLabel || normalized || 'Script').replace(/\s*Script$/i, '').trim() || 'Script',
    icon: 'fa-solid fa-code',
  }
}

function scriptTypeHref(currentSearchParams, scriptType) {
  const params = new URLSearchParams(currentSearchParams)
  params.set('script_type', String(scriptType || '').trim().toLowerCase())
  params.delete('page')
  const nextSearch = params.toString()
  return nextSearch ? `/scripts?${nextSearch}` : '/scripts'
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

export default function ScriptsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePerPage(searchParams.get('per_page'))
  const requestedScriptType = String(searchParams.get('script_type') || '').trim().toLowerCase()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [busyById, setBusyById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getScripts()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load scripts.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const scripts = payload && Array.isArray(payload.scripts) ? payload.scripts : []
  const scriptTypes = useMemo(() => {
    const scriptTypesFromPayload = payload && Array.isArray(payload.script_types) ? payload.script_types : []
    const source = scriptTypesFromPayload.length > 0 ? scriptTypesFromPayload : FALLBACK_SCRIPT_TYPES
    const seen = new Set()
    return source
      .map((item) => {
        const value = String(item?.value || '').trim().toLowerCase()
        const label = String(item?.label || item?.value || '').trim()
        if (!value || seen.has(value)) {
          return null
        }
        seen.add(value)
        return { value, label: label || value }
      })
      .filter(Boolean)
  }, [payload])
  const activeScriptTypeValue = useMemo(() => {
    if (scriptTypes.length === 0) {
      return ''
    }
    const requested = String(requestedScriptType || '').trim().toLowerCase()
    return scriptTypes.some((item) => item.value === requested) ? requested : scriptTypes[0].value
  }, [requestedScriptType, scriptTypes])
  const filteredScripts = activeScriptTypeValue
    ? scripts.filter((script) => String(script?.script_type || '').trim().toLowerCase() === activeScriptTypeValue)
    : scripts
  const totalRows = filteredScripts.length
  const totalPages = Math.max(1, Math.ceil(totalRows / perPage))
  const currentPage = Math.min(page, totalPages)
  const pageStart = (currentPage - 1) * perPage
  const visibleScripts = filteredScripts.slice(pageStart, pageStart + perPage)
  const sidebarItems = scriptTypes.map((item) => {
    const navMeta = resolveScriptTypeNavMeta(item.value, item.label)
    return {
      id: item.value,
      to: scriptTypeHref(searchParams, item.value),
      label: navMeta.label,
      icon: navMeta.icon,
    }
  })

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

  function setBusy(scriptId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[scriptId] = true
      } else {
        delete next[scriptId]
      }
      return next
    })
  }

  async function handleDelete(scriptId) {
    if (!window.confirm('Delete this script?')) {
      return
    }
    setActionError('')
    setActionInfo('')
    setBusy(scriptId, true)
    try {
      await deleteScript(scriptId)
      await refresh({ silent: true })
      setActionInfo('Script deleted.')
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete script.'))
    } finally {
      setBusy(scriptId, false)
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
      ariaLabel="Scripts"
      className="provider-fixed-page"
      sidebarAriaLabel="Script types"
      sidebarTitle="Script Types"
      sidebarItems={sidebarItems}
      activeSidebarId={activeScriptTypeValue}
      mainTitle="Scripts"
      mainActions={(
        <div className="pagination-bar-actions">
          <HeaderPagination
            ariaLabel="Scripts pages"
            canGoPrev={currentPage > 1}
            canGoNext={currentPage < totalPages}
            onPrev={() => updateParams({ page: currentPage - 1 })}
            onNext={() => updateParams({ page: currentPage + 1 })}
            currentPage={currentPage}
            totalPages={totalPages}
          />
          <div className="pagination-size">
            <label htmlFor="scripts-per-page">Rows per page</label>
            <select
              id="scripts-per-page"
              value={String(perPage)}
              onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
            >
              {SCRIPT_PER_PAGE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <p className="panel-header-meta">{totalRows} scripts</p>
          <Link to="/scripts/new" className="icon-button" aria-label="New script" title="New script">
            <ActionIcon name="plus" />
          </Link>
        </div>
      )}
    >
      {state.loading ? <p>Loading scripts...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}
      {!state.loading && !state.error ? (
        <div className="workflow-list-table-shell">
          {visibleScripts.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>File name</th>
                    <th>Type</th>
                    <th>Description</th>
                    <th className="table-actions-cell">Delete</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleScripts.map((script) => {
                    const href = `/scripts/${script.id}`
                    const busy = Boolean(busyById[script.id])
                    return (
                      <tr
                        key={script.id}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{script.file_name || `Script ${script.id}`}</Link>
                        </td>
                        <td>{script.script_type_label || script.script_type || '-'}</td>
                        <td>
                          <p className="muted" style={{ fontSize: '12px' }}>{script.description || '-'}</p>
                        </td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              aria-label="Delete script"
                              title="Delete script"
                              disabled={busy}
                              onClick={() => handleDelete(script.id)}
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
            <TableListEmptyState message="No scripts created yet for this type." />
          )}
        </div>
      ) : null}
    </TwoColumnListShell>
  )
}

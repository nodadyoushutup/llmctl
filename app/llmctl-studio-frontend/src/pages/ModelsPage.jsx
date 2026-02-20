import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { useFlash } from '../lib/flashMessages'
import { HttpError } from '../lib/httpClient'
import { rememberModelsListScroll, resolveModelsListHref, restoreModelsListScroll } from '../lib/modelsListState'
import { deleteModel, getModels, updateDefaultModel } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

const SORT_KEYS = new Set(['name', 'provider', 'model', 'default'])
const SORT_DIRECTIONS = new Set(['asc', 'desc'])
const PER_PAGE_OPTIONS = [10, 25, 50]
const EMPTY_MODELS = []

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function parseSortKey(value) {
  const normalized = String(value || '').toLowerCase()
  return SORT_KEYS.has(normalized) ? normalized : 'name'
}

function parseSortDirection(value) {
  const normalized = String(value || '').toLowerCase()
  return SORT_DIRECTIONS.has(normalized) ? normalized : 'asc'
}

function parsePerPage(value) {
  const parsed = parsePositiveInt(value, 10)
  return PER_PAGE_OPTIONS.includes(parsed) ? parsed : 10
}

function parseDefaultFilter(value) {
  const normalized = String(value || '').toLowerCase()
  if (normalized === 'default' || normalized === 'non_default') {
    return normalized
  }
  return ''
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

function buildModelSearchText(model) {
  return [
    String(model?.name || ''),
    String(model?.description || ''),
    String(model?.provider || ''),
    String(model?.provider_label || ''),
    String(model?.model_name || ''),
  ].join(' ').toLowerCase()
}

export default function ModelsPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const flash = useFlash()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parsePositiveInt(searchParams.get('page'), 1)
  const perPage = parsePerPage(searchParams.get('per_page'))
  const sortKey = parseSortKey(searchParams.get('sort'))
  const sortDirection = parseSortDirection(searchParams.get('dir'))
  const providerFilter = String(searchParams.get('provider') || '').trim().toLowerCase()
  const defaultFilter = parseDefaultFilter(searchParams.get('default'))
  const searchQuery = String(searchParams.get('q') || '').trim()

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [busyById, setBusyById] = useState({})
  const [searchDraft, setSearchDraft] = useState(searchQuery)
  const [scrollRestoreAttempted, setScrollRestoreAttempted] = useState(false)

  useEffect(() => {
    setSearchDraft(searchQuery)
  }, [searchQuery])

  useEffect(() => {
    if (scrollRestoreAttempted || state.loading) {
      return
    }
    const savedOffset = restoreModelsListScroll(location.search)
    setScrollRestoreAttempted(true)
    if (!Number.isFinite(savedOffset)) {
      return
    }
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: savedOffset, behavior: 'auto' })
    })
  }, [location.search, scrollRestoreAttempted, state.loading])

  useEffect(() => {
    setScrollRestoreAttempted(false)
  }, [location.search])

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getModels()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load models.'),
      }))
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const models = useMemo(
    () => (payload && Array.isArray(payload.models) ? payload.models : EMPTY_MODELS),
    [payload],
  )
  const listHref = resolveModelsListHref(`/models${location.search}`)

  const providerOptions = useMemo(() => {
    const optionsByValue = new Map()
    models.forEach((model) => {
      const value = String(model?.provider || '').trim().toLowerCase()
      if (!value || optionsByValue.has(value)) {
        return
      }
      const label = String(model?.provider_label || model?.provider || value)
      optionsByValue.set(value, label)
    })
    return Array.from(optionsByValue.entries())
      .map(([value, label]) => ({ value, label }))
      .sort((left, right) => left.label.localeCompare(right.label))
  }, [models])

  const filteredModels = useMemo(() => {
    const normalizedSearch = searchQuery.toLowerCase()
    return models.filter((model) => {
      if (providerFilter && String(model?.provider || '').toLowerCase() !== providerFilter) {
        return false
      }
      if (defaultFilter === 'default' && !model?.is_default) {
        return false
      }
      if (defaultFilter === 'non_default' && model?.is_default) {
        return false
      }
      if (normalizedSearch && !buildModelSearchText(model).includes(normalizedSearch)) {
        return false
      }
      return true
    })
  }, [defaultFilter, models, providerFilter, searchQuery])

  const sortedModels = useMemo(() => {
    const next = [...filteredModels]
    next.sort((left, right) => {
      if (sortKey === 'provider') {
        const leftProvider = String(left?.provider_label || left?.provider || '')
        const rightProvider = String(right?.provider_label || right?.provider || '')
        return leftProvider.localeCompare(rightProvider, undefined, { sensitivity: 'base' })
      }
      if (sortKey === 'model') {
        return String(left?.model_name || '').localeCompare(String(right?.model_name || ''), undefined, { sensitivity: 'base' })
      }
      if (sortKey === 'default') {
        return Number(Boolean(left?.is_default)) - Number(Boolean(right?.is_default))
      }
      return String(left?.name || '').localeCompare(String(right?.name || ''), undefined, { sensitivity: 'base' })
    })
    if (sortDirection === 'desc') {
      next.reverse()
    }
    return next
  }, [filteredModels, sortDirection, sortKey])

  const totalModels = sortedModels.length
  const totalPages = Math.max(1, Math.ceil(totalModels / perPage))
  const currentPage = Math.min(page, totalPages)
  const pageStart = (currentPage - 1) * perPage
  const visibleModels = sortedModels.slice(pageStart, pageStart + perPage)

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
    if (parsePerPage(updated.get('per_page')) === 10) {
      updated.delete('per_page')
    }
    if (parseSortKey(updated.get('sort')) === 'name') {
      updated.delete('sort')
    }
    if (parseSortDirection(updated.get('dir')) === 'asc') {
      updated.delete('dir')
    }
    if (!String(updated.get('provider') || '').trim()) {
      updated.delete('provider')
    }
    if (!parseDefaultFilter(updated.get('default'))) {
      updated.delete('default')
    }
    if (!String(updated.get('q') || '').trim()) {
      updated.delete('q')
    }
    setSearchParams(updated)
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const normalizedDraft = searchDraft.trim()
    if (normalizedDraft === searchQuery) {
      return
    }
    const timeoutId = window.setTimeout(() => {
      updateParams({ q: normalizedDraft || null, page: 1 })
    }, 260)
    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [searchDraft, searchQuery, updateParams])

  useEffect(() => {
    if (state.loading) {
      return
    }
    if (page === currentPage) {
      return
    }
    updateParams({ page: currentPage })
  }, [currentPage, page, state.loading, updateParams])

  function setBusy(modelId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[modelId] = true
      } else {
        delete next[modelId]
      }
      return next
    })
  }

  async function handleDelete(model) {
    const modelId = Number.parseInt(String(model?.id || ''), 10)
    if (!Number.isInteger(modelId) || modelId <= 0) {
      return
    }
    if (!window.confirm('Delete this model?')) {
      return
    }
    setBusy(modelId, true)
    try {
      await deleteModel(modelId)
      await refresh({ silent: true })
      flash.success(`Deleted model ${model?.name || modelId}.`)
    } catch (error) {
      flash.error(errorMessage(error, 'Failed to delete model.'))
    } finally {
      setBusy(modelId, false)
    }
  }

  async function handleDefault(model) {
    const modelId = Number.parseInt(String(model?.id || ''), 10)
    if (!Number.isInteger(modelId) || modelId <= 0) {
      return
    }
    setBusy(modelId, true)
    try {
      const nextIsDefault = !model?.is_default
      await updateDefaultModel(modelId, nextIsDefault)
      await refresh({ silent: true })
      flash.success(nextIsDefault ? 'Default model updated.' : 'Default model unset.')
    } catch (error) {
      flash.error(errorMessage(error, 'Failed to update default model.'))
    } finally {
      setBusy(modelId, false)
    }
  }

  function rememberListState() {
    rememberModelsListScroll(location.search)
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    rememberListState()
    navigate(href, { state: { from: listHref } })
  }

  return (
    <section className="stack" aria-label="Models">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Models</h2>
            <p>Create model profiles that bind provider selection and runtime policies.</p>
          </div>
          <Link
            to="/models/new"
            state={{ from: listHref }}
            className="icon-button"
            aria-label="New model"
            title="New model"
            onClick={rememberListState}
          >
            <ActionIcon name="plus" />
          </Link>
        </div>
        <div className="toolbar toolbar-wrap">
          <div className="toolbar-group">
            <label htmlFor="models-search">Search</label>
            <input
              id="models-search"
              type="search"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Name, provider, model..."
            />
          </div>
          <div className="toolbar-group">
            <label htmlFor="models-provider-filter">Provider</label>
            <select
              id="models-provider-filter"
              value={providerFilter}
              onChange={(event) => updateParams({ provider: event.target.value, page: 1 })}
            >
              <option value="">All providers</option>
              {providerOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
          <div className="toolbar-group">
            <label htmlFor="models-default-filter">Default</label>
            <select
              id="models-default-filter"
              value={defaultFilter}
              onChange={(event) => updateParams({ default: event.target.value, page: 1 })}
            >
              <option value="">All</option>
              <option value="default">Default only</option>
              <option value="non_default">Non-default only</option>
            </select>
          </div>
          <div className="toolbar-group">
            <label htmlFor="models-sort-key">Sort</label>
            <select
              id="models-sort-key"
              value={sortKey}
              onChange={(event) => updateParams({ sort: event.target.value, page: 1 })}
            >
              <option value="name">Name</option>
              <option value="provider">Provider</option>
              <option value="model">Model</option>
              <option value="default">Default</option>
            </select>
          </div>
          <div className="toolbar-group">
            <label htmlFor="models-sort-direction">Direction</label>
            <select
              id="models-sort-direction"
              value={sortDirection}
              onChange={(event) => updateParams({ dir: event.target.value, page: 1 })}
            >
              <option value="asc">Ascending</option>
              <option value="desc">Descending</option>
            </select>
          </div>
          <div className="toolbar-group">
            <label htmlFor="models-per-page">Rows per page</label>
            <select
              id="models-per-page"
              value={String(perPage)}
              onChange={(event) => updateParams({ per_page: event.target.value, page: 1 })}
            >
              {PER_PAGE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
        </div>
        {!state.loading && !state.error ? (
          <div className="title-row" style={{ marginTop: '4px' }}>
            <p className="toolbar-meta">Total models: {totalModels}</p>
            <nav className="pagination" aria-label="Models pages">
              {currentPage > 1 ? (
                <button
                  type="button"
                  className="pagination-btn"
                  onClick={() => updateParams({ page: currentPage - 1 })}
                >
                  Prev
                </button>
              ) : (
                <span className="pagination-btn is-disabled" aria-disabled="true">Prev</span>
              )}
              <span className="pagination-link is-active" aria-current="page">
                {currentPage}
              </span>
              <span className="muted">/ {totalPages}</span>
              {currentPage < totalPages ? (
                <button
                  type="button"
                  className="pagination-btn"
                  onClick={() => updateParams({ page: currentPage + 1 })}
                >
                  Next
                </button>
              ) : (
                <span className="pagination-btn is-disabled" aria-disabled="true">Next</span>
              )}
            </nav>
          </div>
        ) : null}
        {state.loading ? <p>Loading models...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && visibleModels.length === 0 ? <p>No models matched the current filters.</p> : null}
        {!state.loading && !state.error && visibleModels.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th className="table-actions-cell">Default</th>
                  <th className="table-actions-cell">Delete</th>
                </tr>
              </thead>
              <tbody>
                {visibleModels.map((model) => {
                  const href = `/models/${model.id}`
                  const busy = Boolean(busyById[model.id])
                  return (
                    <tr
                      key={model.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleRowClick(event, href)}
                    >
                      <td>
                        <Link
                          to={href}
                          state={{ from: listHref }}
                          onClick={rememberListState}
                        >
                          {model.name || `Model ${model.id}`}
                        </Link>
                        {model.description ? (
                          <p className="muted" style={{ marginTop: '6px', fontSize: '12px' }}>
                            {model.description}
                          </p>
                        ) : null}
                      </td>
                      <td>{model.provider_label || model.provider || '-'}</td>
                      <td>{model.model_name || '-'}</td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <button
                            type="button"
                            className={`icon-button${model.is_default ? ' icon-button-active' : ''}`}
                            aria-label={model.is_default ? 'Unset default model' : 'Set default model'}
                            title={model.is_default ? 'Unset default model' : 'Set default model'}
                            disabled={busy}
                            onClick={() => handleDefault(model)}
                          >
                            <ActionIcon name={model.is_default ? 'star-filled' : 'star'} />
                          </button>
                        </div>
                      </td>
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Delete model"
                            title="Delete model"
                            disabled={busy}
                            onClick={() => handleDelete(model)}
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

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getConfluenceWorkspace } from '../lib/studioApi'

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

export default function ConfluencePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedPageId = useMemo(() => String(searchParams.get('page') || '').trim(), [searchParams])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getConfluenceWorkspace({ page: selectedPageId })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Confluence workspace.') })
    }
  }, [selectedPageId])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getConfluenceWorkspace({ page: selectedPageId })
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Confluence workspace.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [selectedPageId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const pages = payload && Array.isArray(payload.pages) ? payload.pages : []
  const selectedPage = payload && payload.selected_page && typeof payload.selected_page === 'object'
    ? payload.selected_page
    : null

  return (
    <section className="stack" aria-label="Confluence workspace">
      <article className="card">
        <PanelHeader
          title="Confluence Workspace"
          actions={(
            <div className="table-actions">
              <Link to="/settings/integrations/confluence" className="btn-link btn-secondary">Confluence Settings</Link>
              <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
            </div>
          )}
        />
        <p className="muted">Select pages in a space and preview their rendered content.</p>
        {state.loading ? <p>Loading Confluence pages...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.error ? <p className="error-text">{String(payload.error)}</p> : null}
        {!state.loading && !state.error ? (
          <div className="key-value-grid">
            <p><strong>Space:</strong> {payload?.space_name || payload?.space || '-'}</p>
            <p><strong>Site:</strong> {payload?.site || '-'}</p>
            <p><strong>Connected:</strong> {payload?.connected ? 'Yes' : 'No'}</p>
          </div>
        ) : null}
      </article>

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Pages</h2>
          {pages.length === 0 ? <p>No pages found.</p> : null}
          {pages.length > 0 ? (
            <ul className="stack">
              {pages.map((page, index) => {
                const pageId = String(page?.id || '').trim()
                return (
                  <li key={`${pageId || 'page'}-${index}`}>
                    <button
                      type="button"
                      className={pageId && pageId === selectedPageId ? 'btn-link' : 'btn-link btn-secondary'}
                      onClick={() => {
                        const next = new URLSearchParams(searchParams)
                        if (pageId) {
                          next.set('page', pageId)
                        } else {
                          next.delete('page')
                        }
                        setSearchParams(next)
                      }}
                    >
                      {page?.title || `Page ${index + 1}`}
                    </button>
                  </li>
                )
              })}
            </ul>
          ) : null}
        </article>
      ) : null}

      {!state.loading && !state.error && selectedPage ? (
        <article className="card">
          <h2>{selectedPage.title || 'Selected Page'}</h2>
          <p>{selectedPage.url ? <a href={selectedPage.url} target="_blank" rel="noreferrer">Open in Confluence</a> : null}</p>
          <p>{selectedPage.excerpt || selectedPage.summary || '-'}</p>
          <pre className="code-block">{selectedPage.body_text || selectedPage.content || ''}</pre>
        </article>
      ) : null}
    </section>
  )
}

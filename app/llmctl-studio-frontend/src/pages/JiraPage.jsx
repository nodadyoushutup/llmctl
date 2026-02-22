import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getJiraWorkspace } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function errorMessage(error, fallback) {
  if (error instanceof HttpError) {
    if (error.isAuthError) {
      return `${error.message} Sign in to Studio if authentication is enabled.`
    }
    if (error.status === 0) {
      return 'Unable to reach the Studio API. Check connectivity and try again.'
    }
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

export default function JiraPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getJiraWorkspace()
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Jira workspace.') })
    }
  }, [])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getJiraWorkspace()
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Jira workspace.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const columns = payload && Array.isArray(payload.board_columns) ? payload.board_columns : []
  const unmapped = payload && Array.isArray(payload.board_unmapped) ? payload.board_unmapped : []

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Jira workspace">
      <article className="card">
        <PanelHeader
          title="Jira Workspace"
          actions={(
            <div className="table-actions">
              <Link to="/settings/integrations/jira" className="btn-link btn-secondary">Jira Settings</Link>
              <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
            </div>
          )}
        />
        <p className="muted">Browse board columns and drill into issue details.</p>
        {state.loading ? <p>Loading Jira board...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.board_error ? <p className="error-text">{String(payload.board_error)}</p> : null}
        {!state.loading && !state.error ? (
          <div className="key-value-grid">
            <p><strong>Board:</strong> {payload?.board || '-'}</p>
            <p><strong>Site:</strong> {payload?.site || '-'}</p>
            <p><strong>Columns:</strong> {payload?.board_column_count ?? 0}</p>
            <p><strong>Issues:</strong> {payload?.board_issue_total ?? 0}</p>
          </div>
        ) : null}
      </article>

      {!state.loading && !state.error && columns.length > 0 ? columns.map((column, index) => {
        const issues = Array.isArray(column?.issues) ? column.issues : []
        return (
          <article className="card" key={`${column?.name || 'column'}-${index}`}>
            <h2>{column?.name || `Column ${index + 1}`}</h2>
            {issues.length === 0 ? <p>No issues in this column.</p> : null}
            {issues.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Key</th>
                      <th>Summary</th>
                      <th>Status</th>
                      <th>Assignee</th>
                    </tr>
                  </thead>
                  <tbody>
                    {issues.map((issue, issueIndex) => {
                      const key = String(issue?.key || '').trim()
                      const href = key ? `/jira/issues/${encodeURIComponent(key)}` : '/jira'
                      return (
                        <tr key={`${key || String(issue?.summary || 'issue')}-${issueIndex}`} className="table-row-link" data-href={href} onClick={(event) => handleRowClick(event, href)}>
                          <td><Link to={href}>{key || '-'}</Link></td>
                          <td>{issue?.summary || '-'}</td>
                          <td>{issue?.status?.name || issue?.status || '-'}</td>
                          <td>{issue?.assignee?.display_name || issue?.assignee || '-'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </article>
        )
      }) : null}

      {!state.loading && !state.error && unmapped.length > 0 ? (
        <article className="card">
          <h2>Unmapped Issues</h2>
          <ul className="stack">
            {unmapped.map((issue, index) => (
              <li key={`${issue?.key || 'issue'}-${index}`}>{issue?.key || '-'}: {issue?.summary || '-'}</li>
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getGithubWorkspace } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

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

export default function GithubPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('pulls')
  const [prStatus, setPrStatus] = useState('open')
  const [prAuthor, setPrAuthor] = useState('')
  const [codePath, setCodePath] = useState('')
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getGithubWorkspace({
        tab,
        prStatus,
        prAuthor,
        path: codePath,
      })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load GitHub workspace.') })
    }
  }, [tab, prStatus, prAuthor, codePath])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const payload = await getGithubWorkspace({
          tab,
          prStatus,
          prAuthor,
          path: codePath,
        })
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load GitHub workspace.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [tab, prStatus, prAuthor, codePath])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const pullRequests = payload && Array.isArray(payload.pull_requests) ? payload.pull_requests : []
  const actions = payload && Array.isArray(payload.actions) ? payload.actions : []
  const codeEntries = payload && Array.isArray(payload.code_entries) ? payload.code_entries : []
  const prAuthors = payload && Array.isArray(payload.pull_request_authors) ? payload.pull_request_authors : []

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="GitHub workspace">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>GitHub Workspace</h2>
            <p>Browse pull requests, workflow runs, and repository files.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/integrations/github" className="btn-link btn-secondary">GitHub Settings</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            <button type="button" className={tab === 'pulls' ? 'btn-link' : 'btn-link btn-secondary'} onClick={() => setTab('pulls')}>Pulls</button>
            <button type="button" className={tab === 'actions' ? 'btn-link' : 'btn-link btn-secondary'} onClick={() => setTab('actions')}>Actions</button>
            <button type="button" className={tab === 'code' ? 'btn-link' : 'btn-link btn-secondary'} onClick={() => setTab('code')}>Code</button>
          </div>
        </div>
        {state.loading ? <p>Loading GitHub workspace...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.pull_request_error ? <p className="error-text">{String(payload.pull_request_error)}</p> : null}
        {payload?.actions_error ? <p className="error-text">{String(payload.actions_error)}</p> : null}
        {payload?.code_error ? <p className="error-text">{String(payload.code_error)}</p> : null}
      </article>

      {!state.loading && !state.error && tab === 'pulls' ? (
        <article className="card">
          <h2>Pull Requests</h2>
          <div className="toolbar">
            <div className="toolbar-group">
              <label>
                Status
                <select value={prStatus} onChange={(event) => setPrStatus(event.target.value)}>
                  <option value="open">Open</option>
                  <option value="all">All</option>
                  <option value="closed">Closed</option>
                  <option value="merged">Merged</option>
                  <option value="draft">Draft</option>
                </select>
              </label>
              <label>
                Author
                <select value={prAuthor} onChange={(event) => setPrAuthor(event.target.value)}>
                  <option value="">All</option>
                  {prAuthors.map((author) => (
                    <option key={author} value={author}>{author}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="btn-link btn-secondary" onClick={refresh}>Apply</button>
            </div>
          </div>
          {pullRequests.length === 0 ? <p>No pull requests found.</p> : null}
          {pullRequests.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>PR</th>
                    <th>Title</th>
                    <th>Author</th>
                    <th>Status</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {pullRequests.map((item) => {
                    const prNumber = Number.parseInt(String(item.number ?? ''), 10)
                    if (!Number.isInteger(prNumber) || prNumber <= 0) {
                      return null
                    }
                    const href = `/github/pulls/${prNumber}`
                    return (
                      <tr key={prNumber} className="table-row-link" data-href={href} onClick={(event) => handleRowClick(event, href)}>
                        <td><Link to={href}>#{prNumber}</Link></td>
                        <td>{item.title || '-'}</td>
                        <td>{item.author || '-'}</td>
                        <td>{item.state || '-'}</td>
                        <td>{item.updated_at || '-'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      ) : null}

      {!state.loading && !state.error && tab === 'actions' ? (
        <article className="card">
          <h2>Actions</h2>
          {actions.length === 0 ? <p>No workflow runs found.</p> : null}
          {actions.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Workflow</th>
                    <th>Status</th>
                    <th>Branch</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {actions.map((item, index) => (
                    <tr key={`${item.name || 'action'}-${index}`}>
                      <td>{item.name || '-'}</td>
                      <td>{item.status || '-'}</td>
                      <td>{item.branch || '-'}</td>
                      <td>{item.updated_at || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </article>
      ) : null}

      {!state.loading && !state.error && tab === 'code' ? (
        <article className="card">
          <h2>Code Explorer</h2>
          <div className="toolbar">
            <div className="toolbar-group">
              <label>
                Path
                <input value={codePath} onChange={(event) => setCodePath(event.target.value)} placeholder="docs/README.md" />
              </label>
              <button type="button" className="btn-link btn-secondary" onClick={refresh}>Open</button>
            </div>
          </div>
          {payload?.code_file ? (
            <div className="stack">
              <h3>{payload.code_file.path || payload.code_file.name || 'Selected file'}</h3>
              <pre className="code-block">{payload.code_file.content || ''}</pre>
            </div>
          ) : null}
          {codeEntries.length === 0 ? <p>No code entries for this path.</p> : null}
          {codeEntries.length > 0 ? (
            <ul className="stack">
              {codeEntries.map((entry, index) => (
                <li key={`${entry.path || entry.name || 'entry'}-${index}`}>
                  <button
                    type="button"
                    className="btn-link btn-secondary"
                    onClick={() => {
                      setCodePath(String(entry.path || ''))
                    }}
                  >
                    {entry.type === 'dir' ? 'Folder' : 'File'}: {entry.path || entry.name || '-'}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

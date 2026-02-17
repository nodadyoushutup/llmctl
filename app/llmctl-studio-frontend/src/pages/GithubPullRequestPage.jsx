import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useLocation, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getGithubPullRequest, runGithubPullRequestCodeReview } from '../lib/studioApi'

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

function tabFromPath(pathname) {
  if (pathname.endsWith('/commits')) {
    return 'commits'
  }
  if (pathname.endsWith('/checks')) {
    return 'checks'
  }
  if (pathname.endsWith('/files')) {
    return 'files'
  }
  return 'conversation'
}

export default function GithubPullRequestPage() {
  const { prNumber } = useParams()
  const location = useLocation()
  const tab = useMemo(() => tabFromPath(location.pathname), [location.pathname])
  const parsedPrNumber = Number.parseInt(String(prNumber ?? ''), 10)

  const invalidId = !Number.isInteger(parsedPrNumber) || parsedPrNumber <= 0
  const [state, setState] = useState({ loading: !invalidId, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [actionInfo, setActionInfo] = useFlashState('success')

  const refresh = useCallback(async () => {
    if (invalidId) {
      return
    }
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getGithubPullRequest(parsedPrNumber, { tab })
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load pull request details.') })
    }
  }, [invalidId, parsedPrNumber, tab])

  useEffect(() => {
    if (invalidId) {
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const payload = await getGithubPullRequest(parsedPrNumber, { tab })
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load pull request details.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [invalidId, parsedPrNumber, tab])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const pullRequest = payload && payload.pull_request && typeof payload.pull_request === 'object'
    ? payload.pull_request
    : null
  const comments = payload && Array.isArray(payload.comments) ? payload.comments : []
  const reviewers = payload && Array.isArray(payload.reviewers) ? payload.reviewers : []

  async function runCodeReview() {
    if (invalidId) {
      return
    }
    setActionError('')
    setActionInfo('')
    try {
      const result = await runGithubPullRequestCodeReview(parsedPrNumber, {
        prTitle: String(pullRequest?.title || ''),
        prUrl: String(pullRequest?.url || ''),
      })
      const taskId = Number.parseInt(String(result?.task_id ?? ''), 10)
      if (Number.isInteger(taskId) && taskId > 0) {
        setActionInfo(`Code review queued as node ${taskId}.`)
      } else {
        setActionInfo('Code review queued.')
      }
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to queue code review.'))
    }
  }

  if (invalidId) {
    return (
      <section className="stack" aria-label="GitHub pull request detail">
        <article className="card">
          <h2>GitHub Pull Request</h2>
          <p className="error-text">Pull request id must be a positive integer.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="stack" aria-label="GitHub pull request detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>GitHub Pull Request</h2>
            <p>Conversation, commits, checks, and changed-file context.</p>
          </div>
          <div className="table-actions">
            <Link to="/github" className="btn-link btn-secondary">Back to GitHub</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
            <button type="button" className="btn-link" onClick={runCodeReview}>Run Code Review</button>
          </div>
        </div>
        <div className="toolbar">
          <div className="toolbar-group">
            <Link to={`/github/pulls/${parsedPrNumber}`} className={tab === 'conversation' ? 'btn-link' : 'btn-link btn-secondary'}>Conversation</Link>
            <Link to={`/github/pulls/${parsedPrNumber}/commits`} className={tab === 'commits' ? 'btn-link' : 'btn-link btn-secondary'}>Commits</Link>
            <Link to={`/github/pulls/${parsedPrNumber}/checks`} className={tab === 'checks' ? 'btn-link' : 'btn-link btn-secondary'}>Checks</Link>
            <Link to={`/github/pulls/${parsedPrNumber}/files`} className={tab === 'files' ? 'btn-link' : 'btn-link btn-secondary'}>Files</Link>
          </div>
        </div>
        {state.loading ? <p>Loading pull request...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.pull_request_error ? <p className="error-text">{String(payload.pull_request_error)}</p> : null}
        {payload?.comments_error ? <p className="error-text">{String(payload.comments_error)}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
      </article>

      {!state.loading && !state.error && pullRequest ? (
        <article className="card">
          <h2>#{pullRequest.number || parsedPrNumber} {pullRequest.title || ''}</h2>
          <div className="key-value-grid">
            <p><strong>State:</strong> {pullRequest.state || '-'}</p>
            <p><strong>Author:</strong> {pullRequest.author || '-'}</p>
            <p><strong>Base:</strong> {pullRequest.base_branch || '-'}</p>
            <p><strong>Head:</strong> {pullRequest.head_branch || '-'}</p>
          </div>
          {Array.isArray(pullRequest.labels) && pullRequest.labels.length > 0 ? (
            <p><strong>Labels:</strong> {pullRequest.labels.map((label) => label.name || '').filter(Boolean).join(', ') || '-'}</p>
          ) : null}
          {reviewers.length > 0 ? <p><strong>Reviewers:</strong> {reviewers.join(', ')}</p> : null}
        </article>
      ) : null}

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>{tab === 'conversation' ? 'Conversation' : tab === 'commits' ? 'Commits' : tab === 'checks' ? 'Checks' : 'Files'}</h2>
          {comments.length === 0 ? <p>No timeline entries returned.</p> : null}
          {comments.length > 0 ? (
            <ul className="stack">
              {comments.map((comment, index) => (
                <li key={`${comment.id || 'comment'}-${index}`}>
                  <strong>{comment.author || comment.actor || 'system'}:</strong> {comment.body || comment.text || comment.event || '-'}
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

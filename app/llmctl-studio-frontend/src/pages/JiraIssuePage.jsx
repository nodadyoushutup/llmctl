import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getJiraIssue } from '../lib/studioApi'

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

export default function JiraIssuePage() {
  const { issueKey } = useParams()
  const normalizedIssueKey = String(issueKey || '').trim()
  const invalidIssue = normalizedIssueKey.length === 0
  const [state, setState] = useState({ loading: !invalidIssue, payload: null, error: '' })

  const refresh = useCallback(async () => {
    if (invalidIssue) {
      return
    }
    setState((current) => ({ ...current, loading: true, error: '' }))
    try {
      const payload = await getJiraIssue(normalizedIssueKey)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Jira issue.') })
    }
  }, [invalidIssue, normalizedIssueKey])

  useEffect(() => {
    if (invalidIssue) {
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const payload = await getJiraIssue(normalizedIssueKey)
        if (active) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (active) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load Jira issue.') })
        }
      }
    })()
    return () => {
      active = false
    }
  }, [invalidIssue, normalizedIssueKey])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const issue = payload && payload.issue && typeof payload.issue === 'object' ? payload.issue : null
  const comments = payload && Array.isArray(payload.comments) ? payload.comments : []

  if (invalidIssue) {
    return (
      <section className="stack" aria-label="Jira issue detail">
        <article className="card">
          <h2>Jira Issue</h2>
          <p className="error-text">Issue key is required.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="stack" aria-label="Jira issue detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Jira Issue</h2>
            <p>Native React replacement for `/jira/issues/:issueKey` detail and comment surfaces.</p>
          </div>
          <div className="table-actions">
            <Link to="/jira" className="btn-link btn-secondary">Back to Jira</Link>
            <button type="button" className="btn-link btn-secondary" onClick={refresh}>Refresh</button>
          </div>
        </div>
        {state.loading ? <p>Loading issue...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {payload?.issue_error ? <p className="error-text">{String(payload.issue_error)}</p> : null}
        {payload?.comments_error ? <p className="error-text">{String(payload.comments_error)}</p> : null}
      </article>

      {!state.loading && !state.error && issue ? (
        <article className="card">
          <h2>{issue.key || normalizedIssueKey} - {issue.summary || 'Jira issue'}</h2>
          <div className="key-value-grid">
            <p><strong>Status:</strong> {issue.status?.name || issue.status || '-'}</p>
            <p><strong>Priority:</strong> {issue.priority?.name || issue.priority || '-'}</p>
            <p><strong>Assignee:</strong> {issue.assignee?.display_name || issue.assignee || '-'}</p>
            <p><strong>Reporter:</strong> {issue.reporter?.display_name || issue.reporter || '-'}</p>
          </div>
          <p>{issue.description || '-'}</p>
        </article>
      ) : null}

      {!state.loading && !state.error ? (
        <article className="card">
          <h2>Comments</h2>
          {comments.length === 0 ? <p>No comments found.</p> : null}
          {comments.length > 0 ? (
            <ul className="stack">
              {comments.map((comment, index) => (
                <li key={`${comment?.id || 'comment'}-${index}`}>
                  <strong>{comment?.author?.display_name || comment?.author || 'user'}:</strong> {comment?.body || comment?.text || '-'}
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
    </section>
  )
}

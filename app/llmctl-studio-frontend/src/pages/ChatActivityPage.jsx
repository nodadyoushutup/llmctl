import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import LegacyFallbackNote from '../components/LegacyFallbackNote'
import { HttpError } from '../lib/httpClient'
import { getChatActivity } from '../lib/studioApi'

function extractThreadId(item) {
  if (!item || typeof item !== 'object') {
    return null
  }
  const direct = item.thread_id
  if (Number.isInteger(direct) && direct > 0) {
    return direct
  }
  const thread = item.thread
  if (thread && typeof thread === 'object' && Number.isInteger(thread.id) && thread.id > 0) {
    return thread.id
  }
  return null
}

export default function ChatActivityPage() {
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const payload = await getChatActivity({ limit: 50 })
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      } catch (error) {
        if (!cancelled) {
          let message = error instanceof HttpError ? error.message : 'Failed to load chat activity.'
          if (error instanceof HttpError && error.isAuthError) {
            message = `${message} Sign in to Studio if authentication is enabled.`
          }
          setState({ loading: false, payload: null, error: message })
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  const items = useMemo(() => {
    if (!state.payload || typeof state.payload !== 'object') {
      return []
    }
    return Array.isArray(state.payload.items) ? state.payload.items : []
  }, [state.payload])

  return (
    <section className="stack" aria-label="Chat activity">
      <article className="card">
        <h2>Chat activity (React)</h2>
        <p>Wave 1 migration of the legacy chat activity page using <code>/api/chat/activity</code>.</p>
        <LegacyFallbackNote path="/chat/activity" label="Open /chat/activity" />
      </article>

      <article className="card">
        <h2>Recent activity</h2>
        {state.loading ? <p>Loading activity...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error && items.length === 0 ? (
          <p>No chat activity events available.</p>
        ) : null}
        <div className="activity-list">
          {items.map((item, index) => {
            const threadId = extractThreadId(item)
            const kind = item && typeof item === 'object' ? String(item.kind || item.type || 'event') : 'event'
            const createdAt =
              item && typeof item === 'object' ? String(item.created_at || item.updated_at || '') : ''
            return (
              <article key={`activity-${index}`} className="activity-item">
                <header>
                  <strong>{kind}</strong>
                  {createdAt ? <span>{createdAt}</span> : null}
                </header>
                {threadId ? (
                  <p>
                    Thread: <Link to={`/chat/threads/${threadId}`}>#{threadId}</Link>
                  </p>
                ) : null}
                <details>
                  <summary>Payload</summary>
                  <pre>{JSON.stringify(item, null, 2)}</pre>
                </details>
              </article>
            )
          })}
        </div>
      </article>
    </section>
  )
}

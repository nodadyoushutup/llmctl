import { useEffect, useState } from 'react'
import { getBackendHealth, getChatActivity } from '../lib/studioApi'
import { HttpError } from '../lib/httpClient'

function summarizeActivity(payload) {
  if (!payload || typeof payload !== 'object') {
    return { label: 'No payload', value: '-' }
  }
  const total = Array.isArray(payload.events)
    ? payload.events.length
    : (Array.isArray(payload.items) ? payload.items.length : 0)
  const hasNext = Boolean(payload.has_next || payload.hasNext)
  return {
    label: 'Recent chat events',
    value: `${total}${hasNext ? '+' : ''}`,
  }
}

export default function ApiDiagnosticsPage() {
  const [health, setHealth] = useState({ loading: true, data: null, error: '' })
  const [activity, setActivity] = useState({ loading: true, data: null, error: '' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const payload = await getBackendHealth()
        if (!cancelled) {
          setHealth({ loading: false, data: payload, error: '' })
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof HttpError ? error.message : 'Health request failed.'
          setHealth({ loading: false, data: null, error: message })
        }
      }

      try {
        const payload = await getChatActivity({ limit: 5 })
        if (!cancelled) {
          setActivity({ loading: false, data: payload, error: '' })
        }
      } catch (error) {
        if (!cancelled) {
          let message = error instanceof HttpError ? error.message : 'Chat activity request failed.'
          if (error instanceof HttpError && error.isAuthError) {
            message = `${message} Sign in to Studio if authentication is enabled.`
          }
          setActivity({ loading: false, data: null, error: message })
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  const activitySummary = summarizeActivity(activity.data)

  return (
    <section className="card-grid" aria-label="API diagnostics">
      <article className="card">
        <h2>Backend health</h2>
        {health.loading ? <p>Loading health check...</p> : null}
        {health.error ? <p className="error-text">{health.error}</p> : null}
        {health.data ? <pre>{JSON.stringify(health.data, null, 2)}</pre> : null}
      </article>

      <article className="card">
        <h2>Read endpoint probe</h2>
        {activity.loading ? <p>Loading chat activity...</p> : null}
        {activity.error ? <p className="error-text">{activity.error}</p> : null}
        {activity.data ? (
          <>
            <p>
              <strong>{activitySummary.label}:</strong> {activitySummary.value}
            </p>
            <pre>{JSON.stringify(activity.data, null, 2)}</pre>
          </>
        ) : null}
      </article>
    </section>
  )
}

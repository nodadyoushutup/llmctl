import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { getMemoryMeta } from '../lib/studioApi'

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

export default function MemoryNewPage() {
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getMemoryMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load memory create policy.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const message = payload?.message || 'Create memories by adding Memory nodes in a flowchart.'

  return (
    <section className="stack" aria-label="Memory create policy">
      <article className="card">
        <PanelHeader
          title="Memories Are Flowchart-Managed"
          titleTag="h2"
          actions={<Link to="/memories" className="btn-link btn-secondary">All Memories</Link>}
        />
        {state.loading ? <p>Loading policy details...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <div className="stack-sm">
            <p>{message}</p>
            <a href="/flowcharts" className="btn-link">Open Flowcharts</a>
          </div>
        ) : null}
      </article>
    </section>
  )
}

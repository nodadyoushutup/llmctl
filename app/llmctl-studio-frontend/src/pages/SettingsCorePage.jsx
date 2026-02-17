import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getSettingsCore } from '../lib/studioApi'

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

export default function SettingsCorePage() {
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getSettingsCore()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load core settings.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const coreConfig = state.payload?.core_config && typeof state.payload.core_config === 'object'
    ? state.payload.core_config
    : {}

  return (
    <section className="stack" aria-label="Settings core">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>Settings Core</h2>
            <p>Native React replacement for `/settings/core` runtime and path metadata.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/provider" className="btn-link btn-secondary">Provider</Link>
            <Link to="/settings/runtime" className="btn-link btn-secondary">Runtime</Link>
            <Link to="/settings/chat" className="btn-link btn-secondary">Chat</Link>
          </div>
        </div>
        {state.loading ? <p>Loading core settings...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <dl className="kv-grid">
            {Object.entries(coreConfig).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{String(value ?? '') || '-'}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </article>
    </section>
  )
}

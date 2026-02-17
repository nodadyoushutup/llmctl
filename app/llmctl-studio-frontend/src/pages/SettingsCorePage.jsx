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
            <h2>Core Settings</h2>
            <p>Paths, polling, and provider defaults.</p>
          </div>
          <div className="table-actions">
            <Link to="/settings/provider" className="btn-link btn-secondary">Provider</Link>
            <Link to="/settings/runtime" className="btn-link btn-secondary">Runtime</Link>
            <Link to="/settings/chat" className="btn-link btn-secondary">Chat</Link>
            <Link to="/settings/integrations" className="btn-link btn-secondary">Integrations</Link>
          </div>
        </div>
        {state.loading ? <p>Loading core settings...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <div className="stack">
            {Object.entries(coreConfig).map(([key, value]) => (
              <div key={key} className="subcard">
                <p className="eyebrow">{key}</p>
                <p className="muted" style={{ marginTop: '8px', fontSize: '12px' }}>
                  {String(value ?? '') || '-'}
                </p>
              </div>
            ))}
          </div>
        ) : null}
      </article>
    </section>
  )
}

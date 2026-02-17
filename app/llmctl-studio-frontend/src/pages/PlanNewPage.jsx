import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getPlanMeta } from '../lib/studioApi'

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

export default function PlanNewPage() {
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getPlanMeta()
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load plan create policy.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const message = payload?.message || 'Create plans by adding Plan nodes in a flowchart.'

  return (
    <section className="stack" aria-label="Plan create policy">
      <article className="card">
        <div className="title-row">
          <h2>Plans Are Flowchart-Managed</h2>
          <Link to="/plans" className="btn-link btn-secondary">All Plans</Link>
        </div>
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

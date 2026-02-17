import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getRunEdit } from '../lib/studioApi'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

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

export default function RunEditPage() {
  const { runId } = useParams()
  const parsedRunId = useMemo(() => parseId(runId), [runId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    if (!parsedRunId) {
      return
    }
    let cancelled = false
    getRunEdit(parsedRunId)
      .then((payload) => {
        if (!cancelled) {
          setState({ loading: false, payload, error: '' })
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load autorun metadata.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [parsedRunId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const run = payload && payload.run && typeof payload.run === 'object' ? payload.run : null
  const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
  const message = payload?.message || 'Autoruns are managed from the agent.'

  const invalidId = parsedRunId == null
  const loading = invalidId ? false : state.loading
  const error = invalidId ? 'Invalid run id.' : state.error

  return (
    <section className="stack" aria-label="Autorun edit">
      <article className="card">
        <div className="title-row">
          <h2>Autoruns are read-only</h2>
          <div className="table-actions">
            {run ? <Link to={`/runs/${run.id}`} className="btn-link btn-secondary">Back to Autorun</Link> : null}
            <Link to="/runs" className="btn-link btn-secondary">All Autoruns</Link>
          </div>
        </div>
        {loading ? <p>Loading autorun metadata...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        {!loading && !error ? (
          <div className="stack-sm">
            <p>{message}</p>
            <div className="table-actions">
              {agent ? (
                <Link to={`/agents/${agent.id}/edit`} className="btn-link">Edit Agent Settings</Link>
              ) : null}
              {agent ? (
                <Link to={`/agents/${agent.id}`} className="btn-link btn-secondary">View Agent</Link>
              ) : null}
            </div>
          </div>
        ) : null}
      </article>
    </section>
  )
}

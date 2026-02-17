import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getRunMeta } from '../lib/studioApi'

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

export default function RunNewPage() {
  const [searchParams] = useSearchParams()
  const selectedAgentId = parseId(searchParams.get('agent_id'))
  const [state, setState] = useState({ loading: true, payload: null, error: '' })

  useEffect(() => {
    let cancelled = false
    getRunMeta({ agentId: selectedAgentId })
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
  }, [selectedAgentId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const agents = payload && Array.isArray(payload.agents) ? payload.agents : []
  const selectedAgent = agents.find((agent) => agent.id === payload?.selected_agent_id) || null
  const message = payload?.message || 'Autoruns are created when autorun is enabled on an agent.'

  return (
    <section className="stack" aria-label="Autorun policy">
      <article className="card">
        <div className="title-row">
          <h2>Autoruns are automatic</h2>
          <div className="table-actions">
            <Link to="/runs" className="btn-link btn-secondary">All Autoruns</Link>
          </div>
        </div>
        {state.loading ? <p>Loading policy details...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {!state.loading && !state.error ? (
          <div className="stack-sm">
            <p>{message}</p>
            {selectedAgent ? (
              <p className="toolbar-meta">
                Current selection: <Link to={`/agents/${selectedAgent.id}`}>{selectedAgent.name}</Link>
              </p>
            ) : null}
            <div className="table-actions">
              <Link to="/agents" className="btn-link">Manage Agents</Link>
              {selectedAgent ? (
                <Link to={`/agents/${selectedAgent.id}/edit`} className="btn-link btn-secondary">
                  Edit Selected Agent
                </Link>
              ) : null}
            </div>
          </div>
        ) : null}
      </article>
    </section>
  )
}

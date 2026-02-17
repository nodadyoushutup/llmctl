import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { HttpError } from '../lib/httpClient'
import { getAgents } from '../lib/studioApi'

function errorMessage(error) {
  if (error instanceof HttpError) {
    if (error.isAuthError) {
      return `${error.message} Sign in to Studio if authentication is enabled.`
    }
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return 'Failed to load dashboard overview.'
}

function isActiveStatus(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'starting' || normalized === 'running' || normalized === 'stopping'
}

export default function OverviewPage() {
  const [state, setState] = useState({ loading: true, agents: [], error: '' })

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const payload = await getAgents()
        const items = payload && typeof payload === 'object' && Array.isArray(payload.agents)
          ? payload.agents
          : []
        if (!active) {
          return
        }
        setState({ loading: false, agents: items, error: '' })
      } catch (error) {
        if (!active) {
          return
        }
        setState({ loading: false, agents: [], error: errorMessage(error) })
      }
    }

    load()
    return () => {
      active = false
    }
  }, [])

  const activeAgents = useMemo(
    () => state.agents.filter((agent) => isActiveStatus(agent.status)).slice(0, 5),
    [state.agents],
  )

  const recentAgents = useMemo(
    () => [...state.agents].sort((left, right) => Number(right.id || 0) - Number(left.id || 0)).slice(0, 5),
    [state.agents],
  )

  const recentRuns = useMemo(
    () => [...state.agents]
      .filter((agent) => String(agent.last_run_at || '').trim())
      .sort((left, right) => Number(right.id || 0) - Number(left.id || 0))
      .slice(0, 5),
    [state.agents],
  )

  const summary = {
    total: state.agents.length,
    active: activeAgents.length,
    lastRunAt: recentRuns[0]?.last_run_at || '-',
  }

  return (
    <section className="stack" aria-label="Overview">
      {state.loading ? <p className="muted">Loading overview...</p> : null}
      {state.error ? <p className="error-text">{state.error}</p> : null}

      <section className="grid grid-3">
        <article className="card">
          <div className="card-header">
            <h2 className="section-title">Overview</h2>
          </div>
          <p className="muted" style={{ marginTop: '12px' }}>
            Track agent density, active load, and the last known autorun signal.
          </p>
          <div className="grid grid-2" style={{ marginTop: '20px' }}>
            <div className="stat-card">
              <p className="eyebrow">total</p>
              <p style={{ marginTop: '8px', fontSize: '24px' }}>{summary.total}</p>
            </div>
            <div className="stat-card">
              <p className="eyebrow">active</p>
              <p style={{ marginTop: '8px', fontSize: '24px' }}>{summary.active}</p>
            </div>
          </div>
          <div className="subcard" style={{ marginTop: '18px' }}>
            <p className="eyebrow">last autorun</p>
            <p style={{ marginTop: '8px' }}>{summary.lastRunAt}</p>
          </div>
        </article>

        <article className="card">
          <div className="card-header">
            <h2 className="section-title">Newest Agents</h2>
          </div>
          <div className="stack" style={{ marginTop: '20px' }}>
            {recentAgents.length > 0 ? recentAgents.map((agent) => (
              <div key={agent.id} className="row-between">
                <div>
                  <p>
                    <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                  </p>
                  <p className="muted" style={{ marginTop: '4px', fontSize: '12px' }}>
                    created {agent.created_at || '-'}
                  </p>
                </div>
              </div>
            )) : <p className="muted">No agents created yet.</p>}
          </div>
        </article>

        <article className="card">
          <div className="card-header">
            <h2 className="section-title">Autorun Feed</h2>
          </div>
          <div className="stack" style={{ marginTop: '20px' }}>
            {recentRuns.length > 0 ? recentRuns.map((agent) => (
              <div key={agent.id} className="subcard">
                <div className="row-between">
                  <p>
                    <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                  </p>
                </div>
                <p className="muted" style={{ marginTop: '8px', fontSize: '12px' }}>
                  last autorun {agent.last_run_at}
                </p>
              </div>
            )) : <p className="muted">No autoruns recorded yet.</p>}
          </div>
        </article>
      </section>

      <section className="grid">
        <article className="card">
          <div className="card-header">
            <h2 className="section-title">Active Agents</h2>
          </div>
          <div className="stack" style={{ marginTop: '20px' }}>
            {activeAgents.length > 0 ? activeAgents.map((agent) => (
              <div key={agent.id} className="subcard">
                <div className="row-between">
                  <p>
                    <Link to={`/agents/${agent.id}`}>{agent.name}</Link>
                  </p>
                </div>
                <p className="muted" style={{ marginTop: '8px', fontSize: '12px' }}>
                  last autorun {agent.last_run_at || '-'}
                </p>
              </div>
            )) : <p className="muted">No active agents right now.</p>}
          </div>
        </article>
      </section>
    </section>
  )
}

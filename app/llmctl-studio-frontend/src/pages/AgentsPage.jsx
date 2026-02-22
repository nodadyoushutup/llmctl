import { useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { deleteAgent, getAgents, startAgent, stopAgent } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

function agentStatusClassName(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'starting') {
    return 'status-chip status-running'
  }
  if (normalized === 'stopping') {
    return 'status-chip status-warning'
  }
  if (normalized === 'error') {
    return 'status-chip status-failed'
  }
  return 'status-chip status-idle'
}

function agentStatusLabel(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'starting') {
    return 'on'
  }
  if (normalized === 'stopping') {
    return 'stopping'
  }
  if (normalized === 'error') {
    return 'error'
  }
  return 'off'
}

function loadErrorMessage(error) {
  if (error instanceof HttpError) {
    if (error.isAuthError) {
      return `${error.message} Sign in to Studio if authentication is enabled.`
    }
    return error.message
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return 'Failed to load agents.'
}

export default function AgentsPage() {
  const navigate = useNavigate()
  const [state, setState] = useState({ loading: true, agents: [], error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busyById, setBusyById] = useState({})

  async function refresh() {
    try {
      const payload = await getAgents()
      const items = payload && typeof payload === 'object' && Array.isArray(payload.agents) ? payload.agents : []
      setState({ loading: false, agents: items, error: '' })
    } catch (error) {
      setState({ loading: false, agents: [], error: loadErrorMessage(error) })
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const agents = useMemo(() => state.agents, [state.agents])

  function setBusy(agentId, busy) {
    setBusyById((current) => {
      const next = { ...current }
      if (busy) {
        next[agentId] = true
      } else {
        delete next[agentId]
      }
      return next
    })
  }

  async function handleStart(agentId) {
    setActionError('')
    setBusy(agentId, true)
    try {
      await startAgent(agentId)
      await refresh()
    } catch (error) {
      setActionError(loadErrorMessage(error))
    } finally {
      setBusy(agentId, false)
    }
  }

  async function handleStop(agentId) {
    setActionError('')
    setBusy(agentId, true)
    try {
      await stopAgent(agentId)
      await refresh()
    } catch (error) {
      setActionError(loadErrorMessage(error))
    } finally {
      setBusy(agentId, false)
    }
  }

  async function handleDelete(agentId) {
    if (!window.confirm('Delete this agent?')) {
      return
    }
    setActionError('')
    setBusy(agentId, true)
    try {
      await deleteAgent(agentId)
      await refresh()
    } catch (error) {
      setActionError(loadErrorMessage(error))
    } finally {
      setBusy(agentId, false)
    }
  }

  function handleRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack workflow-fixed-page" aria-label="Agents">
      <article className="card panel-card workflow-list-card">
        <PanelHeader
          title="All Agents"
          actions={(
            <Link to="/agents/new" className="icon-button" aria-label="New agent" title="New agent">
              <ActionIcon name="plus" />
            </Link>
          )}
        />
        <div className="panel-card-body workflow-fixed-panel-body">
          <p className="panel-header-copy">
            Open an agent to see its autorun history, connections, and prompt configuration.
          </p>
          {state.loading ? <p>Loading agents...</p> : null}
          {state.error ? <p className="error-text">{state.error}</p> : null}
          {actionError ? <p className="error-text">{actionError}</p> : null}
          {!state.loading && !state.error && agents.length === 0 ? <p>No agents created yet.</p> : null}
          {!state.loading && !state.error && agents.length > 0 ? (
            <div className="table-wrap workflow-list-table-shell">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Role</th>
                    <th>Autorun</th>
                    <th className="table-actions-cell">Autorun</th>
                    <th className="table-actions-cell">Delete</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => {
                    const status = String(agent.status || 'stopped')
                    const active = ['running', 'starting', 'stopping'].includes(status)
                    const busy = Boolean(busyById[agent.id])
                    const href = `/agents/${agent.id}`
                    return (
                      <tr
                        key={agent.id}
                        className="table-row-link"
                        data-href={href}
                        onClick={(event) => handleRowClick(event, href)}
                      >
                        <td>
                          <Link to={href}>{agent.name}</Link>
                        </td>
                        <td>
                          <span className="chip">{agent.is_system ? 'system' : 'user'}</span>
                        </td>
                        <td>{agent.role_name || '-'}</td>
                        <td>
                          <span className={agentStatusClassName(status)}>
                            {agentStatusLabel(status)}
                          </span>
                        </td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            {active ? (
                              <button
                                type="button"
                                className="icon-button"
                                aria-label="Disable autorun"
                                title="Disable autorun"
                                disabled={busy}
                                onClick={() => handleStop(agent.id)}
                              >
                                <ActionIcon name="stop" />
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="icon-button"
                                aria-label="Enable autorun"
                                title="Enable autorun"
                                disabled={busy}
                                onClick={() => handleStart(agent.id)}
                              >
                                <ActionIcon name="play" />
                              </button>
                            )}
                          </div>
                        </td>
                        <td className="table-actions-cell">
                          <div className="table-actions">
                            <button
                              type="button"
                              className="icon-button icon-button-danger"
                              aria-label="Delete agent"
                              title="Delete agent"
                              disabled={busy}
                              onClick={() => handleDelete(agent.id)}
                            >
                              <ActionIcon name="trash" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </article>
    </section>
  )
}

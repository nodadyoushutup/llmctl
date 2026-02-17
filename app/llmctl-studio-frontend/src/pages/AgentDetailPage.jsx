import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import { getAgent, startAgent, stopAgent } from '../lib/studioApi'
import { shouldIgnoreRowClick } from '../lib/tableRowLink'

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

function statusMeta(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'starting') {
    return { className: 'status-chip status-running', label: 'autorun on' }
  }
  if (normalized === 'stopping') {
    return { className: 'status-chip status-warning', label: 'autorun stopping' }
  }
  if (normalized === 'error') {
    return { className: 'status-chip status-failed', label: 'autorun error' }
  }
  return { className: 'status-chip status-idle', label: 'autorun off' }
}

export default function AgentDetailPage() {
  const navigate = useNavigate()
  const { agentId } = useParams()
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)

  const parsedAgentId = useMemo(() => {
    const parsed = Number.parseInt(String(agentId || ''), 10)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null
  }, [agentId])

  const refresh = useCallback(async () => {
    if (!parsedAgentId) {
      setState({ loading: false, payload: null, error: 'Invalid agent id.' })
      return
    }
    try {
      const payload = await getAgent(parsedAgentId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState({ loading: false, payload: null, error: errorMessage(error, 'Failed to load agent.') })
    }
  }, [parsedAgentId])

  useEffect(() => {
    setState({ loading: true, payload: null, error: '' })
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
  const priorities = payload && Array.isArray(payload.priorities) ? payload.priorities : []
  const assignedSkills = payload && Array.isArray(payload.assigned_skills) ? payload.assigned_skills : []

  async function handleStart() {
    if (!parsedAgentId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await startAgent(parsedAgentId)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to enable autorun.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    if (!parsedAgentId) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await stopAgent(parsedAgentId)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to disable autorun.'))
    } finally {
      setBusy(false)
    }
  }

  function handleSkillRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Agent detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{agent ? agent.name : 'Agent'}</h2>
            {agent && agent.description ? <p>{agent.description}</p> : null}
          </div>
          <div className="table-actions">
            {agent ? (
              <Link to={`/agents/${agent.id}/edit`} className="btn-link">
                Edit
              </Link>
            ) : null}
            <Link to="/agents" className="btn-link btn-secondary">
              All Agents
            </Link>
          </div>
        </div>
        {state.loading ? <p>Loading agent...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {agent ? (
          <div className="stack-sm">
            <div className="table-actions">
              <span className={statusMeta(agent.status).className}>{statusMeta(agent.status).label}</span>
              {['running', 'starting', 'stopping'].includes(String(agent.status || '').toLowerCase()) ? (
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Disable autorun"
                  title="Disable autorun"
                  disabled={busy}
                  onClick={handleStop}
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
                  onClick={handleStart}
                >
                  <ActionIcon name="play" />
                </button>
              )}
            </div>
            <dl className="kv-grid">
              <div>
                <dt>Role</dt>
                <dd>{agent.role_name || '-'}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{agent.created_at || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{agent.updated_at || '-'}</dd>
              </div>
            </dl>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Priorities</h2>
        {priorities.length === 0 ? <p>No priorities configured.</p> : null}
        {priorities.length > 0 ? (
          <ol className="priority-list">
            {priorities.map((priority) => (
              <li key={priority.id}>{priority.content}</li>
            ))}
          </ol>
        ) : null}
      </article>

      <article className="card">
        <h2>Skills</h2>
        {assignedSkills.length === 0 ? <p>No skills assigned.</p> : null}
        {assignedSkills.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Latest version</th>
                </tr>
              </thead>
              <tbody>
                {assignedSkills.map((skill) => {
                  const href = `/skills/${skill.id}`
                  return (
                    <tr
                      key={skill.id}
                      className="table-row-link"
                      data-href={href}
                      onClick={(event) => handleSkillRowClick(event, href)}
                    >
                      <td>
                        <a href={href}>{skill.display_name}</a>
                      </td>
                      <td>{skill.status || '-'}</td>
                      <td>{skill.latest_version || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}

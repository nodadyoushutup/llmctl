import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import {
  attachAgentSkill,
  createAgentPriority,
  deleteAgentPriority,
  detachAgentSkill,
  getAgent,
  moveAgentPriority,
  moveAgentSkill,
  updateAgent,
  updateAgentPriority,
} from '../lib/studioApi'
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

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export default function AgentEditPage() {
  const navigate = useNavigate()
  const { agentId } = useParams()
  const parsedAgentId = useMemo(() => parseId(agentId), [agentId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [validationError, setValidationError] = useState('')
  const [, setActionError] = useFlashState('error')
  const [savingAgent, setSavingAgent] = useState(false)
  const [busyPriorityId, setBusyPriorityId] = useState(null)
  const [busySkillId, setBusySkillId] = useState(null)
  const [addingPriority, setAddingPriority] = useState(false)
  const [attachingSkill, setAttachingSkill] = useState(false)
  const [priorityDrafts, setPriorityDrafts] = useState({})
  const [newPriority, setNewPriority] = useState('')
  const [attachSkillId, setAttachSkillId] = useState('')
  const [agentForm, setAgentForm] = useState({
    name: '',
    description: '',
    roleId: '',
  })

  const refresh = useCallback(async () => {
    if (!parsedAgentId) {
      setState({ loading: false, payload: null, error: 'Invalid agent id.' })
      return
    }
    try {
      const payload = await getAgent(parsedAgentId)
      const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
      const priorities = payload && Array.isArray(payload.priorities) ? payload.priorities : []
      const prioritySeed = {}
      for (const priority of priorities) {
        prioritySeed[priority.id] = String(priority.content || '')
      }
      setPriorityDrafts(prioritySeed)
      if (agent) {
        setAgentForm({
          name: String(agent.name || ''),
          description: String(agent.description || ''),
          roleId: agent.role_id ? String(agent.role_id) : '',
        })
      }
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
  const roles = payload && Array.isArray(payload.roles) ? payload.roles : []
  const priorities = payload && Array.isArray(payload.priorities) ? payload.priorities : []
  const assignedSkills = payload && Array.isArray(payload.assigned_skills) ? payload.assigned_skills : []
  const availableSkills = payload && Array.isArray(payload.available_skills) ? payload.available_skills : []

  async function handleAgentSave(event) {
    event.preventDefault()
    if (!parsedAgentId) {
      return
    }
    setValidationError('')
    setActionError('')
    const description = String(agentForm.description || '').trim()
    if (!description) {
      setValidationError('Description is required.')
      return
    }
    setSavingAgent(true)
    try {
      const roleId = agentForm.roleId ? parseId(agentForm.roleId) : null
      await updateAgent(parsedAgentId, {
        name: String(agentForm.name || '').trim(),
        description,
        roleId: roleId || null,
      })
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update agent.'))
    } finally {
      setSavingAgent(false)
    }
  }

  async function handlePrioritySave(priorityId) {
    if (!parsedAgentId) {
      return
    }
    const content = String(priorityDrafts[priorityId] || '').trim()
    if (!content) {
      setActionError('Priority content is required.')
      return
    }
    setActionError('')
    setBusyPriorityId(priorityId)
    try {
      await updateAgentPriority(parsedAgentId, priorityId, content)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update priority.'))
    } finally {
      setBusyPriorityId(null)
    }
  }

  async function handlePriorityMove(priorityId, direction) {
    if (!parsedAgentId) {
      return
    }
    setActionError('')
    setBusyPriorityId(priorityId)
    try {
      await moveAgentPriority(parsedAgentId, priorityId, direction)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to reorder priority.'))
    } finally {
      setBusyPriorityId(null)
    }
  }

  async function handlePriorityDelete(priorityId) {
    if (!parsedAgentId || !window.confirm('Delete this priority?')) {
      return
    }
    setActionError('')
    setBusyPriorityId(priorityId)
    try {
      await deleteAgentPriority(parsedAgentId, priorityId)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete priority.'))
    } finally {
      setBusyPriorityId(null)
    }
  }

  async function handlePriorityCreate(event) {
    event.preventDefault()
    if (!parsedAgentId) {
      return
    }
    const content = String(newPriority || '').trim()
    if (!content) {
      setActionError('Priority content is required.')
      return
    }
    setActionError('')
    setAddingPriority(true)
    try {
      await createAgentPriority(parsedAgentId, content)
      setNewPriority('')
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to add priority.'))
    } finally {
      setAddingPriority(false)
    }
  }

  async function handleSkillMove(skillId, direction) {
    if (!parsedAgentId) {
      return
    }
    setActionError('')
    setBusySkillId(skillId)
    try {
      await moveAgentSkill(parsedAgentId, skillId, direction)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to reorder skill.'))
    } finally {
      setBusySkillId(null)
    }
  }

  async function handleSkillDetach(skillId) {
    if (!parsedAgentId || !window.confirm('Remove this skill from the agent?')) {
      return
    }
    setActionError('')
    setBusySkillId(skillId)
    try {
      await detachAgentSkill(parsedAgentId, skillId)
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to remove skill.'))
    } finally {
      setBusySkillId(null)
    }
  }

  async function handleSkillAttach(event) {
    event.preventDefault()
    if (!parsedAgentId) {
      return
    }
    const skillId = parseId(attachSkillId)
    if (!skillId) {
      setActionError('Select a skill to assign.')
      return
    }
    setActionError('')
    setAttachingSkill(true)
    try {
      await attachAgentSkill(parsedAgentId, skillId)
      setAttachSkillId('')
      await refresh()
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to assign skill.'))
    } finally {
      setAttachingSkill(false)
    }
  }

  function handleSkillRowClick(event, href) {
    if (shouldIgnoreRowClick(event.target)) {
      return
    }
    navigate(href)
  }

  return (
    <section className="stack" aria-label="Edit agent">
      <article className="card">
        <div className="title-row">
          <h2>{agent ? `Edit ${agent.name}` : 'Edit Agent'}</h2>
          <div className="table-actions">
            {agent ? (
              <Link to={`/agents/${agent.id}`} className="btn-link btn-secondary">
                Back to Agent
              </Link>
            ) : null}
            <Link to="/agents" className="btn-link btn-secondary">
              All Agents
            </Link>
          </div>
        </div>
        {state.loading ? <p>Loading agent...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {validationError ? <p className="error-text">{validationError}</p> : null}
        {agent ? (
          <form className="form-grid" onSubmit={handleAgentSave}>
            <label className="field">
              <span>Name (optional)</span>
              <input
                type="text"
                value={agentForm.name}
                onChange={(event) => setAgentForm((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Description</span>
              <textarea
                required
                value={agentForm.description}
                onChange={(event) =>
                  setAgentForm((current) => ({ ...current, description: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Role (optional)</span>
              <select
                value={agentForm.roleId}
                onChange={(event) => setAgentForm((current) => ({ ...current, roleId: event.target.value }))}
              >
                <option value="">No role</option>
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-actions">
              <button type="submit" className="btn-link" disabled={savingAgent}>
                {savingAgent ? 'Saving...' : 'Save Agent'}
              </button>
            </div>
          </form>
        ) : null}
      </article>

      <article className="card">
        <h2>Priorities</h2>
        {priorities.length === 0 ? <p>No priorities configured yet.</p> : null}
        {priorities.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Content</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {priorities.map((priority, index) => (
                  <tr key={priority.id}>
                    <td>{index + 1}</td>
                    <td>
                      <textarea
                        className="table-textarea"
                        value={priorityDrafts[priority.id] || ''}
                        onChange={(event) =>
                          setPriorityDrafts((current) => ({
                            ...current,
                            [priority.id]: event.target.value,
                          }))
                        }
                      />
                    </td>
                    <td className="table-actions-cell">
                      <div className="table-actions">
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Save priority"
                          title="Save priority"
                          disabled={busyPriorityId === priority.id}
                          onClick={() => handlePrioritySave(priority.id)}
                        >
                          <ActionIcon name="save" />
                        </button>
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Move priority up"
                          title="Move priority up"
                          disabled={busyPriorityId === priority.id || index === 0}
                          onClick={() => handlePriorityMove(priority.id, 'up')}
                        >
                          <ActionIcon name="up" />
                        </button>
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Move priority down"
                          title="Move priority down"
                          disabled={busyPriorityId === priority.id || index === priorities.length - 1}
                          onClick={() => handlePriorityMove(priority.id, 'down')}
                        >
                          <ActionIcon name="down" />
                        </button>
                        <button
                          type="button"
                          className="icon-button icon-button-danger"
                          aria-label="Delete priority"
                          title="Delete priority"
                          disabled={busyPriorityId === priority.id}
                          onClick={() => handlePriorityDelete(priority.id)}
                        >
                          <ActionIcon name="trash" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <form className="form-grid" onSubmit={handlePriorityCreate}>
          <label className="field field-span">
            <span>Add priority</span>
            <textarea
              value={newPriority}
              onChange={(event) => setNewPriority(event.target.value)}
              placeholder="Describe a high-level decision priority."
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="icon-button" aria-label="Add priority" title="Add priority" disabled={addingPriority}>
              <ActionIcon name="plus" />
            </button>
          </div>
        </form>
      </article>

      <article className="card">
        <h2>Skills</h2>
        {assignedSkills.length === 0 ? <p>No skills assigned yet.</p> : null}
        {assignedSkills.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Latest version</th>
                  <th className="table-actions-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {assignedSkills.map((skill, index) => {
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
                      <td className="table-actions-cell">
                        <div className="table-actions">
                          <button
                            type="button"
                            className="icon-button"
                            aria-label="Move skill up"
                            title="Move skill up"
                            disabled={busySkillId === skill.id || index === 0}
                            onClick={() => handleSkillMove(skill.id, 'up')}
                          >
                            <ActionIcon name="up" />
                          </button>
                          <button
                            type="button"
                            className="icon-button"
                            aria-label="Move skill down"
                            title="Move skill down"
                            disabled={busySkillId === skill.id || index === assignedSkills.length - 1}
                            onClick={() => handleSkillMove(skill.id, 'down')}
                          >
                            <ActionIcon name="down" />
                          </button>
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label="Remove skill"
                            title="Remove skill"
                            disabled={busySkillId === skill.id}
                            onClick={() => handleSkillDetach(skill.id)}
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
        <form className="form-grid" onSubmit={handleSkillAttach}>
          <label className="field field-span">
            <span>Add skill</span>
            <select value={attachSkillId} onChange={(event) => setAttachSkillId(event.target.value)}>
              <option value="">Select a skill</option>
              {availableSkills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.display_name} ({skill.status})
                </option>
              ))}
            </select>
          </label>
          <div className="form-actions">
            <button
              type="submit"
              className="icon-button"
              aria-label="Assign skill"
              title="Assign skill"
              disabled={attachingSkill}
            >
              <ActionIcon name="plus" />
            </button>
          </div>
        </form>
      </article>
    </section>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import { HttpError } from '../lib/httpClient'
import {
  createPlanStage,
  createPlanTask,
  deletePlan,
  deletePlanStage,
  deletePlanTask,
  getPlan,
  updatePlanStage,
  updatePlanTask,
} from '../lib/studioApi'

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

function parseCompletedAtInput(value) {
  const normalized = String(value || '').trim()
  if (!normalized || normalized === '-') {
    return ''
  }
  if (normalized.includes(' ')) {
    return normalized.replace(' ', 'T')
  }
  return normalized
}

export default function PlanDetailPage() {
  const navigate = useNavigate()
  const { planId } = useParams()
  const parsedPlanId = useMemo(() => parseId(planId), [planId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [newStage, setNewStage] = useState({ name: '', description: '', completedAt: '' })
  const [newTaskByStageId, setNewTaskByStageId] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!parsedPlanId) {
      setState({ loading: false, payload: null, error: 'Invalid plan id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getPlan(parsedPlanId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load plan detail.'),
      }))
    }
  }, [parsedPlanId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const plan = payload && payload.plan && typeof payload.plan === 'object' ? payload.plan : null
  const stages = plan && Array.isArray(plan.stages) ? plan.stages : []
  const summary = payload && payload.summary && typeof payload.summary === 'object' ? payload.summary : null

  async function handleDeletePlan() {
    if (!plan || !window.confirm('Delete this plan?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deletePlan(plan.id)
      navigate('/plans')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete plan.'))
    }
  }

  async function handleCreateStage(event) {
    event.preventDefault()
    if (!plan) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await createPlanStage(plan.id, newStage)
      setNewStage({ name: '', description: '', completedAt: '' })
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to add stage.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleEditStage(stage) {
    if (!plan || !stage) {
      return
    }
    const nextName = window.prompt('Stage name', String(stage.name || ''))
    if (nextName == null) {
      return
    }
    const nextDescription = window.prompt('Stage description (optional)', String(stage.description || ''))
    if (nextDescription == null) {
      return
    }
    const nextCompletedAt = window.prompt(
      'Completed at (optional, ISO date/time)',
      parseCompletedAtInput(stage.completed_at),
    )
    if (nextCompletedAt == null) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updatePlanStage(plan.id, stage.id, {
        name: nextName,
        description: nextDescription,
        completedAt: nextCompletedAt,
      })
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update stage.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteStage(stageId) {
    if (!plan || !window.confirm('Delete this stage and its tasks?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deletePlanStage(plan.id, stageId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete stage.'))
    } finally {
      setBusy(false)
    }
  }

  function updateNewTask(stageId, patch) {
    setNewTaskByStageId((current) => ({
      ...current,
      [stageId]: {
        name: '',
        description: '',
        completedAt: '',
        ...(current[stageId] || {}),
        ...patch,
      },
    }))
  }

  async function handleCreateTask(event, stageId) {
    event.preventDefault()
    if (!plan) {
      return
    }
    const draft = newTaskByStageId[stageId] || { name: '', description: '', completedAt: '' }
    setActionError('')
    setBusy(true)
    try {
      await createPlanTask(plan.id, stageId, draft)
      updateNewTask(stageId, { name: '', description: '', completedAt: '' })
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to add task.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleEditTask(stageId, task) {
    if (!plan || !task) {
      return
    }
    const nextName = window.prompt('Task name', String(task.name || ''))
    if (nextName == null) {
      return
    }
    const nextDescription = window.prompt('Task description (optional)', String(task.description || ''))
    if (nextDescription == null) {
      return
    }
    const nextCompletedAt = window.prompt(
      'Completed at (optional, ISO date/time)',
      parseCompletedAtInput(task.completed_at),
    )
    if (nextCompletedAt == null) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updatePlanTask(plan.id, stageId, task.id, {
        name: nextName,
        description: nextDescription,
        completedAt: nextCompletedAt,
      })
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to update task.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteTask(stageId, taskId) {
    if (!plan || !window.confirm('Delete this task?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deletePlanTask(plan.id, stageId, taskId)
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to delete task.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="stack" aria-label="Plan detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{plan ? plan.name : 'Plan'}</h2>
            <p>Native React detail for `/plans/:planId` with stage/task mutations.</p>
          </div>
          <div className="table-actions">
            {plan ? <Link to={`/plans/${plan.id}/edit`} className="btn-link btn-secondary">Edit Plan</Link> : null}
            <Link to="/plans" className="btn-link btn-secondary">All Plans</Link>
            {plan ? (
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete plan"
                title="Delete plan"
                disabled={busy}
                onClick={handleDeletePlan}
              >
                <ActionIcon name="trash" />
              </button>
            ) : null}
          </div>
        </div>
        {state.loading ? <p>Loading plan...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {plan ? (
          <dl className="kv-grid">
            <div>
              <dt>Description</dt>
              <dd>{plan.description || '-'}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>{plan.completed_at || '-'}</dd>
            </div>
            <div>
              <dt>Stages</dt>
              <dd>{summary?.stage_count ?? stages.length}</dd>
            </div>
            <div>
              <dt>Tasks</dt>
              <dd>{summary?.task_count ?? 0}</dd>
            </div>
          </dl>
        ) : null}
      </article>

      <article className="card">
        <h2>Add Stage</h2>
        <form className="form-grid" onSubmit={handleCreateStage}>
          <label className="field">
            <span>Stage name</span>
            <input
              type="text"
              required
              value={newStage.name}
              onChange={(event) => setNewStage((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Completed at (optional)</span>
            <input
              type="text"
              value={newStage.completedAt}
              onChange={(event) => setNewStage((current) => ({ ...current, completedAt: event.target.value }))}
              placeholder="YYYY-MM-DDTHH:MM"
            />
          </label>
          <label className="field field-span">
            <span>Description (optional)</span>
            <textarea
              value={newStage.description}
              onChange={(event) => setNewStage((current) => ({ ...current, description: event.target.value }))}
            />
          </label>
          <div className="form-actions">
            <button type="submit" className="btn-link" disabled={busy}>
              Add Stage
            </button>
          </div>
        </form>
      </article>

      <article className="card">
        <h2>Plan Outline</h2>
        {stages.length === 0 ? <p>No stages yet.</p> : null}
        {stages.map((stage, index) => {
          const tasks = Array.isArray(stage.tasks) ? stage.tasks : []
          const draft = newTaskByStageId[stage.id] || { name: '', description: '', completedAt: '' }
          return (
            <details key={stage.id} className="card" open={index === 0}>
              <summary className="title-row">
                <strong>{stage.name}</strong>
                <div className="table-actions">
                  <span className="chip">{tasks.length} task{tasks.length === 1 ? '' : 's'}</span>
                  <span className="toolbar-meta">completed: {stage.completed_at || '-'}</span>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Edit stage"
                    title="Edit stage"
                    disabled={busy}
                    onClick={(event) => {
                      event.preventDefault()
                      handleEditStage(stage)
                    }}
                  >
                    <ActionIcon name="edit" />
                  </button>
                  <button
                    type="button"
                    className="icon-button icon-button-danger"
                    aria-label="Delete stage"
                    title="Delete stage"
                    disabled={busy}
                    onClick={(event) => {
                      event.preventDefault()
                      handleDeleteStage(stage.id)
                    }}
                  >
                    <ActionIcon name="trash" />
                  </button>
                </div>
              </summary>
              {stage.description ? <p>{stage.description}</p> : null}
              <div className="stack-sm">
                <h3>Tasks</h3>
                {tasks.length === 0 ? <p className="toolbar-meta">No tasks for this stage yet.</p> : null}
                {tasks.length > 0 ? (
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Task</th>
                          <th>Completed</th>
                          <th className="table-actions-cell">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((task) => (
                          <tr key={task.id}>
                            <td>
                              <strong>{task.name}</strong>
                              {task.description ? <p className="table-note">{task.description}</p> : null}
                            </td>
                            <td>{task.completed_at || '-'}</td>
                            <td className="table-actions-cell">
                              <div className="table-actions">
                                <button
                                  type="button"
                                  className="icon-button"
                                  aria-label="Edit task"
                                  title="Edit task"
                                  disabled={busy}
                                  onClick={() => handleEditTask(stage.id, task)}
                                >
                                  <ActionIcon name="edit" />
                                </button>
                                <button
                                  type="button"
                                  className="icon-button icon-button-danger"
                                  aria-label="Delete task"
                                  title="Delete task"
                                  disabled={busy}
                                  onClick={() => handleDeleteTask(stage.id, task.id)}
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
                <h3>Add Task</h3>
                <form className="form-grid" onSubmit={(event) => handleCreateTask(event, stage.id)}>
                  <label className="field">
                    <span>Task name</span>
                    <input
                      type="text"
                      required
                      value={draft.name}
                      onChange={(event) => updateNewTask(stage.id, { name: event.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>Completed at (optional)</span>
                    <input
                      type="text"
                      value={draft.completedAt}
                      placeholder="YYYY-MM-DDTHH:MM"
                      onChange={(event) => updateNewTask(stage.id, { completedAt: event.target.value })}
                    />
                  </label>
                  <label className="field field-span">
                    <span>Description (optional)</span>
                    <textarea
                      value={draft.description}
                      onChange={(event) => updateNewTask(stage.id, { description: event.target.value })}
                    />
                  </label>
                  <div className="form-actions">
                    <button type="submit" className="btn-link" disabled={busy}>
                      Add Task
                    </button>
                  </div>
                </form>
              </div>
            </details>
          )
        })}
      </article>
    </section>
  )
}

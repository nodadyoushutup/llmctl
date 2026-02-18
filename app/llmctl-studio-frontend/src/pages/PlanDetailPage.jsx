import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import ArtifactHistoryTable from '../components/ArtifactHistoryTable'
import PersistedDetails from '../components/PersistedDetails'
import { HttpError } from '../lib/httpClient'
import {
  createPlanStage,
  createPlanTask,
  deletePlan,
  deletePlanStage,
  deletePlanTask,
  getPlan,
  getPlanArtifacts,
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

function toDateTimeLocal(value) {
  const normalized = String(value || '').trim()
  if (!normalized || normalized === '-') {
    return ''
  }
  const withT = normalized.includes(' ') ? normalized.replace(' ', 'T') : normalized
  return withT.length >= 16 ? withT.slice(0, 16) : withT
}

function stopSummaryAction(event) {
  event.preventDefault()
  event.stopPropagation()
}

export default function PlanDetailPage() {
  const navigate = useNavigate()
  const { planId } = useParams()
  const parsedPlanId = useMemo(() => parseId(planId), [planId])

  const [state, setState] = useState({ loading: true, payload: null, artifactsPayload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [openPanels, setOpenPanels] = useState({})
  const [newStage, setNewStage] = useState({ name: '', description: '', completedAt: '' })
  const [stageEditById, setStageEditById] = useState({})
  const [newTaskByStageId, setNewTaskByStageId] = useState({})
  const [taskEditById, setTaskEditById] = useState({})

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!parsedPlanId) {
      setState({ loading: false, payload: null, artifactsPayload: null, error: 'Invalid plan id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getPlan(parsedPlanId)
      let artifactsPayload = { items: [] }
      try {
        artifactsPayload = await getPlanArtifacts(parsedPlanId, { limit: 25 })
      } catch {
        artifactsPayload = { items: [] }
      }
      setState({ loading: false, payload, artifactsPayload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        artifactsPayload: silent ? current.artifactsPayload : null,
        error: errorMessage(error, 'Failed to load plan detail.'),
      }))
    }
  }, [parsedPlanId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const artifactsPayload = state.artifactsPayload && typeof state.artifactsPayload === 'object'
    ? state.artifactsPayload
    : null
  const plan = payload && payload.plan && typeof payload.plan === 'object' ? payload.plan : null
  const artifacts = artifactsPayload && Array.isArray(artifactsPayload.items) ? artifactsPayload.items : []
  const stages = plan && Array.isArray(plan.stages) ? plan.stages : []
  const summary = payload && payload.summary && typeof payload.summary === 'object' ? payload.summary : null

  const stageCount = Number.isInteger(summary?.stage_count) ? summary.stage_count : stages.length
  const taskCount = Number.isInteger(summary?.task_count)
    ? summary.task_count
    : stages.reduce((count, stage) => count + (Array.isArray(stage.tasks) ? stage.tasks.length : 0), 0)

  function togglePanel(panelId) {
    setOpenPanels((current) => ({
      ...current,
      [panelId]: !current[panelId],
    }))
  }

  function getStageEditDraft(stage) {
    return stageEditById[stage.id] || {
      name: String(stage.name || ''),
      description: String(stage.description || ''),
      completedAt: toDateTimeLocal(stage.completed_at),
    }
  }

  function updateStageEditDraft(stage, patch) {
    setStageEditById((current) => ({
      ...current,
      [stage.id]: {
        ...(current[stage.id] || {
          name: String(stage.name || ''),
          description: String(stage.description || ''),
          completedAt: toDateTimeLocal(stage.completed_at),
        }),
        ...patch,
      },
    }))
  }

  function getTaskEditDraft(task) {
    return taskEditById[task.id] || {
      name: String(task.name || ''),
      description: String(task.description || ''),
      completedAt: toDateTimeLocal(task.completed_at),
    }
  }

  function updateTaskEditDraft(task, patch) {
    setTaskEditById((current) => ({
      ...current,
      [task.id]: {
        ...(current[task.id] || {
          name: String(task.name || ''),
          description: String(task.description || ''),
          completedAt: toDateTimeLocal(task.completed_at),
        }),
        ...patch,
      },
    }))
  }

  function getNewTaskDraft(stageId) {
    return newTaskByStageId[stageId] || { name: '', description: '', completedAt: '' }
  }

  function updateNewTaskDraft(stageId, patch) {
    setNewTaskByStageId((current) => ({
      ...current,
      [stageId]: {
        ...(current[stageId] || { name: '', description: '', completedAt: '' }),
        ...patch,
      },
    }))
  }

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
      setOpenPanels((current) => ({ ...current, 'add-stage-panel': false }))
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to add stage.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleUpdateStage(event, stage) {
    event.preventDefault()
    if (!plan || !stage) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updatePlanStage(plan.id, stage.id, getStageEditDraft(stage))
      setOpenPanels((current) => ({ ...current, [`stage-edit-${stage.id}`]: false }))
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

  async function handleCreateTask(event, stageId) {
    event.preventDefault()
    if (!plan) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await createPlanTask(plan.id, stageId, getNewTaskDraft(stageId))
      updateNewTaskDraft(stageId, { name: '', description: '', completedAt: '' })
      setOpenPanels((current) => ({ ...current, [`stage-add-task-${stageId}`]: false }))
      await refresh({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to add task.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleUpdateTask(event, stageId, task) {
    event.preventDefault()
    if (!plan || !task) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await updatePlanTask(plan.id, stageId, task.id, getTaskEditDraft(task))
      setOpenPanels((current) => ({ ...current, [`task-edit-${task.id}`]: false }))
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
        <div className="title-row" style={{ marginBottom: '16px' }}>
          <Link to="/plans" className="btn btn-secondary">
            <i className="fa-solid fa-arrow-left" />
            back to plans
          </Link>
          {plan ? (
            <div className="table-actions">
              <Link
                to={`/plans/${plan.id}/edit`}
                className="icon-button"
                aria-label="Edit plan"
                title="Edit plan"
              >
                <ActionIcon name="edit" />
              </Link>
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
            </div>
          ) : null}
        </div>

        {state.loading ? <p>Loading plan...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}

        {plan ? (
          <>
            <div className="card-header">
              <div>
                <p className="eyebrow">plan {plan.id}</p>
                <h2 className="section-title">{plan.name}</h2>
              </div>
            </div>
            <dl className="meta-list meta-list-compact" style={{ marginTop: '20px' }}>
              <div className="meta-span">
                <dt>Description</dt>
                <dd>{plan.description || '-'}</dd>
              </div>
              <div>
                <dt>Completed</dt>
                <dd>{plan.completed_at || '-'}</dd>
              </div>
              <div>
                <dt>Stages</dt>
                <dd>{stageCount}</dd>
              </div>
              <div>
                <dt>Tasks</dt>
                <dd>{taskCount}</dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{plan.created_at || '-'}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{plan.updated_at || '-'}</dd>
              </div>
            </dl>

            <div className="subcard" style={{ marginTop: '20px' }}>
              <p className="eyebrow">artifact history</p>
              <ArtifactHistoryTable
                artifacts={artifacts}
                emptyMessage="No artifact history yet for this plan."
                hrefForArtifact={(artifact) => `/plans/${plan.id}/artifacts/${artifact.id}`}
              />
            </div>
          </>
        ) : null}
      </article>

      <article className="card">
        <div className="card-header">
          <h2 className="section-title">Plan Outline</h2>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => togglePanel('add-stage-panel')}
          >
            <i className="fa-solid fa-plus" />
            add stage
          </button>
        </div>

        <p className="muted" style={{ marginTop: '12px' }}>
          Expand each stage to browse subtasks, notes, and update progress.
        </p>

        {state.error ? <p className="error-text" style={{ marginTop: '12px' }}>{state.error}</p> : null}

        {stages.length > 0 ? (
          <div className="stack" style={{ marginTop: '20px' }}>
            {stages.map((stage, index) => {
              const tasks = Array.isArray(stage.tasks) ? stage.tasks : []
              const stageEditDraft = getStageEditDraft(stage)
              const newTaskDraft = getNewTaskDraft(stage.id)
              const stageTaskPanelId = `stage-add-task-${stage.id}`
              const stageEditPanelId = `stage-edit-${stage.id}`

              return (
                <PersistedDetails
                  key={stage.id}
                  className={`subcard plan-stage${stage.completed_at ? ' is-complete' : ''}`}
                  storageKey={`plan:${parsedPlanId || 'unknown'}:stage:${stage.id}`}
                  defaultOpen={index === 0}
                >
                  <summary className="plan-stage-summary">
                    <div>
                      <p className="eyebrow">stage {index + 1}</p>
                      <p className="plan-node-title">{stage.name}</p>
                    </div>
                    <div className="row" style={{ gap: '10px' }}>
                      <span className="chip">{tasks.length} task{tasks.length === 1 ? '' : 's'}</span>
                      <span className={`plan-completed-meta${stage.completed_at ? ' is-complete' : ''}`}>
                        completed: {stage.completed_at || '-'}
                      </span>
                      <div className="plan-stage-actions">
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Add task"
                          title="Add task"
                          onClick={(event) => {
                            stopSummaryAction(event)
                            togglePanel(stageTaskPanelId)
                          }}
                        >
                          <ActionIcon name="plus" />
                        </button>
                        <button
                          type="button"
                          className="icon-button"
                          aria-label="Edit stage"
                          title="Edit stage"
                          onClick={(event) => {
                            stopSummaryAction(event)
                            updateStageEditDraft(stage, {})
                            togglePanel(stageEditPanelId)
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
                            stopSummaryAction(event)
                            handleDeleteStage(stage.id)
                          }}
                        >
                          <ActionIcon name="trash" />
                        </button>
                      </div>
                    </div>
                  </summary>

                  {stage.description ? (
                    <p className="muted" style={{ marginTop: '12px', whiteSpace: 'pre-wrap' }}>
                      {stage.description}
                    </p>
                  ) : null}

                  <div className="plan-tree">
                    {tasks.length > 0 ? (
                      tasks.map((task) => {
                        const taskEditPanelId = `task-edit-${task.id}`
                        const taskEditDraft = getTaskEditDraft(task)

                        return (
                          <PersistedDetails
                            key={task.id}
                            className={`plan-task${task.completed_at ? ' is-complete' : ''}`}
                            storageKey={`plan:${parsedPlanId || 'unknown'}:task:${task.id}`}
                          >
                            <summary className="plan-task-summary">
                              <span className="plan-node-title">{task.name}</span>
                              <div className="row" style={{ gap: '10px' }}>
                                <span className={`plan-completed-meta${task.completed_at ? ' is-complete' : ''}`}>
                                  completed: {task.completed_at || '-'}
                                </span>
                                <div className="plan-task-actions">
                                  <button
                                    type="button"
                                    className="icon-button"
                                    aria-label="Edit task"
                                    title="Edit task"
                                    onClick={(event) => {
                                      stopSummaryAction(event)
                                      updateTaskEditDraft(task, {})
                                      togglePanel(taskEditPanelId)
                                    }}
                                  >
                                    <ActionIcon name="edit" />
                                  </button>
                                  <button
                                    type="button"
                                    className="icon-button icon-button-danger"
                                    aria-label="Delete task"
                                    title="Delete task"
                                    disabled={busy}
                                    onClick={(event) => {
                                      stopSummaryAction(event)
                                      handleDeleteTask(stage.id, task.id)
                                    }}
                                  >
                                    <ActionIcon name="trash" />
                                  </button>
                                </div>
                              </div>
                            </summary>

                            {task.description ? (
                              <p className="muted" style={{ marginTop: '8px', whiteSpace: 'pre-wrap' }}>
                                {task.description}
                              </p>
                            ) : null}

                            <div className={`inline-edit plan-inline-panel${openPanels[taskEditPanelId] ? '' : ' is-hidden'}`}>
                              <form className="form-grid" style={{ marginTop: '10px' }} onSubmit={(event) => handleUpdateTask(event, stage.id, task)}>
                                <label className="field">
                                  <span>task name</span>
                                  <input
                                    type="text"
                                    required
                                    value={taskEditDraft.name}
                                    onChange={(event) => updateTaskEditDraft(task, { name: event.target.value })}
                                  />
                                </label>
                                <label className="field">
                                  <span>completed at (optional)</span>
                                  <input
                                    type="datetime-local"
                                    value={taskEditDraft.completedAt}
                                    onChange={(event) => updateTaskEditDraft(task, { completedAt: event.target.value })}
                                  />
                                </label>
                                <label className="field field-span">
                                  <span>description (optional)</span>
                                  <textarea
                                    value={taskEditDraft.description}
                                    onChange={(event) => updateTaskEditDraft(task, { description: event.target.value })}
                                  />
                                </label>
                                <div className="form-actions">
                                  <button type="submit" className="btn btn-secondary" disabled={busy}>
                                    <i className="fa-solid fa-floppy-disk" />
                                    save task
                                  </button>
                                </div>
                              </form>
                            </div>
                          </PersistedDetails>
                        )
                      })
                    ) : (
                      <p className="muted">No tasks for this stage yet.</p>
                    )}
                  </div>

                  <div className={`inline-edit plan-inline-panel${openPanels[stageTaskPanelId] ? '' : ' is-hidden'}`} style={{ marginTop: '12px' }}>
                    <p className="muted" style={{ fontSize: '12px' }}>add task</p>
                    <form className="form-grid" style={{ marginTop: '10px' }} onSubmit={(event) => handleCreateTask(event, stage.id)}>
                      <label className="field">
                        <span>task name</span>
                        <input
                          type="text"
                          required
                          value={newTaskDraft.name}
                          onChange={(event) => updateNewTaskDraft(stage.id, { name: event.target.value })}
                        />
                      </label>
                      <label className="field">
                        <span>completed at (optional)</span>
                        <input
                          type="datetime-local"
                          value={newTaskDraft.completedAt}
                          onChange={(event) => updateNewTaskDraft(stage.id, { completedAt: event.target.value })}
                        />
                      </label>
                      <label className="field field-span">
                        <span>description (optional)</span>
                        <textarea
                          value={newTaskDraft.description}
                          onChange={(event) => updateNewTaskDraft(stage.id, { description: event.target.value })}
                        />
                      </label>
                      <div className="form-actions">
                        <button type="submit" className="btn btn-secondary" disabled={busy}>
                          <i className="fa-solid fa-plus" />
                          add task
                        </button>
                      </div>
                    </form>
                  </div>

                  <div className={`inline-edit plan-inline-panel${openPanels[stageEditPanelId] ? '' : ' is-hidden'}`} style={{ marginTop: '12px' }}>
                    <p className="muted" style={{ fontSize: '12px' }}>edit stage</p>
                    <form className="form-grid" style={{ marginTop: '10px' }} onSubmit={(event) => handleUpdateStage(event, stage)}>
                      <label className="field">
                        <span>stage name</span>
                        <input
                          type="text"
                          required
                          value={stageEditDraft.name}
                          onChange={(event) => updateStageEditDraft(stage, { name: event.target.value })}
                        />
                      </label>
                      <label className="field">
                        <span>completed at (optional)</span>
                        <input
                          type="datetime-local"
                          value={stageEditDraft.completedAt}
                          onChange={(event) => updateStageEditDraft(stage, { completedAt: event.target.value })}
                        />
                      </label>
                      <label className="field field-span">
                        <span>description (optional)</span>
                        <textarea
                          value={stageEditDraft.description}
                          onChange={(event) => updateStageEditDraft(stage, { description: event.target.value })}
                        />
                      </label>
                      <div className="form-actions">
                        <button type="submit" className="btn btn-secondary" disabled={busy}>
                          <i className="fa-solid fa-floppy-disk" />
                          save stage
                        </button>
                      </div>
                    </form>
                  </div>
                </PersistedDetails>
              )
            })}
          </div>
        ) : (
          <p className="muted" style={{ marginTop: '16px' }}>No stages yet.</p>
        )}

        <div className={`inline-edit plan-inline-panel${openPanels['add-stage-panel'] ? '' : ' is-hidden'}`} style={{ marginTop: '16px' }}>
          <p className="muted" style={{ fontSize: '12px' }}>add stage</p>
          <form className="form-grid" style={{ marginTop: '10px' }} onSubmit={handleCreateStage}>
            <label className="field">
              <span>stage name</span>
              <input
                type="text"
                required
                value={newStage.name}
                onChange={(event) => setNewStage((current) => ({ ...current, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>completed at (optional)</span>
              <input
                type="datetime-local"
                value={newStage.completedAt}
                onChange={(event) => setNewStage((current) => ({ ...current, completedAt: event.target.value }))}
              />
            </label>
            <label className="field field-span">
              <span>description (optional)</span>
              <textarea
                value={newStage.description}
                onChange={(event) => setNewStage((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="btn btn-secondary" disabled={busy}>
                <i className="fa-solid fa-plus" />
                add stage
              </button>
            </div>
          </form>
        </div>
      </article>
    </section>
  )
}

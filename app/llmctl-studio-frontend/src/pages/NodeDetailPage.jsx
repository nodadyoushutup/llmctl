import { useCallback, useEffect, useMemo, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import PersistedDetails from '../components/PersistedDetails'
import { HttpError } from '../lib/httpClient'
import { cancelNode, deleteNode, getNode, getNodeStatus, removeNodeAttachment } from '../lib/studioApi'

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

function nodeStatusMeta(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running') {
    return { className: 'status-chip status-running', label: 'running' }
  }
  if (normalized === 'queued' || normalized === 'pending' || normalized === 'starting') {
    return { className: 'status-chip status-warning', label: normalized }
  }
  if (normalized === 'succeeded' || normalized === 'completed') {
    return { className: 'status-chip status-success', label: normalized }
  }
  if (normalized === 'failed' || normalized === 'error') {
    return { className: 'status-chip status-failed', label: normalized }
  }
  return { className: 'status-chip status-idle', label: normalized || 'idle' }
}

function stageStatusMeta(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running') {
    return { className: 'status-chip status-warning', label: normalized }
  }
  if (normalized === 'completed' || normalized === 'succeeded') {
    return { className: 'status-chip status-running', label: normalized }
  }
  if (normalized === 'failed' || normalized === 'error') {
    return { className: 'status-chip status-failed', label: normalized }
  }
  return { className: 'status-chip status-idle', label: normalized || 'pending' }
}

function canCancel(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'queued' || normalized === 'running' || normalized === 'pending'
}

function scriptTypeLabel(value) {
  return String(value || '')
    .replaceAll('_', ' ')
    .trim() || '-'
}

function stageEntryKey(stage, index) {
  const key = String(stage?.key || '').trim()
  if (key) {
    return `stage-key-${key}-${index + 1}`
  }
  const label = String(stage?.label || '').trim()
  if (label) {
    return `stage-label-${label}-${index + 1}`
  }
  return `stage-${index + 1}`
}

function stageEntryLabel(stage, index) {
  const label = String(stage?.label || '').trim()
  if (label) {
    return label
  }
  const key = String(stage?.key || '').trim()
  if (key) {
    return key
  }
  return `Stage ${index + 1}`
}

export default function NodeDetailPage() {
  const navigate = useNavigate()
  const { nodeId } = useParams()
  const parsedNodeId = useMemo(() => parseId(nodeId), [nodeId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [busyAttachmentId, setBusyAttachmentId] = useState(null)
  const [expandedStageKey, setExpandedStageKey] = useState('')

  const refreshDetail = useCallback(async ({ silent = false } = {}) => {
    if (!parsedNodeId) {
      setState({ loading: false, payload: null, error: 'Invalid node id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getNode(parsedNodeId)
      setState({ loading: false, payload, error: '' })
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load node detail.'),
      }))
    }
  }, [parsedNodeId])

  const refreshStatus = useCallback(async () => {
    if (!parsedNodeId) {
      return
    }
    try {
      const statusPayload = await getNodeStatus(parsedNodeId)
      setState((current) => {
        if (!current.payload || typeof current.payload !== 'object') {
          return current
        }
        const nextPayload = { ...current.payload }
        const existingTask = nextPayload.task && typeof nextPayload.task === 'object' ? nextPayload.task : {}
        nextPayload.task = {
          ...existingTask,
          status: statusPayload.status,
          run_task_id: statusPayload.run_task_id,
          celery_task_id: statusPayload.celery_task_id,
          current_stage: statusPayload.current_stage || '',
          error: statusPayload.error || '',
          output: statusPayload.output || '',
          started_at: statusPayload.started_at || existingTask.started_at || '',
          finished_at: statusPayload.finished_at || existingTask.finished_at || '',
          created_at: statusPayload.created_at || existingTask.created_at || '',
        }
        if (Array.isArray(statusPayload.stage_entries)) {
          nextPayload.stage_entries = statusPayload.stage_entries
        }
        return { ...current, payload: nextPayload }
      })
    } catch (error) {
      setState((current) => ({
        ...current,
        error: errorMessage(error, current.error || 'Failed to refresh node status.'),
      }))
    }
  }, [parsedNodeId])

  useEffect(() => {
    refreshDetail()
  }, [refreshDetail])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const task = payload && payload.task && typeof payload.task === 'object' ? payload.task : null
  const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
  const template = payload && payload.template && typeof payload.template === 'object' ? payload.template : null
  const stageEntries = useMemo(
    () => (payload && Array.isArray(payload.stage_entries) ? payload.stage_entries : []),
    [payload],
  )
  const scripts = payload && Array.isArray(payload.scripts) ? payload.scripts : []
  const attachments = payload && Array.isArray(payload.attachments) ? payload.attachments : []
  const mcpServers = payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []
  const selectedIntegrationLabels = payload && Array.isArray(payload.selected_integration_labels)
    ? payload.selected_integration_labels
    : []
  const isQuickTask = Boolean(payload?.is_quick_task)
  const active = canCancel(task?.status)
  const status = nodeStatusMeta(task?.status)
  const nodeTitle = task?.id ? `Node ${task.id}` : (parsedNodeId ? `Node ${parsedNodeId}` : 'Node')

  useEffect(() => {
    if (!stageEntries.length) {
      setExpandedStageKey('')
      return
    }
    const keyedEntries = stageEntries.map((stage, index) => ({
      key: stageEntryKey(stage, index),
      stage,
    }))
    setExpandedStageKey((current) => {
      if (current && keyedEntries.some((entry) => entry.key === current)) {
        return current
      }
      const runningEntry = keyedEntries.find((entry) => String(entry.stage?.status || '').toLowerCase() === 'running')
      if (runningEntry) {
        return runningEntry.key
      }
      const currentStage = String(task?.current_stage || '').trim().toLowerCase()
      if (currentStage) {
        const matchedEntry = keyedEntries.find((entry) => {
          const entryKey = String(entry.stage?.key || '').trim().toLowerCase()
          const entryLabel = String(entry.stage?.label || '').trim().toLowerCase()
          return entryKey === currentStage || entryLabel === currentStage
        })
        if (matchedEntry) {
          return matchedEntry.key
        }
      }
      return keyedEntries[0]?.key || ''
    })
  }, [stageEntries, task?.current_stage])

  useEffect(() => {
    if (!active) {
      return
    }
    const intervalId = window.setInterval(() => {
      refreshStatus()
    }, 5000)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [active, refreshStatus])

  async function handleCancel() {
    if (!task) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await cancelNode(task.id)
      await refreshDetail({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to cancel node.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete() {
    if (!task || !window.confirm('Delete this node?')) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      await deleteNode(task.id)
      navigate('/nodes')
    } catch (error) {
      setBusy(false)
      setActionError(errorMessage(error, 'Failed to delete node.'))
    }
  }

  async function handleAttachmentRemove(attachmentId) {
    if (!task || !window.confirm('Remove this attachment?')) {
      return
    }
    setActionError('')
    setBusyAttachmentId(attachmentId)
    try {
      await removeNodeAttachment(task.id, attachmentId)
      await refreshDetail({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to remove attachment.'))
    } finally {
      setBusyAttachmentId(null)
    }
  }

  return (
    <section className="node-detail-fixed-page" aria-label="Node detail">
      <div className="node-detail-fixed-layout">
        <article className="card node-detail-panel node-detail-panel-main">
          <PanelHeader
            title={nodeTitle}
            className="node-panel-header"
            actions={(
              <>
                <Link to="/nodes" className="icon-button" aria-label="All nodes" title="All nodes">
                  <i className="fa-solid fa-list" />
                </Link>
                <button
                  type="button"
                  className="icon-button icon-button-danger"
                  aria-label="Delete node"
                  title="Delete node"
                  disabled={busy || !task}
                  onClick={handleDelete}
                >
                  <ActionIcon name="trash" />
                </button>
              </>
            )}
          />
          <div className="node-detail-scroll">
            <header className="node-detail-header">
              {state.loading ? <p>Loading node...</p> : null}
              {state.error ? <p className="error-text">{state.error}</p> : null}
              {actionError ? <p className="error-text">{actionError}</p> : null}
            </header>

            <PersistedDetails
              className="subcard node-detail-section node-detail-collapsible"
              storageKey={`node:${parsedNodeId || 'unknown'}:left:prompt`}
              defaultOpen
            >
              <summary className="node-detail-summary">
                <span className="node-detail-summary-title">Prompt</span>
                <i className="fa-solid fa-chevron-down" aria-hidden="true" />
              </summary>
              <div className="node-detail-section-body">
                {payload?.prompt_text ? <pre>{payload.prompt_text}</pre> : <p>No prompt recorded.</p>}
              </div>
            </PersistedDetails>

            <PersistedDetails
              className="subcard node-detail-section node-detail-collapsible"
              storageKey={`node:${parsedNodeId || 'unknown'}:left:output`}
              defaultOpen
            >
              <summary className="node-detail-summary">
                <span className="node-detail-summary-title">Output</span>
                <i className="fa-solid fa-chevron-down" aria-hidden="true" />
              </summary>
              <div className="node-detail-section-body">
                {task?.output ? <pre>{task.output}</pre> : <p>No output yet.</p>}
              </div>
            </PersistedDetails>

            {task ? (
              <PersistedDetails
                className="subcard node-detail-section node-detail-collapsible"
                storageKey={`node:${parsedNodeId || 'unknown'}:left:details`}
                defaultOpen
              >
                <summary className="node-detail-summary">
                  <span className="node-detail-summary-title">Details</span>
                  <span className="node-detail-summary-meta">
                    <span className={status.className}>{status.label}</span>
                    <i className="fa-solid fa-chevron-down" aria-hidden="true" />
                  </span>
                </summary>
                <div className="node-detail-section-body">
                  <div className="table-actions">
                    {active ? (
                      <button
                        type="button"
                        className="icon-button"
                        aria-label="Cancel node"
                        title="Cancel node"
                        disabled={busy}
                        onClick={handleCancel}
                      >
                        <ActionIcon name="stop" />
                      </button>
                    ) : null}
                  </div>
                  <dl className="kv-grid">
                    <div>
                      <dt>Kind</dt>
                      <dd>{task.kind || '-'}</dd>
                    </div>
                    <div>
                      <dt>Agent</dt>
                      <dd>
                        {agent ? <Link to={`/agents/${agent.id}`}>{agent.name}</Link> : (task.agent_id || '-')}
                      </dd>
                    </div>
                    <div>
                      <dt>Task template</dt>
                      <dd>{template?.name || '-'}</dd>
                    </div>
                    <div>
                      <dt>Model</dt>
                      <dd>{task.model_id || '-'}</dd>
                    </div>
                    <div>
                      <dt>Autorun node</dt>
                      <dd>{task.run_task_id || '-'}</dd>
                    </div>
                    <div>
                      <dt>Celery task</dt>
                      <dd>{task.celery_task_id || '-'}</dd>
                    </div>
                    <div>
                      <dt>Current stage</dt>
                      <dd>{task.current_stage || '-'}</dd>
                    </div>
                    <div>
                      <dt>Created</dt>
                      <dd>{task.created_at || '-'}</dd>
                    </div>
                    <div>
                      <dt>Started</dt>
                      <dd>{task.started_at || '-'}</dd>
                    </div>
                    <div>
                      <dt>Finished</dt>
                      <dd>{task.finished_at || '-'}</dd>
                    </div>
                  </dl>
                  {task.error ? <p className="error-text">{task.error}</p> : null}
                  {active ? <p className="toolbar-meta">Realtime updates active. Polling fallback starts only if socket connectivity fails.</p> : null}
                </div>
              </PersistedDetails>
            ) : null}

            <PersistedDetails
              className="subcard node-detail-section node-detail-collapsible"
              storageKey={`node:${parsedNodeId || 'unknown'}:left:context`}
              defaultOpen={false}
            >
              <summary className="node-detail-summary">
                <span className="node-detail-summary-title">Context</span>
                <i className="fa-solid fa-chevron-down" aria-hidden="true" />
              </summary>
              <div className="node-detail-section-body stack-sm">
                <p>
                  Integrations:{' '}
                  {selectedIntegrationLabels.length > 0
                    ? selectedIntegrationLabels.join(', ')
                    : '-'}
                </p>
                <p>
                  MCP servers:{' '}
                  {mcpServers.length > 0
                    ? mcpServers.map((server) => server.name).join(', ')
                    : '-'}
                </p>
                <p>Scripts:</p>
                {scripts.length > 0 ? (
                  <ul>
                    {scripts.map((script) => (
                      <li key={script.id}>
                        {script.file_name} ({scriptTypeLabel(script.script_type)})
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="toolbar-meta">No scripts attached.</p>
                )}
                <p>Attachments:</p>
                {attachments.length > 0 ? (
                  <ul>
                    {attachments.map((attachment) => (
                      <li key={attachment.id} className="node-detail-attachment-row">
                        <span>{attachment.file_name}</span>
                        {isQuickTask ? (
                          <button
                            type="button"
                            className="icon-button icon-button-danger"
                            aria-label={`Remove ${attachment.file_name}`}
                            title="Remove attachment"
                            disabled={busyAttachmentId === attachment.id}
                            onClick={() => handleAttachmentRemove(attachment.id)}
                          >
                            <ActionIcon name="trash" />
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="toolbar-meta">No attachments.</p>
                )}
              </div>
            </PersistedDetails>
          </div>
        </article>

        <article className="card node-detail-panel node-detail-panel-stages">
          <PanelHeader
            title="Stages"
            className="node-panel-header"
            actions={stageEntries.length > 0 ? <p className="panel-header-meta">{stageEntries.length} total</p> : null}
          />
          <div className="node-stage-shell">
            {stageEntries.length === 0 ? <p className="toolbar-meta node-stage-empty">No stage data yet.</p> : null}
            {stageEntries.length > 0 ? (
              <div className="node-stage-list">
                {stageEntries.map((stage, index) => {
                  const stageKey = stageEntryKey(stage, index)
                  const stageStatus = stageStatusMeta(stage.status)
                  const isExpanded = expandedStageKey === stageKey
                  const contentId = `node-stage-content-${index + 1}`
                  return (
                    <section
                      key={stageKey}
                      className={`node-stage-card${isExpanded ? ' is-expanded' : ''}`}
                    >
                      <button
                        type="button"
                        className="node-stage-toggle"
                        aria-expanded={isExpanded}
                        aria-controls={contentId}
                        onClick={() => setExpandedStageKey((current) => (current === stageKey ? '' : stageKey))}
                      >
                        <span className="node-stage-toggle-main">{stageEntryLabel(stage, index)}</span>
                        <span className="node-stage-toggle-meta">
                          <span className={stageStatus.className}>{stageStatus.label}</span>
                          <i className={`fa-solid ${isExpanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} aria-hidden="true" />
                        </span>
                      </button>
                      {isExpanded ? (
                        <div className="node-stage-content" id={contentId}>
                          {stage.logs ? <pre>{stage.logs}</pre> : <p className="toolbar-meta">No logs yet.</p>}
                        </div>
                      ) : null}
                    </section>
                  )
                })}
              </div>
            ) : null}
          </div>
        </article>
      </div>
    </section>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
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

export default function NodeDetailPage() {
  const navigate = useNavigate()
  const { nodeId } = useParams()
  const parsedNodeId = useMemo(() => parseId(nodeId), [nodeId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [busyAttachmentId, setBusyAttachmentId] = useState(null)

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
  const stageEntries = payload && Array.isArray(payload.stage_entries) ? payload.stage_entries : []
  const scripts = payload && Array.isArray(payload.scripts) ? payload.scripts : []
  const attachments = payload && Array.isArray(payload.attachments) ? payload.attachments : []
  const mcpServers = payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []
  const selectedIntegrationLabels = payload && Array.isArray(payload.selected_integration_labels)
    ? payload.selected_integration_labels
    : []
  const isQuickTask = Boolean(payload?.is_quick_task)
  const active = canCancel(task?.status)
  const status = nodeStatusMeta(task?.status)

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
    <section className="stack" aria-label="Node detail">
      <article className="card">
        <div className="title-row">
          <div>
            <h2>{task ? `Node ${task.id}` : 'Node'}</h2>
            <p>{task?.kind || 'Node'} details and realtime execution state.</p>
          </div>
          <div className="table-actions">
            <Link to="/nodes" className="btn-link btn-secondary">All Nodes</Link>
          </div>
        </div>
        {state.loading ? <p>Loading node...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {task ? (
          <div className="stack-sm">
            <div className="table-actions">
              <span className={status.className}>{status.label}</span>
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
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete node"
                title="Delete node"
                disabled={busy}
                onClick={handleDelete}
              >
                <ActionIcon name="trash" />
              </button>
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
        ) : null}
      </article>

      <article className="card">
        <h2>Context</h2>
        <div className="stack-sm">
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
                <li key={attachment.id}>
                  <span>{attachment.file_name}</span>
                  {isQuickTask ? (
                    <button
                      type="button"
                      className="icon-button icon-button-danger"
                      aria-label={`Remove ${attachment.file_name}`}
                      title="Remove attachment"
                      disabled={busyAttachmentId === attachment.id}
                      onClick={() => handleAttachmentRemove(attachment.id)}
                      style={{ marginLeft: '8px' }}
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
      </article>

      <article className="card">
        <h2>Prompt</h2>
        {payload?.prompt_text ? <pre>{payload.prompt_text}</pre> : <p>No prompt recorded.</p>}
      </article>

      <article className="card">
        <h2>Output</h2>
        {task?.output ? <pre>{task.output}</pre> : <p>No output yet.</p>}
      </article>

      <article className="card">
        <h2>Stages</h2>
        {stageEntries.length === 0 ? <p>No stage data yet.</p> : null}
        {stageEntries.length > 0 ? (
          <div className="stack-sm">
            {stageEntries.map((stage) => {
              const stageStatus = stageStatusMeta(stage.status)
              return (
                <details key={stage.key} className="card">
                  <summary className="title-row">
                    <strong>{stage.label}</strong>
                    <span className={stageStatus.className}>{stageStatus.label}</span>
                  </summary>
                  {stage.logs ? <pre>{stage.logs}</pre> : <p>No logs yet.</p>}
                </details>
              )
            })}
          </div>
        ) : null}
      </article>
    </section>
  )
}

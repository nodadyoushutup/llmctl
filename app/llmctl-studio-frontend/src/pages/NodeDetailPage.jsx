import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useFlash, useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { cancelNode, deleteNode, getNode, getNodeStatus, removeNodeAttachment, retryNode } from '../lib/studioApi'

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
  return normalized === 'queued'
    || normalized === 'running'
    || normalized === 'pending'
    || normalized === 'starting'
    || normalized === 'in_progress'
    || normalized === 'in progress'
    || normalized === 'processing'
    || normalized === 'executing'
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

export function nodeHistoryHref(task) {
  const flowchartNodeId = Number.parseInt(String(task?.flowchart_node_id || ''), 10)
  if (Number.isInteger(flowchartNodeId) && flowchartNodeId > 0) {
    return `/nodes?flowchart_node_id=${flowchartNodeId}`
  }
  return '/nodes'
}

export function stageLogEmptyMessage(stage, index) {
  const label = stageEntryLabel(stage, index).trim().toLowerCase()
  if (label === 'rag indexing' || label === 'rag delta indexing') {
    return 'Waiting for indexing logs...'
  }
  return 'No logs yet.'
}

function isStageRunning(stage) {
  return String(stage?.status || '').toLowerCase() === 'running'
}

function isNearBottom(element, threshold = 12) {
  if (!element) {
    return false
  }
  const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight
  return distanceFromBottom <= threshold
}

function scrollElementToBottom(element) {
  if (!element) {
    return
  }
  element.scrollTop = element.scrollHeight
}

export default function NodeDetailPage() {
  const navigate = useNavigate()
  const { nodeId } = useParams()
  const parsedNodeId = useMemo(() => parseId(nodeId), [nodeId])
  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const flash = useFlash()
  const [actionError, setActionError] = useFlashState('error')
  const [busy, setBusy] = useState(false)
  const [busyAttachmentId, setBusyAttachmentId] = useState(null)
  const [expandedStageKey, setExpandedStageKey] = useState('')
  const [expandedLeftSectionKey, setExpandedLeftSectionKey] = useState('output')
  const [leftPanelExpanded, setLeftPanelExpanded] = useState(false)
  const stageLogRefs = useRef(new Map())
  const stageLogPinnedBottomRef = useRef(new Map())

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

  useEffect(() => {
    setBusy(false)
  }, [parsedNodeId])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const task = payload && payload.task && typeof payload.task === 'object' ? payload.task : null
  const agent = payload && payload.agent && typeof payload.agent === 'object' ? payload.agent : null
  const stageEntries = useMemo(
    () => (payload && Array.isArray(payload.stage_entries) ? payload.stage_entries : []),
    [payload],
  )
  const expandedStage = useMemo(() => {
    if (!expandedStageKey) {
      return null
    }
    const entry = stageEntries.find((stage, index) => stageEntryKey(stage, index) === expandedStageKey)
    return entry || null
  }, [expandedStageKey, stageEntries])
  const expandedStageLogs = String(expandedStage?.logs || '')
  const expandedStageRunning = isStageRunning(expandedStage)
  const scripts = payload && Array.isArray(payload.scripts) ? payload.scripts : []
  const attachments = payload && Array.isArray(payload.attachments) ? payload.attachments : []
  const mcpServers = payload && Array.isArray(payload.mcp_servers) ? payload.mcp_servers : []
  const selectedIntegrationLabels = payload && Array.isArray(payload.selected_integration_labels)
    ? payload.selected_integration_labels
    : []
  const isQuickTask = Boolean(payload?.is_quick_task)
  const active = canCancel(task?.status)
  const status = nodeStatusMeta(task?.status)
  const hasLeftHeaderMessage = state.loading || Boolean(state.error) || Boolean(actionError)
  const nodeHistoryLink = nodeHistoryHref(task)
  const detailItems = useMemo(() => {
    if (!task) {
      return []
    }
    return [
      { label: 'Kind', value: task.kind || '-' },
      {
        label: 'Agent',
        value: agent ? <Link to={`/agents/${agent.id}`}>{agent.name}</Link> : (task.agent_id || '-'),
      },
      {
        label: 'Flowchart',
        value: task.flowchart_id
          ? <Link to={`/flowcharts/${task.flowchart_id}`}>{task.flowchart_id}</Link>
          : '-',
      },
      {
        label: 'Flowchart run',
        value: task.flowchart_run_id && task.flowchart_id
          ? <Link to={`/flowcharts/${task.flowchart_id}/history/${task.flowchart_run_id}`}>{task.flowchart_run_id}</Link>
          : (task.flowchart_run_id || '-'),
      },
      { label: 'Flowchart node', value: task.flowchart_node_id || '-' },
      { label: 'Model', value: task.model_id || '-' },
      { label: 'Autorun node', value: task.run_task_id || '-' },
      { label: 'Celery task', value: task.celery_task_id || '-' },
      { label: 'Current stage', value: task.current_stage || '-' },
      { label: 'Created', value: task.created_at || '-' },
      { label: 'Started', value: task.started_at || '-' },
      { label: 'Finished', value: task.finished_at || '-' },
    ]
  }, [agent, task])
  const leftSectionEntries = useMemo(
    () => [
      { key: 'output', label: 'Output' },
      { key: 'prompt', label: 'Prompt' },
      { key: 'details', label: 'Details' },
      { key: 'context', label: 'Context' },
    ],
    [],
  )

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

  const registerStageLogRef = useCallback((stageKey, node) => {
    if (!stageKey) {
      return
    }
    if (node) {
      stageLogRefs.current.set(stageKey, node)
      if (!stageLogPinnedBottomRef.current.has(stageKey)) {
        stageLogPinnedBottomRef.current.set(stageKey, true)
      }
      return
    }
    stageLogRefs.current.delete(stageKey)
    stageLogPinnedBottomRef.current.delete(stageKey)
  }, [])

  const handleStageLogScroll = useCallback((stageKey) => {
    const viewport = stageLogRefs.current.get(stageKey)
    if (!viewport) {
      return
    }
    stageLogPinnedBottomRef.current.set(stageKey, isNearBottom(viewport))
  }, [])

  useEffect(() => {
    if (!expandedStageKey) {
      return
    }
    const animationFrameId = window.requestAnimationFrame(() => {
      const viewport = stageLogRefs.current.get(expandedStageKey)
      if (!viewport) {
        return
      }
      stageLogPinnedBottomRef.current.set(expandedStageKey, true)
      scrollElementToBottom(viewport)
    })
    return () => {
      window.cancelAnimationFrame(animationFrameId)
    }
  }, [expandedStageKey])

  useEffect(() => {
    if (!expandedStageKey || !expandedStageRunning) {
      return
    }
    const viewport = stageLogRefs.current.get(expandedStageKey)
    if (!viewport) {
      return
    }
    if (!stageLogPinnedBottomRef.current.get(expandedStageKey)) {
      return
    }
    const animationFrameId = window.requestAnimationFrame(() => {
      const currentViewport = stageLogRefs.current.get(expandedStageKey)
      if (!currentViewport) {
        return
      }
      scrollElementToBottom(currentViewport)
    })
    return () => {
      window.cancelAnimationFrame(animationFrameId)
    }
  }, [expandedStageKey, expandedStageLogs, expandedStageRunning])

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
      const payload = await cancelNode(task.id)
      if (payload?.already_stopped) {
        flash.info('Node is not running.')
      } else {
        flash.success('Node cancel requested.')
      }
      await refreshDetail({ silent: true })
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to cancel node.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleRetry() {
    if (!task) {
      return
    }
    setActionError('')
    setBusy(true)
    try {
      const payload = await retryNode(task.id)
      const nextTaskId = Number.parseInt(String(payload?.task_id || ''), 10)
      if (!Number.isInteger(nextTaskId) || nextTaskId <= 0) {
        throw new Error('Retry response did not include a new node id.')
      }
      flash.success(`Node ${nextTaskId} queued.`)
      navigate(`/nodes/${nextTaskId}`)
    } catch (error) {
      setActionError(errorMessage(error, 'Failed to retry node.'))
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
      <div className={`node-detail-fixed-layout${leftPanelExpanded ? ' is-left-expanded' : ''}`}>
        <article className="card node-detail-panel node-detail-panel-main">
          <PanelHeader
            title={<span className={status.className}>{status.label}</span>}
            titleClassName="node-panel-status-title"
            className="node-panel-header"
            actions={(
              <>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={leftPanelExpanded ? 'Collapse left panel' : 'Expand left panel'}
                  title={leftPanelExpanded ? 'Collapse left panel' : 'Expand left panel'}
                  onClick={() => setLeftPanelExpanded((current) => !current)}
                >
                  <i className={`fa-solid ${leftPanelExpanded ? 'fa-compress' : 'fa-expand'}`} />
                </button>
                <Link to={nodeHistoryLink} className="icon-button" aria-label="Node history" title="Node history">
                  <i className="fa-solid fa-list" />
                </Link>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Cancel node"
                  title="Cancel node"
                  disabled={busy || !task || !active}
                  onClick={handleCancel}
                >
                  <ActionIcon name="stop" />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Retry node"
                  title="Retry node"
                  disabled={busy || !task}
                  onClick={handleRetry}
                >
                  <i className="fa-solid fa-rotate-right" />
                </button>
                <button
                  type="button"
                  className="icon-button icon-button-danger"
                  aria-label="Delete node"
                  title="Delete node"
                  disabled={busy || !task}
                  onClick={handleDelete}
                >
                  <i className="fa-solid fa-trash" />
                </button>
              </>
            )}
          />
          <div className="node-detail-scroll">
            {hasLeftHeaderMessage ? (
              <header className="node-detail-header">
                {state.loading ? <p>Loading node...</p> : null}
                {state.error ? <p className="error-text">{state.error}</p> : null}
                {actionError ? <p className="error-text">{actionError}</p> : null}
              </header>
            ) : null}

            <div className="node-left-shell">
              <div className="node-left-list">
                {leftSectionEntries.map((section) => {
                  const isExpanded = expandedLeftSectionKey === section.key
                  const contentId = `node-left-content-${section.key}`
                  return (
                    <section
                      key={section.key}
                      className={`node-left-card${isExpanded ? ' is-expanded' : ''}`}
                    >
                      <button
                        type="button"
                        className="node-left-toggle"
                        aria-expanded={isExpanded}
                        aria-controls={contentId}
                        onClick={() => setExpandedLeftSectionKey((current) => (current === section.key ? '' : section.key))}
                      >
                        <span className="node-left-toggle-main">{section.label}</span>
                        <span className="node-left-toggle-meta">
                          <span className="status-chip node-left-toggle-chip-ghost" aria-hidden="true">completed</span>
                          <i className={`fa-solid ${isExpanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} aria-hidden="true" />
                        </span>
                      </button>
                      {isExpanded ? (
                        <div className="node-left-content" id={contentId}>
                          {section.key === 'prompt'
                            ? (payload?.prompt_text ? <pre className="node-left-code-block">{payload.prompt_text}</pre> : <p className="toolbar-meta node-left-empty">No prompt recorded.</p>)
                            : null}
                          {section.key === 'output'
                            ? (task?.output ? <pre className="node-left-code-block">{task.output}</pre> : <p className="toolbar-meta node-left-empty">No output yet.</p>)
                            : null}
                          {section.key === 'details'
                            ? (
                              task ? (
                                <div className="node-left-scroll-panel">
                                  <dl className="node-details-list">
                                    {detailItems.map((item) => (
                                      <div key={item.label} className="node-details-item">
                                        <dt>{item.label}</dt>
                                        <dd>{item.value}</dd>
                                      </div>
                                    ))}
                                  </dl>
                                </div>
                              ) : (
                                <p className="toolbar-meta node-left-empty">No details yet.</p>
                              )
                            )
                            : null}
                          {section.key === 'context'
                            ? (
                              <div className="node-left-scroll-panel stack-sm">
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
                            )
                            : null}
                        </div>
                      ) : null}
                    </section>
                  )
                })}
              </div>
            </div>
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
                          {stage.logs ? (
                            <pre
                              className="node-stage-log-block"
                              ref={(node) => registerStageLogRef(stageKey, node)}
                              onScroll={() => handleStageLogScroll(stageKey)}
                            >
                              {stage.logs}
                            </pre>
                          ) : (
                            <p className="toolbar-meta node-stage-log-empty">{stageLogEmptyMessage(stage, index)}</p>
                          )}
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

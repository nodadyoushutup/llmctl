import { isValidElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useFlash, useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import PanelHeader from '../components/PanelHeader'
import { HttpError } from '../lib/httpClient'
import { cancelNode, deleteNode, getNode, getNodeStatus, retryNode } from '../lib/studioApi'
import {
  buildNodeLeftPanelSections,
  connectorOutputRows,
  inputConnectorSummaryRows,
  NODE_LEFT_DEFAULT_SECTION_KEY,
  nodeHistoryHref,
  resolveNodeLeftPanelPayload,
  stageLogEmptyMessage,
} from './NodeDetailPage.helpers'

function parseId(value) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function asRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {}
  }
  return value
}

function asRecordList(value) {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item) => item && typeof item === 'object' && !Array.isArray(item))
}

function formatPrettyJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '{}'
  }
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

function asStringList(value) {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => String(item || '').trim())
    .filter((item) => item.length > 0)
}

function titleCaseLabel(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) {
    return '-'
  }
  if (normalized === 'context_only') {
    return 'context only'
  }
  return normalized.replaceAll('_', ' ')
}

function renderMetadataCellValue(value) {
  if (isValidElement(value)) {
    return value
  }
  if (value == null || value === '') {
    return '-'
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join('\n') : '-'
  }
  if (typeof value === 'object') {
    return <pre className="node-context-code-block">{formatPrettyJson(value)}</pre>
  }
  return String(value)
}

function MetadataRowsTable({ rows }) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return null
  }
  return (
    <div className="node-output-summary-table-wrap">
      <table className="node-output-summary-table">
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.label || 'row'}-${index + 1}`}>
              <th scope="row">{row.label}</th>
              <td>{renderMetadataCellValue(row.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function sectionHasContent(section) {
  if (!section || typeof section !== 'object') {
    return false
  }
  const value = section.value && typeof section.value === 'object' && !Array.isArray(section.value)
    ? section.value
    : {}
  switch (section.key) {
    case 'input':
      {
        const triggerCount = Number.parseInt(String(value.trigger_source_count || ''), 10)
        const contextOnlyCount = Number.parseInt(String(value.context_only_source_count || ''), 10)
        const source = String(value.source || '').trim().toLowerCase()
        return asRecordList(value.connector_blocks).length > 0
          || Object.keys(asRecord(value.resolved_input_context)).length > 0
          || (Number.isInteger(triggerCount) && triggerCount > 0)
          || (Number.isInteger(contextOnlyCount) && contextOnlyCount > 0)
          || (source.length > 0 && source !== 'none')
      }
    case 'results':
      return String(value.primary_text || '').trim().length > 0
        || asRecordList(value.summary_rows).length > 0
        || asStringList(value.action_results).length > 0
    case 'prompt':
      return String(value.provided_prompt_text || '').trim().length > 0
        || Object.keys(asRecord(value.provided_prompt_fields)).length > 0
        || Boolean(value.no_inferred_prompt_in_deterministic_mode)
    case 'agent':
      return String(value.name || '').trim().length > 0 || Number.isInteger(value.id)
    case 'mcp_servers':
      return asRecordList(value.items).length > 0
    case 'collections':
      return asRecordList(value.items).length > 0
    case 'raw_json':
      return String(value.formatted_output || '').trim().length > 0
    case 'details':
      return asRecordList(value.rows).length > 0
    default:
      return false
  }
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
  const [expandedStageKey, setExpandedStageKey] = useState('')
  const [expandedLeftSectionKey, setExpandedLeftSectionKey] = useState(NODE_LEFT_DEFAULT_SECTION_KEY)
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
  const leftPanelPayload = useMemo(() => resolveNodeLeftPanelPayload(payload), [payload])
  const leftSectionEntries = useMemo(
    () => buildNodeLeftPanelSections(leftPanelPayload),
    [leftPanelPayload],
  )
  const active = canCancel(task?.status)
  const status = nodeStatusMeta(task?.status)
  const hasLeftHeaderMessage = state.loading || Boolean(state.error) || Boolean(actionError)
  const nodeHistoryLink = nodeHistoryHref(task)

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
    if (!leftSectionEntries.some((section) => section.key === expandedLeftSectionKey)) {
      setExpandedLeftSectionKey(NODE_LEFT_DEFAULT_SECTION_KEY)
    }
  }, [expandedLeftSectionKey, leftSectionEntries])

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
                  const sectionValue = asRecord(section.value)
                  const sectionEmpty = section.emptyMessage || 'No data.'
                  const hasContent = sectionHasContent(section)
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
                        onClick={() => setExpandedLeftSectionKey(section.key)}
                      >
                        <span className="node-left-toggle-main">{section.label}</span>
                        <span className="node-left-toggle-meta">
                          <span className="status-chip node-left-toggle-chip-ghost" aria-hidden="true">completed</span>
                          <i className={`fa-solid ${isExpanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} aria-hidden="true" />
                        </span>
                      </button>
                      {isExpanded ? (
                        <div className="node-left-content" id={contentId}>
                          {section.key === 'input' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              <MetadataRowsTable rows={inputConnectorSummaryRows(sectionValue)} />
                              {asRecordList(sectionValue.connector_blocks).length > 0 ? (
                                <div className="stack-sm">
                                  {asRecordList(sectionValue.connector_blocks).map((block, index) => {
                                    const blockOutput = block.output_state
                                    const outputRows = connectorOutputRows(blockOutput)
                                    return (
                                      <details key={String(block.id || `connector-${index + 1}`)} className="node-input-connector-block">
                                        <summary className="node-input-connector-summary">
                                          {String(block.label || `Connector ${index + 1}`)}
                                        </summary>
                                        <div className="node-input-connector-content stack-sm">
                                          <MetadataRowsTable
                                            rows={[
                                              { label: 'Type', value: titleCaseLabel(block.classification) },
                                              { label: 'Source node id', value: block.source_node_id ?? '-' },
                                              { label: 'Source node type', value: String(block.source_node_type || '-') },
                                              { label: 'Connector key', value: String(block.condition_key || '-') },
                                              { label: 'Edge mode', value: String(block.edge_mode || '-') },
                                            ]}
                                          />
                                          {outputRows.length > 0 ? (
                                            <>
                                              <p className="toolbar-meta">Connector output state</p>
                                              <MetadataRowsTable
                                                rows={outputRows.map((row) => ({
                                                  label: row.label,
                                                  value: row.value,
                                                }))}
                                              />
                                            </>
                                          ) : null}
                                          <p className="toolbar-meta">Connector output raw JSON</p>
                                          <pre className="node-context-code-block">{formatPrettyJson(blockOutput)}</pre>
                                        </div>
                                      </details>
                                    )
                                  })}
                                </div>
                              ) : null}
                              {Object.keys(asRecord(sectionValue.resolved_input_context)).length > 0 ? (
                                <>
                                  <p className="toolbar-meta">Resolved input context</p>
                                  <pre className="node-context-code-block">{formatPrettyJson(sectionValue.resolved_input_context)}</pre>
                                </>
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'results' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {String(sectionValue.primary_text || '').trim() ? (
                                <p className="node-left-results-primary">{String(sectionValue.primary_text || '').trim()}</p>
                              ) : null}
                              <MetadataRowsTable
                                rows={asRecordList(sectionValue.summary_rows).map((row) => ({
                                  label: String(row.label || '-'),
                                  value: row.value ?? '-',
                                }))}
                              />
                              {asStringList(sectionValue.action_results).length > 0 ? (
                                <div className="node-left-results-actions">
                                  <p className="toolbar-meta">Action results</p>
                                  <ul>
                                    {asStringList(sectionValue.action_results).map((result, index) => (
                                      <li key={`${result}-${index + 1}`}>{result}</li>
                                    ))}
                                  </ul>
                                </div>
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'prompt' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {String(sectionValue.notice || '').trim() ? (
                                <p className="toolbar-meta node-left-note">{String(sectionValue.notice || '').trim()}</p>
                              ) : null}
                              {String(sectionValue.provided_prompt_text || '').trim() ? (
                                <>
                                  <p className="toolbar-meta">Provided prompt text</p>
                                  <pre className="node-left-code-block">{String(sectionValue.provided_prompt_text || '')}</pre>
                                </>
                              ) : null}
                              {Object.keys(asRecord(sectionValue.provided_prompt_fields)).length > 0 ? (
                                <>
                                  <p className="toolbar-meta">Provided prompt fields</p>
                                  <pre className="node-context-code-block">{formatPrettyJson(sectionValue.provided_prompt_fields)}</pre>
                                </>
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'agent' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {hasContent ? (
                                <MetadataRowsTable
                                  rows={[
                                    {
                                      label: 'Agent',
                                      value: String(sectionValue.link_href || '').trim()
                                        ? <Link to={String(sectionValue.link_href)}>{String(sectionValue.name || sectionValue.id || '-')}</Link>
                                        : String(sectionValue.name || sectionValue.id || '-'),
                                    },
                                  ]}
                                />
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'mcp_servers' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {hasContent ? (
                                <MetadataRowsTable
                                  rows={asRecordList(sectionValue.items).map((item, index) => ({
                                    label: `MCP ${index + 1}`,
                                    value: String(item.server_key || '').trim()
                                      ? `${String(item.name || '-')}\n${String(item.server_key)}`
                                      : String(item.name || '-'),
                                  }))}
                                />
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'collections' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {hasContent ? (
                                <MetadataRowsTable
                                  rows={asRecordList(sectionValue.items).map((item, index) => ({
                                    label: `Collection ${index + 1}`,
                                    value: String(item.name || item.id_or_key || '-'),
                                  }))}
                                />
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}

                          {section.key === 'raw_json' ? (
                            String(sectionValue.formatted_output || '').trim()
                              ? <pre className="node-left-code-block">{String(sectionValue.formatted_output || '')}</pre>
                              : <p className="toolbar-meta node-left-empty">{sectionEmpty}</p>
                          ) : null}

                          {section.key === 'details' ? (
                            <div className="node-left-scroll-panel stack-sm">
                              {hasContent ? (
                                <MetadataRowsTable
                                  rows={asRecordList(sectionValue.rows).map((row) => ({
                                    label: String(row.label || '-'),
                                    value: row.value ?? '-',
                                  }))}
                                />
                              ) : null}
                              {!hasContent ? <p className="toolbar-meta node-left-empty">{sectionEmpty}</p> : null}
                            </div>
                          ) : null}
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

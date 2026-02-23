import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useFlashState } from '../lib/flashMessages'
import { Link, useNavigate, useParams } from 'react-router-dom'
import FlowchartWorkspaceEditor from '../components/FlowchartWorkspaceEditor'
import { HttpError } from '../lib/httpClient'
import {
  cancelFlowchartRun,
  createQuickNode,
  deleteFlowchart,
  getFlowchartGraph,
  getFlowchartEdit,
  getFlowchartHistory,
  getFlowchartRuntime,
  runFlowchart,
  updateFlowchartGraph,
  validateFlowchart,
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

function isRunActive(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'queued' || normalized === 'running' || normalized === 'stopping'
}

function runtimeMetaTone(status) {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'running') {
    return 'is-running'
  }
  if (normalized === 'queued' || normalized === 'stopping') {
    return 'is-waiting'
  }
  return 'is-idle'
}

function hasTaskPrompt(config) {
  if (!config || typeof config !== 'object') {
    return false
  }
  const prompt = config.task_prompt
  return typeof prompt === 'string' && Boolean(prompt.trim())
}

function flowchartWorkspaceNodeId(node) {
  return parseId(node?.persistedId) || parseId(node?.id)
}

function flowchartWorkspaceNodeLabel(node) {
  const title = String(node?.title || '').trim()
  if (title) {
    return title
  }
  const nodeType = String(node?.node_type || '').trim().toLowerCase()
  return nodeType ? `${nodeType} node` : 'node'
}

function quickNodePromptFromFlowchartNode(node) {
  if (!node || typeof node !== 'object') {
    return ''
  }
  const config = node.config && typeof node.config === 'object' ? node.config : {}
  const candidates = [
    config.task_prompt,
    config.question_prompt,
    config.additive_prompt,
    node.title,
  ]
  for (const value of candidates) {
    const text = String(value || '').trim()
    if (text) {
      return text
    }
  }
  return ''
}

function validateDraftNodes(nodes) {
  if (!Array.isArray(nodes)) {
    return []
  }
  const errors = []
  nodes.forEach((node, index) => {
    const nodeType = String(node?.node_type || '').trim().toLowerCase()
    if (nodeType === 'task' && !hasTaskPrompt(node?.config)) {
      const title = String(node?.title || '').trim()
      const label = title ? `"${title}"` : `#${index + 1}`
      errors.push(`Task node ${label} needs a task prompt before saving or running.`)
    }
  })
  return errors
}

const DEFAULT_FLOWCHART_NODE_TYPES = ['start', 'end', 'flowchart', 'task', 'plan', 'milestone', 'memory', 'decision', 'rag']

export default function FlowchartDetailPage() {
  const navigate = useNavigate()
  const { flowchartId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [, setActionError] = useFlashState('error')
  const [, setActionInfo] = useFlashState('success')
  const [busyAction, setBusyAction] = useState('')
  const [editorGraph, setEditorGraph] = useState({ nodes: [], edges: [] })
  const [editorRevision, setEditorRevision] = useState(0)
  const [validationState, setValidationState] = useState(null)
  const [runtimeWarning, setRuntimeWarning] = useState('')
  const [catalogWarning, setCatalogWarning] = useState('')
  const [isMetaExpanded, setIsMetaExpanded] = useState(false)
  const workspaceEditorRef = useRef(null)

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!parsedFlowchartId) {
      setState({ loading: false, payload: null, error: 'Invalid flowchart id.' })
      return
    }
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const [graphResult, historyResult, editResult, runtimeResult] = await Promise.allSettled([
        getFlowchartGraph(parsedFlowchartId),
        getFlowchartHistory(parsedFlowchartId),
        getFlowchartEdit(parsedFlowchartId),
        getFlowchartRuntime(parsedFlowchartId),
      ])

      if (graphResult.status !== 'fulfilled') {
        throw graphResult.reason
      }
      if (historyResult.status !== 'fulfilled') {
        throw historyResult.reason
      }

      const graphPayload = graphResult.value
      const historyPayload = historyResult.value
      const detail = {
        flowchart: historyPayload?.flowchart || null,
        graph: {
          nodes: Array.isArray(graphPayload?.nodes) ? graphPayload.nodes : [],
          edges: Array.isArray(graphPayload?.edges) ? graphPayload.edges : [],
        },
        runs: Array.isArray(historyPayload?.runs) ? historyPayload.runs : [],
        validation: graphPayload?.validation && typeof graphPayload.validation === 'object'
          ? graphPayload.validation
          : { valid: true, errors: [] },
      }
      const edit = editResult.status === 'fulfilled'
        ? editResult.value
        : { catalog: null, node_types: DEFAULT_FLOWCHART_NODE_TYPES }
      const runtime = runtimeResult.status === 'fulfilled'
        ? runtimeResult.value
        : { active_run_id: null, active_run_status: null, running_node_ids: [] }

      setState({
        loading: false,
        payload: { detail, edit, runtime },
        error: '',
      })
      if (runtimeResult.status !== 'fulfilled') {
        setRuntimeWarning(errorMessage(runtimeResult.reason, 'Runtime status is temporarily unavailable.'))
      } else {
        setRuntimeWarning('')
      }
      if (editResult.status !== 'fulfilled') {
        setCatalogWarning(errorMessage(editResult.reason, 'Catalog and node utility metadata are temporarily unavailable.'))
      } else {
        setCatalogWarning('')
      }
      if (!silent) {
        const graph = detail?.graph && typeof detail.graph === 'object' ? detail.graph : { nodes: [], edges: [] }
        const nextNodes = Array.isArray(graph.nodes) ? graph.nodes : []
        const nextEdges = Array.isArray(graph.edges) ? graph.edges : []
        setEditorGraph({ nodes: nextNodes, edges: nextEdges })
        setEditorRevision((current) => current + 1)
        setValidationState(detail?.validation && typeof detail.validation === 'object' ? detail.validation : null)
      }
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load flowchart.'),
      }))
      setRuntimeWarning('')
      setCatalogWarning('')
    }
  }, [parsedFlowchartId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const payload = state.payload && typeof state.payload === 'object' ? state.payload : null
  const detail = payload?.detail && typeof payload.detail === 'object' ? payload.detail : null
  const edit = payload?.edit && typeof payload.edit === 'object' ? payload.edit : null
  const runtime = payload?.runtime && typeof payload.runtime === 'object' ? payload.runtime : null

  const flowchart = detail?.flowchart && typeof detail.flowchart === 'object' ? detail.flowchart : null
  const nodes = useMemo(() => (Array.isArray(editorGraph?.nodes) ? editorGraph.nodes : []), [editorGraph])
  const edges = useMemo(() => (Array.isArray(editorGraph?.edges) ? editorGraph.edges : []), [editorGraph])
  const draftValidationErrors = useMemo(() => validateDraftNodes(nodes), [nodes])
  const catalog = edit?.catalog && typeof edit.catalog === 'object' ? edit.catalog : null
  const nodeTypeOptions = useMemo(() => {
    const raw = edit?.node_types
    if (!Array.isArray(raw) || raw.length === 0) {
      return DEFAULT_FLOWCHART_NODE_TYPES
    }
    return raw
  }, [edit])
  const runtimeStatus = runtime?.active_run_status || ''
  const activeRunId = runtime?.active_run_id || null
  const activeRun = isRunActive(runtimeStatus)
  const runningNodeIds = Array.isArray(runtime?.running_node_ids) ? runtime.running_node_ids : []

  useEffect(() => {
    if (!activeRun || !parsedFlowchartId) {
      return
    }
    const intervalId = window.setInterval(async () => {
      try {
        const runtimePayload = await getFlowchartRuntime(parsedFlowchartId)
        setState((current) => {
          if (!current.payload || typeof current.payload !== 'object') {
            return current
          }
          return {
            ...current,
            payload: {
              ...current.payload,
              runtime: runtimePayload,
            },
          }
        })
      } catch {
        // ignore transient polling errors
      }
    }, 5000)
    return () => {
      window.clearInterval(intervalId)
    }
  }, [activeRun, parsedFlowchartId])

  async function withAction(actionKey, fn) {
    setActionError('')
    setActionInfo('')
    setBusyAction(actionKey)
    try {
      await fn()
    } catch (error) {
      setActionError(errorMessage(error, 'Flowchart action failed.'))
    } finally {
      setBusyAction('')
    }
  }

  function isBusy(actionKey) {
    return busyAction === actionKey
  }

  async function handleDelete() {
    if (!parsedFlowchartId || !window.confirm('Delete this flowchart?')) {
      return
    }
    await withAction('delete', async () => {
      await deleteFlowchart(parsedFlowchartId)
      navigate('/flowcharts')
    })
  }

  async function handleRun() {
    if (!parsedFlowchartId) {
      return
    }
    await withAction('run', async () => {
      const payload = await runFlowchart(parsedFlowchartId)
      const runId = payload?.flowchart_run?.id
      setActionInfo(runId ? `Flowchart run queued (run ${runId}).` : 'Flowchart run queued.')
      await refresh({ silent: true })
    })
  }

  async function handleRunFromNode(node) {
    if (!parsedFlowchartId) {
      return
    }
    const startNodeId = flowchartWorkspaceNodeId(node)
    if (!startNodeId) {
      setActionError('Save graph before running from this node.')
      return
    }
    const nodeLabel = flowchartWorkspaceNodeLabel(node)
    await withAction('run-from-node', async () => {
      const payload = await runFlowchart(parsedFlowchartId, { startNodeId })
      const runId = parseId(payload?.flowchart_run?.id)
      setActionInfo(runId ? `Flowchart run queued from ${nodeLabel} (run ${runId}).` : `Flowchart run queued from ${nodeLabel}.`)
      await refresh({ silent: true })
    })
  }

  async function handleQuickNodeFromNode(node) {
    const prompt = quickNodePromptFromFlowchartNode(node)
    if (!prompt) {
      setActionError('Add a task prompt, question prompt, additive prompt, or node title before using Quick Node.')
      return
    }
    const config = node?.config && typeof node.config === 'object' ? node.config : {}
    const mcpServerIds = Array.isArray(node?.mcp_server_ids)
      ? node.mcp_server_ids
        .map((value) => parseId(value))
        .filter((value) => value != null)
      : []
    const ragCollections = Array.isArray(config.collections)
      ? config.collections
        .map((value) => String(value || '').trim())
        .filter((value) => value)
      : []
    const modelId = parseId(node?.model_id)
    const nodeLabel = flowchartWorkspaceNodeLabel(node)
    await withAction('quick-node-from-node', async () => {
      const payload = await createQuickNode({
        prompt,
        modelId,
        mcpServerIds,
        ragCollections,
      })
      const taskId = parseId(payload?.task_id)
      if (taskId) {
        setActionInfo(`Quick Node queued from ${nodeLabel} (node ${taskId}).`)
        navigate(`/nodes/${taskId}`)
        return
      }
      setActionInfo(`Quick Node queued from ${nodeLabel}.`)
      navigate('/nodes')
    })
  }

  async function handleStop(force) {
    if (!activeRunId) {
      return
    }
    if (force && !window.confirm('Force stop active run now?')) {
      return
    }
    await withAction(force ? 'force-stop' : 'stop', async () => {
      await cancelFlowchartRun(activeRunId, { force })
      setActionInfo(force ? 'Force stop requested.' : 'Stop requested.')
      await refresh({ silent: true })
    })
  }

  async function handleValidate() {
    if (!parsedFlowchartId) {
      return
    }
    await withAction('validate', async () => {
      if (draftValidationErrors.length > 0) {
        setValidationState({ valid: false, errors: draftValidationErrors })
        setActionInfo('Validation reported errors in the current draft.')
        return
      }
      const payload = await validateFlowchart(parsedFlowchartId)
      setValidationState({ valid: Boolean(payload?.valid), errors: Array.isArray(payload?.errors) ? payload.errors : [] })
      setActionInfo(payload?.valid ? 'Validation passed.' : 'Validation reported errors.')
    })
  }

  async function handleSaveGraph() {
    if (!parsedFlowchartId) {
      return
    }
    if (workspaceEditorRef.current?.validateBeforeSave && !workspaceEditorRef.current.validateBeforeSave()) {
      return
    }
    await withAction('save-graph', async () => {
      const nodesPayload = Array.isArray(editorGraph?.nodes) ? editorGraph.nodes : []
      const edgesPayload = Array.isArray(editorGraph?.edges) ? editorGraph.edges : []
      const payload = await updateFlowchartGraph(parsedFlowchartId, {
        nodes: nodesPayload,
        edges: edgesPayload,
      })
      const nextNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
      const nextEdges = Array.isArray(payload?.edges) ? payload.edges : []
      const nextValidation = payload?.validation && typeof payload.validation === 'object'
        ? payload.validation
        : { valid: true, errors: [] }
      setState((current) => {
        if (!current.payload || typeof current.payload !== 'object') {
          return current
        }
        const nextDetail = {
          ...(current.payload.detail || {}),
          graph: { nodes: nextNodes, edges: nextEdges },
          validation: nextValidation,
        }
        return {
          ...current,
          payload: {
            ...current.payload,
            detail: nextDetail,
          },
        }
      })
      setEditorGraph({ nodes: nextNodes, edges: nextEdges })
      const applied = workspaceEditorRef.current?.applyServerGraph?.(nextNodes, nextEdges)
      if (!applied) {
        setEditorRevision((current) => current + 1)
      }
      setValidationState(nextValidation)
      setActionInfo('Graph saved.')
    })
  }

  function handleResetGraph() {
    setEditorGraph({ nodes, edges })
    setEditorRevision((current) => current + 1)
    setActionError('')
    setActionInfo('Graph workspace reset to latest server payload.')
  }

  const baseValidation = validationState && typeof validationState === 'object'
    ? validationState
    : detail?.validation
  const activeValidation = draftValidationErrors.length > 0
    ? { valid: false, errors: draftValidationErrors }
    : baseValidation
  const validationErrors = Array.isArray(activeValidation?.errors) ? activeValidation.errors : []
  const runtimeLabel = runtimeStatus || 'idle'
  const validationIssueCount = validationErrors.length
  const validationLabel = activeValidation?.valid
    ? 'valid'
    : `${validationIssueCount} issue${validationIssueCount === 1 ? '' : 's'}`
  const hasTopNotices = Boolean(state.loading || state.error || runtimeWarning || catalogWarning)
  const workspacePanelActions = (
    <div className="flowchart-fixed-workspace-actions">
      <div className="table-actions flowchart-fixed-primary-actions">
        {parsedFlowchartId ? (
          <Link
            to="/flowcharts"
            className="icon-button"
            aria-label="Back to flowcharts"
            title="Back to flowcharts"
          >
            <i className="fa-solid fa-arrow-left" />
          </Link>
        ) : null}
        <button
          type="button"
          className="icon-button flowchart-icon-button-primary"
          aria-label="Save graph"
          title="Save graph"
          disabled={isBusy('save-graph')}
          onClick={handleSaveGraph}
        >
          <i className="fa-solid fa-floppy-disk" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Validate"
          title="Validate"
          disabled={isBusy('validate')}
          onClick={handleValidate}
        >
          <i className="fa-solid fa-check" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Run flowchart"
          title="Run flowchart"
          disabled={isBusy('run') || activeRun}
          onClick={handleRun}
        >
          <i className="fa-solid fa-play" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Reset graph workspace"
          title="Reset graph workspace"
          onClick={handleResetGraph}
        >
          <i className="fa-solid fa-rotate-left" />
        </button>
      </div>
      <div className="table-actions flowchart-fixed-secondary-actions">
        {parsedFlowchartId ? (
          <Link
            to={`/flowcharts/${parsedFlowchartId}/edit`}
            className="icon-button"
            aria-label="Edit metadata"
            title="Edit metadata"
          >
            <i className="fa-solid fa-pen-to-square" />
          </Link>
        ) : null}
        {parsedFlowchartId ? (
          <Link
            to={`/flowcharts/${parsedFlowchartId}/history`}
            className="icon-button"
            aria-label="History"
            title="History"
          >
            <i className="fa-solid fa-clock-rotate-left" />
          </Link>
        ) : null}
        {activeRunId ? (
          <Link
            to={`/flowcharts/runs/${activeRunId}`}
            className="icon-button"
            aria-label={`Open run ${activeRunId}`}
            title={`Open run ${activeRunId}`}
          >
            <i className="fa-solid fa-diagram-project" />
          </Link>
        ) : null}
        {activeRunId ? (
          <button
            type="button"
            className="icon-button"
            aria-label="Stop run"
            title="Stop run"
            disabled={isBusy('stop')}
            onClick={() => handleStop(false)}
          >
            <i className="fa-solid fa-stop" />
          </button>
        ) : null}
        {activeRunId ? (
          <button
            type="button"
            className="icon-button icon-button-danger"
            aria-label="Force stop run"
            title="Force stop run"
            disabled={isBusy('force-stop')}
            onClick={() => handleStop(true)}
          >
            <i className="fa-solid fa-ban" />
          </button>
        ) : null}
        <button
          type="button"
          className={`icon-button${isMetaExpanded ? ' icon-button-active' : ''}`}
          aria-label={isMetaExpanded ? 'Hide metadata' : 'Show metadata'}
          title={isMetaExpanded ? 'Hide metadata' : 'Show metadata'}
          aria-expanded={isMetaExpanded}
          aria-controls="flowchart-inline-meta"
          onClick={() => setIsMetaExpanded((current) => !current)}
        >
          <i className={`fa-solid ${isMetaExpanded ? 'fa-chevron-up' : 'fa-chevron-down'}`} />
        </button>
        <button
          type="button"
          className="icon-button icon-button-danger"
          aria-label="Delete flowchart"
          title="Delete flowchart"
          disabled={isBusy('delete')}
          onClick={handleDelete}
        >
          <i className="fa-solid fa-trash" />
        </button>
      </div>
    </div>
  )
  const handleWorkspaceNotice = useCallback((message) => {
    const text = String(message || '').trim()
    if (!text) {
      return
    }
    setActionError(text)
  }, [setActionError])

  const handleWorkspaceGraphChange = useCallback((nextGraph) => {
    const nextNodes = Array.isArray(nextGraph?.nodes) ? nextGraph.nodes : []
    const nextEdges = Array.isArray(nextGraph?.edges) ? nextGraph.edges : []
    setEditorGraph((current) => {
      if (current.nodes === nextNodes && current.edges === nextEdges) {
        return current
      }
      return { nodes: nextNodes, edges: nextEdges }
    })
  }, [])

  return (
    <section className="flowchart-fixed-page" aria-label="Flowchart detail">
      <article className="card flowchart-fixed-card">
        {hasTopNotices ? (
          <div className="flowchart-fixed-notices">
            {state.loading ? <p>Loading flowchart...</p> : null}
            {state.error ? <p className="error-text">{state.error}</p> : null}
            {runtimeWarning ? <p className="toolbar-meta">{runtimeWarning}</p> : null}
            {catalogWarning ? <p className="toolbar-meta">{catalogWarning}</p> : null}
          </div>
        ) : null}
        {flowchart && isMetaExpanded ? (
          <section className="flowchart-meta-panel" id="flowchart-inline-meta" aria-label="Flowchart metadata">
            <div className="flowchart-meta-head">
              <p className="flowchart-meta-title">
                <i className="fa-solid fa-chart-simple" />
                workspace metadata
              </p>
              <span className={`flowchart-meta-pill ${runtimeMetaTone(runtimeStatus)}`}>
                <i className="fa-solid fa-wave-square" />
                runtime {runtimeLabel}
              </span>
            </div>
            <div className="flowchart-meta-grid">
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">nodes</p>
                <p className="flowchart-meta-value">{nodes.length}</p>
              </article>
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">edges</p>
                <p className="flowchart-meta-value">{edges.length}</p>
              </article>
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">active run</p>
                <p className="flowchart-meta-value">{activeRunId ? `run ${activeRunId}` : 'none'}</p>
              </article>
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">max runtime</p>
                <p className="flowchart-meta-value">{flowchart.max_runtime_minutes || '-'}m</p>
              </article>
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">max parallel</p>
                <p className="flowchart-meta-value">{flowchart.max_parallel_nodes || 1}</p>
              </article>
              <article className="flowchart-meta-item">
                <p className="flowchart-meta-label">validation</p>
                <p className={`flowchart-meta-value ${activeValidation?.valid ? 'is-valid' : 'is-invalid'}`}>
                  {activeValidation?.valid ? (
                    <i className="fa-solid fa-circle-check" />
                  ) : (
                    <i className="fa-solid fa-triangle-exclamation" />
                  )}
                  {validationLabel}
                </p>
              </article>
            </div>
          </section>
        ) : null}

        <div className="flowchart-fixed-workspace">
          <FlowchartWorkspaceEditor
            ref={workspaceEditorRef}
            key={`flowchart-workspace-${editorRevision}`}
            initialNodes={nodes}
            initialEdges={edges}
            catalog={catalog}
            nodeTypes={nodeTypeOptions}
            runningNodeIds={runningNodeIds}
            panelTitle="Workspace"
            panelActions={workspacePanelActions}
            onGraphChange={handleWorkspaceGraphChange}
            onNotice={handleWorkspaceNotice}
            onSaveGraph={handleSaveGraph}
            onRunFromNode={handleRunFromNode}
            onQuickNodeFromNode={handleQuickNodeFromNode}
            saveGraphBusy={isBusy('save-graph')}
          />
        </div>
      </article>
    </section>
  )
}

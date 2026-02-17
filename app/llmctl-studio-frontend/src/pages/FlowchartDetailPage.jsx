import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
import FlowchartWorkspaceEditor from '../components/FlowchartWorkspaceEditor'
import { HttpError } from '../lib/httpClient'
import {
  attachFlowchartNodeMcp,
  attachFlowchartNodeScript,
  attachFlowchartNodeSkill,
  cancelFlowchartRun,
  deleteFlowchart,
  detachFlowchartNodeMcp,
  detachFlowchartNodeScript,
  detachFlowchartNodeSkill,
  getFlowchartGraph,
  getFlowchartEdit,
  getFlowchartHistory,
  getFlowchartNodeUtilities,
  getFlowchartRuntime,
  reorderFlowchartNodeScripts,
  reorderFlowchartNodeSkills,
  runFlowchart,
  setFlowchartNodeModel,
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

function runStatusClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'queued') {
    return 'status-chip status-running'
  }
  if (normalized === 'stopping') {
    return 'status-chip status-warning'
  }
  if (normalized === 'failed' || normalized === 'error') {
    return 'status-chip status-failed'
  }
  return 'status-chip status-idle'
}

function isRunActive(status) {
  const normalized = String(status || '').toLowerCase()
  return normalized === 'queued' || normalized === 'running' || normalized === 'stopping'
}

function toJsonText(value) {
  return JSON.stringify(value, null, 2)
}

function parseCsvIds(raw) {
  if (!String(raw || '').trim()) {
    return []
  }
  return String(raw)
    .split(',')
    .map((item) => Number.parseInt(item.trim(), 10))
    .filter((item) => Number.isInteger(item) && item > 0)
}

const DEFAULT_FLOWCHART_NODE_TYPES = ['start', 'end', 'flowchart', 'task', 'plan', 'milestone', 'memory', 'decision', 'rag']

export default function FlowchartDetailPage() {
  const navigate = useNavigate()
  const { flowchartId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [graphDraft, setGraphDraft] = useState({ nodesText: '[]', edgesText: '[]' })
  const [editorGraph, setEditorGraph] = useState({ nodes: [], edges: [] })
  const [editorRevision, setEditorRevision] = useState(0)
  const [validationState, setValidationState] = useState(null)
  const [runtimeWarning, setRuntimeWarning] = useState('')
  const [catalogWarning, setCatalogWarning] = useState('')

  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [utilityState, setUtilityState] = useState({ loading: false, payload: null, error: '' })
  const [modelIdInput, setModelIdInput] = useState('')
  const [mcpServerIdInput, setMcpServerIdInput] = useState('')
  const [scriptIdInput, setScriptIdInput] = useState('')
  const [skillIdInput, setSkillIdInput] = useState('')
  const [scriptIdsInput, setScriptIdsInput] = useState('')
  const [skillIdsInput, setSkillIdsInput] = useState('')

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
      const graph = detail?.graph && typeof detail.graph === 'object' ? detail.graph : { nodes: [], edges: [] }
      const nextNodes = Array.isArray(graph.nodes) ? graph.nodes : []
      const nextEdges = Array.isArray(graph.edges) ? graph.edges : []
      setGraphDraft({ nodesText: toJsonText(nextNodes), edgesText: toJsonText(nextEdges) })
      setEditorGraph({ nodes: nextNodes, edges: nextEdges })
      setEditorRevision((current) => current + 1)
      setValidationState(detail?.validation && typeof detail.validation === 'object' ? detail.validation : null)
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

  const refreshUtilities = useCallback(async (nodeId, { silent = false } = {}) => {
    if (!parsedFlowchartId || !nodeId) {
      setUtilityState({ loading: false, payload: null, error: '' })
      return
    }
    if (!silent) {
      setUtilityState((current) => ({ ...current, loading: true, error: '' }))
    }
    try {
      const payload = await getFlowchartNodeUtilities(parsedFlowchartId, nodeId)
      setUtilityState({ loading: false, payload, error: '' })
      setModelIdInput(payload?.node?.model_id ? String(payload.node.model_id) : '')
      setScriptIdsInput(Array.isArray(payload?.node?.script_ids) ? payload.node.script_ids.join(',') : '')
      setSkillIdsInput('')
    } catch (error) {
      setUtilityState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load node utilities.'),
      }))
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
  const persistedNodes = useMemo(
    () => nodes.filter((node) => parseId(node?.id)),
    [nodes],
  )
  const selectedPersistedNodeId = useMemo(() => parseId(selectedNodeId), [selectedNodeId])
  const runs = Array.isArray(detail?.runs) ? detail.runs : []
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
  const utilitiesAvailable = Boolean(catalog)

  useEffect(() => {
    if (!selectedNodeId && persistedNodes.length > 0) {
      setSelectedNodeId(String(persistedNodes[0].id))
      return
    }
    if (
      selectedNodeId &&
      persistedNodes.every((node) => String(node.id) !== String(selectedNodeId))
    ) {
      setSelectedNodeId(persistedNodes.length > 0 ? String(persistedNodes[0].id) : '')
    }
  }, [persistedNodes, selectedNodeId])

  useEffect(() => {
    if (!utilitiesAvailable || !selectedPersistedNodeId) {
      setUtilityState({ loading: false, payload: null, error: '' })
      return
    }
    refreshUtilities(selectedPersistedNodeId)
  }, [selectedPersistedNodeId, refreshUtilities, utilitiesAvailable])

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
      const payload = await validateFlowchart(parsedFlowchartId)
      setValidationState({ valid: Boolean(payload?.valid), errors: Array.isArray(payload?.errors) ? payload.errors : [] })
      setActionInfo(payload?.valid ? 'Validation passed.' : 'Validation reported errors.')
    })
  }

  async function handleSaveGraph() {
    if (!parsedFlowchartId) {
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
      setGraphDraft({ nodesText: toJsonText(nextNodes), edgesText: toJsonText(nextEdges) })
      setEditorGraph({ nodes: nextNodes, edges: nextEdges })
      setEditorRevision((current) => current + 1)
      setValidationState(nextValidation)
      setActionInfo('Graph saved.')
      if (selectedPersistedNodeId) {
        await refreshUtilities(selectedPersistedNodeId, { silent: true })
      }
    })
  }

  function handleResetGraph() {
    setGraphDraft({ nodesText: toJsonText(nodes), edgesText: toJsonText(edges) })
    setEditorGraph({ nodes, edges })
    setEditorRevision((current) => current + 1)
    setActionError('')
    setActionInfo('Graph workspace reset to latest server payload.')
  }

  async function handleSetModel() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    await withAction('set-model', async () => {
      await setFlowchartNodeModel(parsedFlowchartId, selectedPersistedNodeId, {
        modelId: parseId(modelIdInput),
      })
      setActionInfo('Node model updated.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleAttachMcp() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    const parsedMcpId = parseId(mcpServerIdInput)
    if (!parsedMcpId) {
      setActionError('Select an MCP server to attach.')
      return
    }
    await withAction('attach-mcp', async () => {
      await attachFlowchartNodeMcp(parsedFlowchartId, selectedPersistedNodeId, { mcpServerId: parsedMcpId })
      setActionInfo('MCP server attached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleDetachMcp(mcpId) {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    await withAction(`detach-mcp-${mcpId}`, async () => {
      await detachFlowchartNodeMcp(parsedFlowchartId, selectedPersistedNodeId, mcpId)
      setActionInfo('MCP server detached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleAttachScript() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    const parsedScriptId = parseId(scriptIdInput)
    if (!parsedScriptId) {
      setActionError('Select a script to attach.')
      return
    }
    await withAction('attach-script', async () => {
      await attachFlowchartNodeScript(parsedFlowchartId, selectedPersistedNodeId, { scriptId: parsedScriptId })
      setActionInfo('Script attached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleDetachScript(scriptId) {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    await withAction(`detach-script-${scriptId}`, async () => {
      await detachFlowchartNodeScript(parsedFlowchartId, selectedPersistedNodeId, scriptId)
      setActionInfo('Script detached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleReorderScripts() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    await withAction('reorder-scripts', async () => {
      await reorderFlowchartNodeScripts(parsedFlowchartId, selectedPersistedNodeId, {
        scriptIds: parseCsvIds(scriptIdsInput),
      })
      setActionInfo('Script order updated.')
      await refresh({ silent: true })
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleAttachSkill() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    const parsedSkillId = parseId(skillIdInput)
    if (!parsedSkillId) {
      setActionError('Provide a skill id to attach.')
      return
    }
    await withAction('attach-skill', async () => {
      const payload = await attachFlowchartNodeSkill(parsedFlowchartId, selectedPersistedNodeId, {
        skillId: parsedSkillId,
      })
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill attach request sent.')
      }
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleDetachSkill() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    const parsedSkillId = parseId(skillIdInput)
    if (!parsedSkillId) {
      setActionError('Provide a skill id to detach.')
      return
    }
    await withAction('detach-skill', async () => {
      const payload = await detachFlowchartNodeSkill(parsedFlowchartId, selectedPersistedNodeId, parsedSkillId)
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill detach request sent.')
      }
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  async function handleReorderSkills() {
    if (!parsedFlowchartId || !selectedPersistedNodeId) {
      return
    }
    await withAction('reorder-skills', async () => {
      const payload = await reorderFlowchartNodeSkills(parsedFlowchartId, selectedPersistedNodeId, {
        skillIds: parseCsvIds(skillIdsInput),
      })
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill reorder request sent.')
      }
      await refreshUtilities(selectedPersistedNodeId, { silent: true })
    })
  }

  const activeValidation = validationState && typeof validationState === 'object'
    ? validationState
    : detail?.validation
  const validationErrors = Array.isArray(activeValidation?.errors) ? activeValidation.errors : []

  function handleWorkspaceNotice(message) {
    const text = String(message || '').trim()
    if (!text) {
      return
    }
    setActionError(text)
  }

  function handleWorkspaceGraphChange(nextGraph) {
    const nextNodes = Array.isArray(nextGraph?.nodes) ? nextGraph.nodes : []
    const nextEdges = Array.isArray(nextGraph?.edges) ? nextGraph.edges : []
    setEditorGraph({ nodes: nextNodes, edges: nextEdges })
    setGraphDraft({ nodesText: toJsonText(nextNodes), edgesText: toJsonText(nextEdges) })
  }

  function handleWorkspaceSelectionChange(nextNodeId) {
    setSelectedNodeId(String(nextNodeId || ''))
  }

  const selectedNode = persistedNodes.find((node) => String(node.id) === String(selectedNodeId)) || null
  const utilityNode = utilityState.payload?.node && typeof utilityState.payload.node === 'object'
    ? utilityState.payload.node
    : null
  const utilityCatalog = utilityState.payload?.catalog && typeof utilityState.payload.catalog === 'object'
    ? utilityState.payload.catalog
    : catalog
  const utilityValidation = utilityState.payload?.validation && typeof utilityState.payload.validation === 'object'
    ? utilityState.payload.validation
    : null
  const models = Array.isArray(utilityCatalog?.models) ? utilityCatalog.models : []
  const mcpServers = Array.isArray(utilityCatalog?.mcp_servers) ? utilityCatalog.mcp_servers : []
  const scripts = Array.isArray(utilityCatalog?.scripts) ? utilityCatalog.scripts : []

  return (
    <section className="stack" aria-label="Flowchart detail">
      <article className="card">
        <div className="title-row" style={{ marginBottom: '12px' }}>
          <div className="table-actions">
            {parsedFlowchartId ? (
              <Link to="/flowcharts" className="btn btn-secondary">
                <i className="fa-solid fa-arrow-left" />
                back to flowcharts
              </Link>
            ) : null}
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}/edit`} className="btn btn-secondary">
                <i className="fa-solid fa-pen-to-square" />
                edit metadata
              </Link>
            ) : null}
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}/history`} className="btn btn-secondary">
                <i className="fa-solid fa-clock-rotate-left" />
                history
              </Link>
            ) : null}
            <button
              type="button"
              className="icon-button icon-button-danger"
              aria-label="Delete flowchart"
              title="Delete flowchart"
              disabled={isBusy('delete')}
              onClick={handleDelete}
            >
              <ActionIcon name="trash" />
            </button>
          </div>
        </div>
        {state.loading ? <p>Loading flowchart...</p> : null}
        {state.error ? <p className="error-text">{state.error}</p> : null}
        {runtimeWarning ? <p className="toolbar-meta">{runtimeWarning}</p> : null}
        {catalogWarning ? <p className="toolbar-meta">{catalogWarning}</p> : null}
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
        {flowchart ? (
          <div className="stack-sm">
            <p className="muted" style={{ marginTop: '4px' }}>
              flowchart {flowchart.id}: {flowchart.name}
            </p>
            <dl className="kv-grid">
              <div>
                <dt>Description</dt>
                <dd>{flowchart.description || '-'}</dd>
              </div>
              <div>
                <dt>Nodes</dt>
                <dd>{nodes.length}</dd>
              </div>
              <div>
                <dt>Edges</dt>
                <dd>{edges.length}</dd>
              </div>
              <div>
                <dt>Max node executions</dt>
                <dd>{flowchart.max_node_executions || '-'}</dd>
              </div>
              <div>
                <dt>Max runtime minutes</dt>
                <dd>{flowchart.max_runtime_minutes || '-'}</dd>
              </div>
              <div>
                <dt>Max parallel nodes</dt>
                <dd>{flowchart.max_parallel_nodes || 1}</dd>
              </div>
              <div>
                <dt>Active run</dt>
                <dd>{activeRunId ? `run ${activeRunId}` : '-'}</dd>
              </div>
              <div>
                <dt>Runtime status</dt>
                <dd>
                  <span className={runStatusClass(runtimeStatus)}>{runtimeStatus || 'idle'}</span>
                </dd>
              </div>
            </dl>
            <div className="table-actions">
              <button
                type="button"
                className="btn btn-primary"
                disabled={isBusy('save-graph')}
                onClick={handleSaveGraph}
              >
                <i className="fa-solid fa-floppy-disk" />
                save graph
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={isBusy('validate')}
                onClick={handleValidate}
              >
                <i className="fa-solid fa-check" />
                validate
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={isBusy('run') || activeRun}
                onClick={handleRun}
              >
                <i className="fa-solid fa-play" />
                run flowchart
              </button>
              {activeRunId ? (
                <Link to={`/flowcharts/runs/${activeRunId}`} className="btn btn-secondary">
                  <i className="fa-solid fa-diagram-project" />
                  open active run
                </Link>
              ) : null}
              {activeRunId ? (
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={isBusy('stop')}
                  onClick={() => handleStop(false)}
                >
                  <i className="fa-solid fa-stop" />
                  stop flowchart
                </button>
              ) : null}
              {activeRunId ? (
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={isBusy('force-stop')}
                  onClick={() => handleStop(true)}
                >
                  <i className="fa-solid fa-ban" />
                  force stop
                </button>
              ) : null}
            </div>
            {activeValidation ? (
              <div className="stack-sm">
                <p className={activeValidation.valid ? 'toolbar-meta' : 'error-text'}>
                  Validation: {activeValidation.valid ? 'valid' : 'invalid'}
                </p>
                {!activeValidation.valid && validationErrors.length > 0 ? (
                  <ul>
                    {validationErrors.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Flowchart Workspace</h2>
        <FlowchartWorkspaceEditor
          key={`flowchart-workspace-${editorRevision}`}
          initialNodes={nodes}
          initialEdges={edges}
          catalog={catalog}
          nodeTypes={nodeTypeOptions}
          runningNodeIds={runningNodeIds}
          onGraphChange={handleWorkspaceGraphChange}
          onNodeSelectionChange={handleWorkspaceSelectionChange}
          onNotice={handleWorkspaceNotice}
        />
        <div className="stack-sm">
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={isBusy('save-graph')}
              onClick={handleSaveGraph}
            >
              <i className="fa-solid fa-floppy-disk" />
              save graph
            </button>
            <button type="button" className="btn btn-secondary" onClick={handleResetGraph}>
              <i className="fa-solid fa-rotate-left" />
              reset workspace
            </button>
          </div>
          <details>
            <summary className="toolbar-meta">Raw graph JSON</summary>
            <label className="field">
              <span>nodes[] JSON</span>
              <textarea className="table-textarea" value={graphDraft.nodesText} readOnly />
            </label>
            <label className="field">
              <span>edges[] JSON</span>
              <textarea className="table-textarea" value={graphDraft.edgesText} readOnly />
            </label>
          </details>
        </div>
      </article>

      <article className="card">
        <h2>Node Utilities</h2>
        <p className="toolbar-meta">Select a persisted node to manage model/MCP/script/skill operations.</p>
        {!utilitiesAvailable ? (
          <p className="error-text">Node utilities are temporarily unavailable while catalog endpoints are degraded.</p>
        ) : null}
        <div className="toolbar-group">
          <label htmlFor="flowchart-node-select">Node</label>
          <select
            id="flowchart-node-select"
            value={selectedNodeId}
            onChange={(event) => setSelectedNodeId(event.target.value)}
            disabled={!utilitiesAvailable}
          >
            <option value="">Select node</option>
            {persistedNodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.title || `Node ${node.id}`} ({node.node_type})
              </option>
            ))}
          </select>
        </div>
        {utilityState.loading ? <p>Loading node utilities...</p> : null}
        {utilityState.error ? <p className="error-text">{utilityState.error}</p> : null}
        {selectedNode && utilityNode ? (
          <div className="stack-sm">
            <dl className="kv-grid">
              <div>
                <dt>Node</dt>
                <dd>{selectedNode.title || `Node ${selectedNode.id}`}</dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{selectedNode.node_type || '-'}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd>{utilityNode.model_id || '-'}</dd>
              </div>
              <div>
                <dt>MCP IDs</dt>
                <dd>{Array.isArray(utilityNode.mcp_server_ids) ? utilityNode.mcp_server_ids.join(', ') || '-' : '-'}</dd>
              </div>
              <div>
                <dt>Script IDs</dt>
                <dd>{Array.isArray(utilityNode.script_ids) ? utilityNode.script_ids.join(', ') || '-' : '-'}</dd>
              </div>
              <div>
                <dt>Attachment IDs</dt>
                <dd>{Array.isArray(utilityNode.attachment_ids) ? utilityNode.attachment_ids.join(', ') || '-' : '-'}</dd>
              </div>
            </dl>

            {utilityValidation ? (
              <p className={utilityValidation.valid ? 'toolbar-meta' : 'error-text'}>
                Utility compatibility: {utilityValidation.valid ? 'valid' : 'invalid'}
                {!utilityValidation.valid && Array.isArray(utilityValidation.errors)
                  ? ` (${utilityValidation.errors.join('; ')})`
                  : ''}
              </p>
            ) : null}

            <div className="form-grid">
              <label className="field">
                <span>Set model</span>
                <select value={modelIdInput} onChange={(event) => setModelIdInput(event.target.value)}>
                  <option value="">None</option>
                  {models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name || `Model ${model.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleSetModel}>
                  Save model
                </button>
              </div>
            </div>

            <div className="form-grid">
              <label className="field">
                <span>Attach MCP server</span>
                <select value={mcpServerIdInput} onChange={(event) => setMcpServerIdInput(event.target.value)}>
                  <option value="">Select MCP server</option>
                  {mcpServers.map((server) => (
                    <option key={server.id} value={server.id}>
                      {server.name || `MCP ${server.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleAttachMcp}>
                  Attach MCP
                </button>
              </div>
              {Array.isArray(utilityNode.mcp_server_ids) && utilityNode.mcp_server_ids.length > 0 ? (
                <div className="table-actions">
                  {utilityNode.mcp_server_ids.map((mcpId) => (
                    <button
                      key={mcpId}
                      type="button"
                      className="icon-button icon-button-danger"
                      aria-label={`Detach MCP ${mcpId}`}
                      title={`Detach MCP ${mcpId}`}
                      onClick={() => handleDetachMcp(mcpId)}
                    >
                      <ActionIcon name="trash" />
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            <div className="form-grid">
              <label className="field">
                <span>Attach script</span>
                <select value={scriptIdInput} onChange={(event) => setScriptIdInput(event.target.value)}>
                  <option value="">Select script</option>
                  {scripts.map((script) => (
                    <option key={script.id} value={script.id}>
                      {script.file_name || `Script ${script.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleAttachScript}>
                  Attach script
                </button>
              </div>
              {Array.isArray(utilityNode.script_ids) && utilityNode.script_ids.length > 0 ? (
                <div className="table-actions">
                  {utilityNode.script_ids.map((scriptId) => (
                    <button
                      key={scriptId}
                      type="button"
                      className="icon-button icon-button-danger"
                      aria-label={`Detach script ${scriptId}`}
                      title={`Detach script ${scriptId}`}
                      onClick={() => handleDetachScript(scriptId)}
                    >
                      <ActionIcon name="trash" />
                    </button>
                  ))}
                </div>
              ) : null}
              <label className="field">
                <span>Reorder script ids (comma separated)</span>
                <input
                  type="text"
                  value={scriptIdsInput}
                  onChange={(event) => setScriptIdsInput(event.target.value)}
                  placeholder="3,5,8"
                />
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleReorderScripts}>
                  Save script order
                </button>
              </div>
            </div>

            <div className="form-grid">
              <label className="field">
                <span>Skill id</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={skillIdInput}
                  onChange={(event) => setSkillIdInput(event.target.value)}
                  placeholder="42"
                />
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleAttachSkill}>
                  Attach skill
                </button>
                <button type="button" className="btn-link btn-secondary" onClick={handleDetachSkill}>
                  Detach skill
                </button>
              </div>
              <label className="field">
                <span>Reorder skill ids (comma separated)</span>
                <input
                  type="text"
                  value={skillIdsInput}
                  onChange={(event) => setSkillIdsInput(event.target.value)}
                  placeholder="2,4,6"
                />
              </label>
              <div className="form-actions">
                <button type="button" className="btn-link btn-secondary" onClick={handleReorderSkills}>
                  Save skill order
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </article>

      <article className="card">
        <h2>Recent Runs</h2>
        {runs.length === 0 ? <p>No runs recorded yet.</p> : null}
        {runs.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Started</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link to={`/flowcharts/runs/${run.id}`}>Run {run.id}</Link>
                    </td>
                    <td>
                      <span className={runStatusClass(run.status)}>{run.status || '-'}</span>
                    </td>
                    <td>{run.created_at || '-'}</td>
                    <td>{run.started_at || '-'}</td>
                    <td>{run.finished_at || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </article>
    </section>
  )
}

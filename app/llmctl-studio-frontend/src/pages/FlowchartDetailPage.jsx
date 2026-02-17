import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ActionIcon from '../components/ActionIcon'
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
  getFlowchart,
  getFlowchartEdit,
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

function parseJsonArray(raw, label) {
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error(`${label} must be valid JSON.`)
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON array.`)
  }
  return parsed
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

export default function FlowchartDetailPage() {
  const navigate = useNavigate()
  const { flowchartId } = useParams()
  const parsedFlowchartId = useMemo(() => parseId(flowchartId), [flowchartId])

  const [state, setState] = useState({ loading: true, payload: null, error: '' })
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [graphDraft, setGraphDraft] = useState({ nodesText: '[]', edgesText: '[]' })
  const [validationState, setValidationState] = useState(null)

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
      const [detail, edit, runtime] = await Promise.all([
        getFlowchart(parsedFlowchartId),
        getFlowchartEdit(parsedFlowchartId),
        getFlowchartRuntime(parsedFlowchartId),
      ])
      setState({
        loading: false,
        payload: { detail, edit, runtime },
        error: '',
      })
      const graph = detail?.graph && typeof detail.graph === 'object' ? detail.graph : { nodes: [], edges: [] }
      const nextNodes = Array.isArray(graph.nodes) ? graph.nodes : []
      const nextEdges = Array.isArray(graph.edges) ? graph.edges : []
      setGraphDraft({ nodesText: toJsonText(nextNodes), edgesText: toJsonText(nextEdges) })
      setValidationState(detail?.validation && typeof detail.validation === 'object' ? detail.validation : null)
    } catch (error) {
      setState((current) => ({
        loading: false,
        payload: silent ? current.payload : null,
        error: errorMessage(error, 'Failed to load flowchart.'),
      }))
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
  const graph = detail?.graph && typeof detail.graph === 'object' ? detail.graph : null
  const nodes = useMemo(
    () => (Array.isArray(graph?.nodes) ? graph.nodes : []),
    [graph],
  )
  const edges = useMemo(
    () => (Array.isArray(graph?.edges) ? graph.edges : []),
    [graph],
  )
  const runs = Array.isArray(detail?.runs) ? detail.runs : []
  const catalog = edit?.catalog && typeof edit.catalog === 'object' ? edit.catalog : null
  const runtimeStatus = runtime?.active_run_status || ''
  const activeRunId = runtime?.active_run_id || null
  const activeRun = isRunActive(runtimeStatus)

  useEffect(() => {
    if (!selectedNodeId && nodes.length > 0) {
      setSelectedNodeId(String(nodes[0].id))
      return
    }
    if (selectedNodeId && nodes.every((node) => String(node.id) !== String(selectedNodeId))) {
      setSelectedNodeId(nodes.length > 0 ? String(nodes[0].id) : '')
    }
  }, [nodes, selectedNodeId])

  useEffect(() => {
    if (!selectedNodeId) {
      setUtilityState({ loading: false, payload: null, error: '' })
      return
    }
    refreshUtilities(selectedNodeId)
  }, [selectedNodeId, refreshUtilities])

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
      const nodesPayload = parseJsonArray(graphDraft.nodesText, 'nodes')
      const edgesPayload = parseJsonArray(graphDraft.edgesText, 'edges')
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
      setValidationState(nextValidation)
      setActionInfo('Graph saved.')
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  function handleResetGraph() {
    setGraphDraft({ nodesText: toJsonText(nodes), edgesText: toJsonText(edges) })
    setActionError('')
    setActionInfo('Graph editor reset to latest server payload.')
  }

  async function handleSetModel() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    await withAction('set-model', async () => {
      await setFlowchartNodeModel(parsedFlowchartId, selectedNodeId, {
        modelId: parseId(modelIdInput),
      })
      setActionInfo('Node model updated.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleAttachMcp() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    const parsedMcpId = parseId(mcpServerIdInput)
    if (!parsedMcpId) {
      setActionError('Select an MCP server to attach.')
      return
    }
    await withAction('attach-mcp', async () => {
      await attachFlowchartNodeMcp(parsedFlowchartId, selectedNodeId, { mcpServerId: parsedMcpId })
      setActionInfo('MCP server attached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleDetachMcp(mcpId) {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    await withAction(`detach-mcp-${mcpId}`, async () => {
      await detachFlowchartNodeMcp(parsedFlowchartId, selectedNodeId, mcpId)
      setActionInfo('MCP server detached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleAttachScript() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    const parsedScriptId = parseId(scriptIdInput)
    if (!parsedScriptId) {
      setActionError('Select a script to attach.')
      return
    }
    await withAction('attach-script', async () => {
      await attachFlowchartNodeScript(parsedFlowchartId, selectedNodeId, { scriptId: parsedScriptId })
      setActionInfo('Script attached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleDetachScript(scriptId) {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    await withAction(`detach-script-${scriptId}`, async () => {
      await detachFlowchartNodeScript(parsedFlowchartId, selectedNodeId, scriptId)
      setActionInfo('Script detached.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleReorderScripts() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    await withAction('reorder-scripts', async () => {
      await reorderFlowchartNodeScripts(parsedFlowchartId, selectedNodeId, {
        scriptIds: parseCsvIds(scriptIdsInput),
      })
      setActionInfo('Script order updated.')
      await refresh({ silent: true })
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleAttachSkill() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    const parsedSkillId = parseId(skillIdInput)
    if (!parsedSkillId) {
      setActionError('Provide a skill id to attach.')
      return
    }
    await withAction('attach-skill', async () => {
      const payload = await attachFlowchartNodeSkill(parsedFlowchartId, selectedNodeId, {
        skillId: parsedSkillId,
      })
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill attach request sent.')
      }
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleDetachSkill() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    const parsedSkillId = parseId(skillIdInput)
    if (!parsedSkillId) {
      setActionError('Provide a skill id to detach.')
      return
    }
    await withAction('detach-skill', async () => {
      const payload = await detachFlowchartNodeSkill(parsedFlowchartId, selectedNodeId, parsedSkillId)
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill detach request sent.')
      }
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  async function handleReorderSkills() {
    if (!parsedFlowchartId || !selectedNodeId) {
      return
    }
    await withAction('reorder-skills', async () => {
      const payload = await reorderFlowchartNodeSkills(parsedFlowchartId, selectedNodeId, {
        skillIds: parseCsvIds(skillIdsInput),
      })
      if (payload?.warning) {
        setActionInfo(payload.warning)
      } else {
        setActionInfo('Skill reorder request sent.')
      }
      await refreshUtilities(selectedNodeId, { silent: true })
    })
  }

  const activeValidation = validationState && typeof validationState === 'object'
    ? validationState
    : detail?.validation
  const validationErrors = Array.isArray(activeValidation?.errors) ? activeValidation.errors : []

  const selectedNode = nodes.find((node) => String(node.id) === String(selectedNodeId)) || null
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
        <div className="title-row">
          <div>
            <h2>{flowchart ? flowchart.name : 'Flowchart'}</h2>
            <p>Native React replacement for `/flowcharts/:flowchartId` editor/runtime workspace.</p>
          </div>
          <div className="table-actions">
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}/edit`} className="btn-link btn-secondary">Edit Metadata</Link>
            ) : null}
            {parsedFlowchartId ? (
              <Link to={`/flowcharts/${parsedFlowchartId}/history`} className="btn-link btn-secondary">History</Link>
            ) : null}
            <Link to="/flowcharts" className="btn-link btn-secondary">All Flowcharts</Link>
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
        {actionError ? <p className="error-text">{actionError}</p> : null}
        {actionInfo ? <p className="toolbar-meta">{actionInfo}</p> : null}
        {flowchart ? (
          <div className="stack-sm">
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
                className="btn-link btn-secondary"
                disabled={isBusy('validate')}
                onClick={handleValidate}
              >
                Validate
              </button>
              <button
                type="button"
                className="btn-link"
                disabled={isBusy('run') || activeRun}
                onClick={handleRun}
              >
                Run Flowchart
              </button>
              {activeRunId ? (
                <Link to={`/flowcharts/runs/${activeRunId}`} className="btn-link btn-secondary">Open Active Run</Link>
              ) : null}
              {activeRunId ? (
                <button
                  type="button"
                  className="btn-link btn-secondary"
                  disabled={isBusy('stop')}
                  onClick={() => handleStop(false)}
                >
                  Stop
                </button>
              ) : null}
              {activeRunId ? (
                <button
                  type="button"
                  className="btn-link"
                  disabled={isBusy('force-stop')}
                  onClick={() => handleStop(true)}
                >
                  Force Stop
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
        <h2>Graph Snapshot</h2>
        {nodes.length === 0 ? <p>No nodes found.</p> : null}
        {nodes.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Type</th>
                  <th>Ref</th>
                  <th>Model</th>
                  <th>MCP</th>
                  <th>Scripts</th>
                  <th>Position</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((node) => {
                  const isSelected = String(node.id) === String(selectedNodeId)
                  return (
                    <tr key={node.id}>
                      <td>
                        <button
                          type="button"
                          className="btn-link btn-secondary"
                          onClick={() => setSelectedNodeId(String(node.id))}
                        >
                          {node.title || `Node ${node.id}`}
                          {isSelected ? ' (selected)' : ''}
                        </button>
                      </td>
                      <td>{node.node_type || '-'}</td>
                      <td>{node.ref_id || '-'}</td>
                      <td>{node.model_id || '-'}</td>
                      <td>{Array.isArray(node.mcp_server_ids) ? node.mcp_server_ids.join(', ') || '-' : '-'}</td>
                      <td>{Array.isArray(node.script_ids) ? node.script_ids.join(', ') || '-' : '-'}</td>
                      <td>{`${node.x ?? 0}, ${node.y ?? 0}`}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="stack-sm">
          <label className="field">
            <span>nodes[] JSON</span>
            <textarea
              className="table-textarea"
              value={graphDraft.nodesText}
              onChange={(event) => setGraphDraft((current) => ({ ...current, nodesText: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>edges[] JSON</span>
            <textarea
              className="table-textarea"
              value={graphDraft.edgesText}
              onChange={(event) => setGraphDraft((current) => ({ ...current, edgesText: event.target.value }))}
            />
          </label>
          <div className="form-actions">
            <button
              type="button"
              className="btn-link"
              disabled={isBusy('save-graph')}
              onClick={handleSaveGraph}
            >
              Save Graph
            </button>
            <button type="button" className="btn-link btn-secondary" onClick={handleResetGraph}>
              Reset JSON
            </button>
          </div>
        </div>
      </article>

      <article className="card">
        <h2>Node Utilities</h2>
        <p className="toolbar-meta">Select a node above to manage model/MCP/script/skill operations.</p>
        <div className="toolbar-group">
          <label htmlFor="flowchart-node-select">Node</label>
          <select
            id="flowchart-node-select"
            value={selectedNodeId}
            onChange={(event) => setSelectedNodeId(event.target.value)}
          >
            {nodes.map((node) => (
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

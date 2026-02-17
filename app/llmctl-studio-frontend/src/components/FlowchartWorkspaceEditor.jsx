import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_NODE_TYPES = ['start', 'end', 'flowchart', 'task', 'plan', 'milestone', 'memory', 'decision', 'rag']
const NODE_TYPE_WITH_REF = new Set(['flowchart', 'task', 'plan', 'milestone', 'memory'])
const NODE_TYPE_REQUIRES_REF = new Set(['flowchart', 'plan', 'milestone', 'memory'])
const HANDLE_IDS = ['top', 'right', 'bottom', 'left']
const EDGE_MODE_OPTIONS = ['solid', 'dotted']
const TYPE_TO_REF_CATALOG_KEY = {
  flowchart: 'flowcharts',
  task: 'tasks',
  plan: 'plans',
  milestone: 'milestones',
  memory: 'memories',
}

const WORLD_WIDTH = 4200
const WORLD_HEIGHT = 2600

const NODE_DIMENSIONS = {
  start: { width: 108, height: 108 },
  end: { width: 108, height: 108 },
  flowchart: { width: 108, height: 108 },
  decision: { width: 148, height: 148 },
  plan: { width: 132, height: 132 },
  memory: { width: 190, height: 108 },
  default: { width: 190, height: 96 },
}

const CONNECTOR_LAYOUTS = {
  start: {
    top: { x: 0.5, y: 0 },
    right: { x: 1, y: 0.5 },
    bottom: { x: 0.5, y: 1 },
    left: { x: 0, y: 0.5 },
  },
  end: {
    top: { x: 0.5, y: 0 },
    right: { x: 1, y: 0.5 },
    bottom: { x: 0.5, y: 1 },
    left: { x: 0, y: 0.5 },
  },
  flowchart: {
    top: { x: 0.5, y: 0 },
    right: { x: 1, y: 0.5 },
    bottom: { x: 0.5, y: 1 },
    left: { x: 0, y: 0.5 },
  },
  default: {
    top: { x: 0.5, y: 0 },
    right: { x: 1, y: 0.5 },
    bottom: { x: 0.5, y: 1 },
    left: { x: 0, y: 0.5 },
  },
}

function parsePositiveInt(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

function parseOptionalInt(value) {
  if (value == null || value === '') {
    return null
  }
  const parsed = Number.parseInt(String(value), 10)
  return Number.isInteger(parsed) ? parsed : null
}

function toNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function normalizeNodeType(value) {
  const type = String(value || '').trim().toLowerCase()
  return DEFAULT_NODE_TYPES.includes(type) ? type : 'task'
}

function titleForType(type) {
  const normalized = normalizeNodeType(type)
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function nodeDimensions(type) {
  const normalized = normalizeNodeType(type)
  return NODE_DIMENSIONS[normalized] || NODE_DIMENSIONS.default
}

function connectorPosition(node, handleId) {
  const dimensions = nodeDimensions(node.node_type)
  const layout = CONNECTOR_LAYOUTS[normalizeNodeType(node.node_type)] || CONNECTOR_LAYOUTS.default
  const point = layout[handleId] || layout.right
  return {
    x: toNumber(node.x, 0) + dimensions.width * point.x,
    y: toNumber(node.y, 0) + dimensions.height * point.y,
  }
}

function edgePath(start, end) {
  const deltaX = Math.max(56, Math.abs(end.x - start.x) * 0.45)
  const control1 = { x: start.x + deltaX, y: start.y }
  const control2 = { x: end.x - deltaX, y: end.y }
  return `M ${start.x} ${start.y} C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${end.x} ${end.y}`
}

function makeNodeToken(persistedId, clientId) {
  if (persistedId) {
    return `id:${persistedId}`
  }
  return `client:${clientId}`
}

function defaultConfigForType(nodeType) {
  const normalized = normalizeNodeType(nodeType)
  if (normalized === 'task') {
    return { task_prompt: '' }
  }
  if (normalized === 'rag') {
    return {
      mode: 'query',
      collections: [],
      question_prompt: '',
    }
  }
  return {}
}

function refLabel(item, nodeType) {
  if (!item || typeof item !== 'object') {
    return '-'
  }
  if (nodeType === 'task') {
    return String(item.name || item.id)
  }
  return String(item.name || item.title || item.id)
}

function normalizeEdgeMode(value) {
  const mode = String(value || '').trim().toLowerCase()
  return EDGE_MODE_OPTIONS.includes(mode) ? mode : 'solid'
}

function buildNodePayload(node) {
  const payload = {
    id: node.persistedId || null,
    node_type: normalizeNodeType(node.node_type),
    title: String(node.title || '').trim() || null,
    ref_id: node.ref_id == null ? null : parseOptionalInt(node.ref_id),
    x: Number(toNumber(node.x, 0).toFixed(2)),
    y: Number(toNumber(node.y, 0).toFixed(2)),
    config: node.config && typeof node.config === 'object' ? node.config : {},
    model_id: node.model_id == null ? null : parseOptionalInt(node.model_id),
    mcp_server_ids: Array.isArray(node.mcp_server_ids) ? node.mcp_server_ids : [],
    script_ids: Array.isArray(node.script_ids) ? node.script_ids : [],
    attachment_ids: Array.isArray(node.attachment_ids) ? node.attachment_ids : [],
  }
  if (!node.persistedId) {
    payload.client_id = node.clientId
    delete payload.id
  }
  return payload
}

function buildEdgePayload(edge, nodesByToken) {
  const source = nodesByToken.get(edge.sourceToken)
  const target = nodesByToken.get(edge.targetToken)
  if (!source || !target) {
    return null
  }
  return {
    source_node_id: source.persistedId || source.clientId,
    target_node_id: target.persistedId || target.clientId,
    source_handle_id: edge.sourceHandleId || null,
    target_handle_id: edge.targetHandleId || null,
    edge_mode: normalizeEdgeMode(edge.edge_mode),
    condition_key: String(edge.condition_key || '').trim() || null,
    label: String(edge.label || '').trim() || null,
  }
}

function buildInitialWorkspace(initialNodes, initialEdges) {
  const normalizedNodes = []
  const tokenLookup = new Map()
  let maxClientNodeId = 0
  let maxClientEdgeId = 0

  const sourceNodes = Array.isArray(initialNodes) ? initialNodes : []
  for (const raw of sourceNodes) {
    const persistedId = parsePositiveInt(raw?.id)
    const rawClientId = parsePositiveInt(raw?.client_id)
    const clientId = rawClientId || (persistedId ? persistedId : maxClientNodeId + 1)
    maxClientNodeId = Math.max(maxClientNodeId, clientId)

    const nodeType = normalizeNodeType(raw?.node_type)
    const token = makeNodeToken(persistedId, clientId)
    const node = {
      token,
      persistedId,
      clientId,
      node_type: nodeType,
      title: String(raw?.title || '').trim() || titleForType(nodeType),
      ref_id: parseOptionalInt(raw?.ref_id),
      x: toNumber(raw?.x, 0),
      y: toNumber(raw?.y, 0),
      config: raw?.config && typeof raw.config === 'object' ? { ...raw.config } : defaultConfigForType(nodeType),
      model_id: parseOptionalInt(raw?.model_id),
      mcp_server_ids: Array.isArray(raw?.mcp_server_ids) ? raw.mcp_server_ids.filter((value) => parsePositiveInt(value) != null) : [],
      script_ids: Array.isArray(raw?.script_ids) ? raw.script_ids.filter((value) => parsePositiveInt(value) != null) : [],
      attachment_ids: Array.isArray(raw?.attachment_ids) ? raw.attachment_ids.filter((value) => parsePositiveInt(value) != null) : [],
    }
    normalizedNodes.push(node)
    tokenLookup.set(String(raw?.id), token)
    tokenLookup.set(`id:${raw?.id}`, token)
    tokenLookup.set(String(clientId), token)
    tokenLookup.set(`client:${clientId}`, token)
  }

  const normalizedEdges = []
  const sourceEdges = Array.isArray(initialEdges) ? initialEdges : []
  for (const raw of sourceEdges) {
    const persistedId = parsePositiveInt(raw?.id)
    const sourceRaw = raw?.source_node_id ?? raw?.source
    const targetRaw = raw?.target_node_id ?? raw?.target
    const sourceToken = tokenLookup.get(String(sourceRaw)) || tokenLookup.get(`id:${sourceRaw}`) || tokenLookup.get(`client:${sourceRaw}`)
    const targetToken = tokenLookup.get(String(targetRaw)) || tokenLookup.get(`id:${targetRaw}`) || tokenLookup.get(`client:${targetRaw}`)
    if (!sourceToken || !targetToken) {
      continue
    }
    const localId = persistedId ? `id:${persistedId}` : `client-edge:${maxClientEdgeId + 1}`
    if (!persistedId) {
      maxClientEdgeId += 1
    }
    normalizedEdges.push({
      localId,
      persistedId,
      sourceToken,
      targetToken,
      sourceHandleId: String(raw?.source_handle_id || '').trim() || 'right',
      targetHandleId: String(raw?.target_handle_id || '').trim() || 'left',
      edge_mode: normalizeEdgeMode(raw?.edge_mode),
      condition_key: String(raw?.condition_key || '').trim(),
      label: String(raw?.label || '').trim(),
    })
  }

  return {
    nodes: normalizedNodes,
    edges: normalizedEdges,
    nextClientNodeId: Math.max(maxClientNodeId + 1, 1),
    nextClientEdgeId: Math.max(maxClientEdgeId + 1, 1),
  }
}

export default function FlowchartWorkspaceEditor({
  initialNodes = [],
  initialEdges = [],
  catalog = null,
  nodeTypes = DEFAULT_NODE_TYPES,
  runningNodeIds = [],
  onGraphChange,
  onNodeSelectionChange,
  onNotice,
}) {
  const initialWorkspace = useMemo(
    () => buildInitialWorkspace(initialNodes, initialEdges),
    [initialNodes, initialEdges],
  )
  const viewportRef = useRef(null)
  const nextClientNodeIdRef = useRef(initialWorkspace.nextClientNodeId)
  const nextClientEdgeIdRef = useRef(initialWorkspace.nextClientEdgeId)

  const [nodes, setNodes] = useState(() => initialWorkspace.nodes)
  const [edges, setEdges] = useState(() => initialWorkspace.edges)
  const [selectedNodeToken, setSelectedNodeToken] = useState('')
  const [selectedEdgeId, setSelectedEdgeId] = useState('')
  const [connectStart, setConnectStart] = useState(null)
  const [dragging, setDragging] = useState(null)

  const runningNodeIdSet = useMemo(() => {
    const values = Array.isArray(runningNodeIds) ? runningNodeIds : []
    return new Set(values.map((value) => parsePositiveInt(value)).filter((value) => value != null))
  }, [runningNodeIds])

  const availableNodeTypes = useMemo(() => {
    const fromApi = Array.isArray(nodeTypes) ? nodeTypes : []
    const normalized = fromApi
      .map((item) => normalizeNodeType(item))
      .filter((item, index, array) => array.indexOf(item) === index)
    return normalized.length > 0 ? normalized : DEFAULT_NODE_TYPES
  }, [nodeTypes])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    viewport.scrollLeft = Math.max(0, WORLD_WIDTH / 2 - viewport.clientWidth / 2)
    viewport.scrollTop = Math.max(0, WORLD_HEIGHT / 2 - viewport.clientHeight / 2)
  }, [])

  const nodesByToken = useMemo(() => {
    const map = new Map()
    for (const node of nodes) {
      map.set(node.token, node)
    }
    return map
  }, [nodes])

  useEffect(() => {
    if (typeof onGraphChange !== 'function') {
      return
    }
    const payloadNodes = nodes.map((node) => buildNodePayload(node))
    const payloadEdges = edges
      .map((edge) => buildEdgePayload(edge, nodesByToken))
      .filter((edge) => edge != null)
    onGraphChange({ nodes: payloadNodes, edges: payloadEdges })
  }, [nodes, edges, nodesByToken, onGraphChange])

  useEffect(() => {
    if (typeof onNodeSelectionChange !== 'function') {
      return
    }
    const selectedNode = nodesByToken.get(selectedNodeToken)
    if (!selectedNode || !selectedNode.persistedId) {
      onNodeSelectionChange('')
      return
    }
    onNodeSelectionChange(String(selectedNode.persistedId))
  }, [selectedNodeToken, nodesByToken, onNodeSelectionChange])

  useEffect(() => {
    if (!dragging) {
      return undefined
    }

    function onPointerMove(event) {
      const viewport = viewportRef.current
      if (!viewport) {
        return
      }
      const rect = viewport.getBoundingClientRect()
      const graphX = event.clientX - rect.left + viewport.scrollLeft
      const graphY = event.clientY - rect.top + viewport.scrollTop
      setNodes((current) => current.map((node) => {
        if (node.token !== dragging.token) {
          return node
        }
        const dimensions = nodeDimensions(node.node_type)
        const x = clamp(graphX - dragging.offsetX, 24, WORLD_WIDTH - dimensions.width - 24)
        const y = clamp(graphY - dragging.offsetY, 24, WORLD_HEIGHT - dimensions.height - 24)
        return {
          ...node,
          x,
          y,
        }
      }))
    }

    function onPointerUp() {
      setDragging(null)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
  }, [dragging])

  const selectedNode = selectedNodeToken ? nodesByToken.get(selectedNodeToken) || null : null
  const selectedEdge = selectedEdgeId
    ? edges.find((edge) => edge.localId === selectedEdgeId) || null
    : null

  const emitNotice = useCallback((message) => {
    if (typeof onNotice === 'function') {
      onNotice(String(message || ''))
    }
  }, [onNotice])

  function updateNode(token, updater) {
    setNodes((current) => current.map((node) => {
      if (node.token !== token) {
        return node
      }
      const nextNode = typeof updater === 'function' ? updater(node) : { ...node, ...updater }
      const normalizedType = normalizeNodeType(nextNode.node_type)
      return {
        ...nextNode,
        node_type: normalizedType,
        config: nextNode.config && typeof nextNode.config === 'object'
          ? nextNode.config
          : defaultConfigForType(normalizedType),
      }
    }))
  }

  function updateEdge(localId, updater) {
    setEdges((current) => current.map((edge) => {
      if (edge.localId !== localId) {
        return edge
      }
      return typeof updater === 'function' ? updater(edge) : { ...edge, ...updater }
    }))
  }

  function addNode(nodeType) {
    const normalizedType = normalizeNodeType(nodeType)
    if (normalizedType === 'start' && nodes.some((node) => normalizeNodeType(node.node_type) === 'start')) {
      emitNotice('Only one start node is allowed.')
      return
    }

    const viewport = viewportRef.current
    const dimensions = nodeDimensions(normalizedType)
    let x = WORLD_WIDTH / 2 - dimensions.width / 2
    let y = WORLD_HEIGHT / 2 - dimensions.height / 2
    if (viewport) {
      x = viewport.scrollLeft + viewport.clientWidth / 2 - dimensions.width / 2
      y = viewport.scrollTop + viewport.clientHeight / 2 - dimensions.height / 2
    }

    const clientId = nextClientNodeIdRef.current++
    const node = {
      token: makeNodeToken(null, clientId),
      persistedId: null,
      clientId,
      node_type: normalizedType,
      title: titleForType(normalizedType),
      ref_id: null,
      x: clamp(x, 24, WORLD_WIDTH - dimensions.width - 24),
      y: clamp(y, 24, WORLD_HEIGHT - dimensions.height - 24),
      config: defaultConfigForType(normalizedType),
      model_id: null,
      mcp_server_ids: [],
      script_ids: [],
      attachment_ids: [],
    }

    setNodes((current) => [...current, node])
    setSelectedNodeToken(node.token)
    setSelectedEdgeId('')
  }

  const removeNode = useCallback((token) => {
    const node = nodesByToken.get(token)
    if (!node) {
      return
    }
    if (normalizeNodeType(node.node_type) === 'start') {
      emitNotice('Start node cannot be deleted.')
      return
    }
    setNodes((current) => current.filter((item) => item.token !== token))
    setEdges((current) => current.filter((edge) => edge.sourceToken !== token && edge.targetToken !== token))
    setSelectedNodeToken('')
  }, [emitNotice, nodesByToken])

  const removeEdge = useCallback((localId) => {
    setEdges((current) => current.filter((edge) => edge.localId !== localId))
    setSelectedEdgeId('')
  }, [])

  useEffect(() => {
    function onKeyDown(event) {
      const tagName = String(event?.target?.tagName || '').toLowerCase()
      if (tagName === 'input' || tagName === 'textarea' || tagName === 'select' || event.metaKey || event.ctrlKey) {
        return
      }
      if (event.key === 'Escape') {
        setConnectStart(null)
        return
      }
      if (event.key !== 'Delete' && event.key !== 'Backspace') {
        return
      }
      if (selectedNodeToken) {
        const node = nodesByToken.get(selectedNodeToken)
        if (node && normalizeNodeType(node.node_type) === 'start') {
          emitNotice('Start node cannot be deleted.')
          event.preventDefault()
          return
        }
        removeNode(selectedNodeToken)
        event.preventDefault()
        return
      }
      if (selectedEdgeId) {
        removeEdge(selectedEdgeId)
        event.preventDefault()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [emitNotice, removeEdge, removeNode, selectedNodeToken, selectedEdgeId, nodesByToken])

  function beginDrag(event, node) {
    if (event.button !== 0) {
      return
    }
    if (event.target.closest('.flow-ws-node-connector')) {
      return
    }
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    event.preventDefault()
    const rect = viewport.getBoundingClientRect()
    const graphX = event.clientX - rect.left + viewport.scrollLeft
    const graphY = event.clientY - rect.top + viewport.scrollTop
    setDragging({
      token: node.token,
      offsetX: graphX - toNumber(node.x, 0),
      offsetY: graphY - toNumber(node.y, 0),
    })
    setSelectedNodeToken(node.token)
    setSelectedEdgeId('')
  }

  function createEdge(sourceToken, sourceHandleId, targetToken, targetHandleId) {
    const sourceNode = nodesByToken.get(sourceToken)
    const targetNode = nodesByToken.get(targetToken)
    if (!sourceNode || !targetNode) {
      return
    }
    if (sourceToken === targetToken) {
      return
    }
    const duplicate = edges.some((edge) => (
      edge.sourceToken === sourceToken &&
      edge.targetToken === targetToken &&
      edge.sourceHandleId === sourceHandleId &&
      edge.targetHandleId === targetHandleId
    ))
    if (duplicate) {
      return
    }

    const isDecision = normalizeNodeType(sourceNode.node_type) === 'decision'
    const decisionEdgeCount = edges.filter((edge) => edge.sourceToken === sourceToken).length
    const edge = {
      localId: `client-edge:${nextClientEdgeIdRef.current++}`,
      persistedId: null,
      sourceToken,
      targetToken,
      sourceHandleId,
      targetHandleId,
      edge_mode: 'solid',
      condition_key: isDecision ? `path_${decisionEdgeCount + 1}` : '',
      label: '',
    }
    setEdges((current) => [...current, edge])
    setSelectedEdgeId(edge.localId)
    setSelectedNodeToken('')
  }

  function toggleConnector(nodeToken, handleId) {
    if (!connectStart) {
      setConnectStart({ nodeToken, handleId })
      return
    }
    if (connectStart.nodeToken === nodeToken && connectStart.handleId === handleId) {
      setConnectStart(null)
      return
    }
    createEdge(connectStart.nodeToken, connectStart.handleId, nodeToken, handleId)
    setConnectStart(null)
  }

  function handleNodeTypeChange(node, nextNodeType) {
    const normalizedType = normalizeNodeType(nextNodeType)
    if (
      normalizedType === 'start' &&
      nodes.some((item) => item.token !== node.token && normalizeNodeType(item.node_type) === 'start')
    ) {
      emitNotice('Only one start node is allowed.')
      return
    }

    updateNode(node.token, (current) => {
      const nextConfig = current.config && typeof current.config === 'object'
        ? { ...current.config }
        : defaultConfigForType(normalizedType)
      if (normalizedType !== 'task') {
        delete nextConfig.task_prompt
      }
      if (normalizedType !== 'rag') {
        delete nextConfig.mode
        delete nextConfig.collections
        delete nextConfig.question_prompt
      }
      if (normalizedType === 'task' && typeof nextConfig.task_prompt !== 'string') {
        nextConfig.task_prompt = ''
      }
      if (normalizedType === 'rag') {
        if (!nextConfig.mode) {
          nextConfig.mode = 'query'
        }
        if (!Array.isArray(nextConfig.collections)) {
          nextConfig.collections = []
        }
        if (typeof nextConfig.question_prompt !== 'string') {
          nextConfig.question_prompt = ''
        }
      }
      return {
        ...current,
        node_type: normalizedType,
        ref_id: NODE_TYPE_WITH_REF.has(normalizedType) ? current.ref_id : null,
        config: nextConfig,
      }
    })
  }

  const selectedNodeRefOptions = useMemo(() => {
    if (!selectedNode) {
      return []
    }
    const key = TYPE_TO_REF_CATALOG_KEY[normalizeNodeType(selectedNode.node_type)]
    if (!key || !catalog || typeof catalog !== 'object') {
      return []
    }
    const rows = catalog[key]
    return Array.isArray(rows) ? rows : []
  }, [selectedNode, catalog])
  const modelOptions = useMemo(() => {
    if (!catalog || typeof catalog !== 'object' || !Array.isArray(catalog.models)) {
      return []
    }
    return catalog.models
  }, [catalog])

  return (
    <div className="flow-ws-layout">
      <aside className="flow-ws-sidebar">
        <p className="eyebrow">Node Bar</p>
        <p className="toolbar-meta">Click to add a node at the current viewport center.</p>
        <div className="flow-ws-palette">
          {availableNodeTypes.map((nodeType) => {
            const disabled = nodeType === 'start' && nodes.some((node) => normalizeNodeType(node.node_type) === 'start')
            return (
              <button
                key={nodeType}
                type="button"
                className="btn btn-secondary flow-ws-palette-item"
                disabled={disabled}
                onClick={() => addNode(nodeType)}
              >
                {nodeType}
              </button>
            )
          })}
        </div>
      </aside>

      <div className="flow-ws-editor">
        <div className="flow-ws-toolbar">
          <p className="toolbar-meta">
            {connectStart
              ? `Connecting from ${connectStart.nodeToken} (${connectStart.handleId}). Click a target handle.`
              : 'Drag nodes, click handles to connect, then edit in the inspector.'}
          </p>
          {connectStart ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setConnectStart(null)}
            >
              cancel connect
            </button>
          ) : null}
        </div>
        <div className="flow-ws-viewport" ref={viewportRef}>
          <div className="flow-ws-world" style={{ width: `${WORLD_WIDTH}px`, height: `${WORLD_HEIGHT}px` }}>
            <svg className="flow-ws-edge-layer" viewBox={`0 0 ${WORLD_WIDTH} ${WORLD_HEIGHT}`} preserveAspectRatio="none">
              {edges.map((edge) => {
                const sourceNode = nodesByToken.get(edge.sourceToken)
                const targetNode = nodesByToken.get(edge.targetToken)
                if (!sourceNode || !targetNode) {
                  return null
                }
                const start = connectorPosition(sourceNode, edge.sourceHandleId)
                const end = connectorPosition(targetNode, edge.targetHandleId)
                const path = edgePath(start, end)
                const selected = edge.localId === selectedEdgeId
                const midX = (start.x + end.x) / 2
                const midY = (start.y + end.y) / 2
                return (
                  <g key={edge.localId}>
                    <path
                      d={path}
                      className={`flow-ws-edge-path${edge.edge_mode === 'dotted' ? ' is-dotted' : ''}${selected ? ' is-selected' : ''}`}
                      onClick={() => {
                        setSelectedEdgeId(edge.localId)
                        setSelectedNodeToken('')
                      }}
                    />
                    {(edge.label || edge.condition_key) ? (
                      <text x={midX} y={midY - 8} className="flow-ws-edge-label">
                        {edge.label || edge.condition_key}
                      </text>
                    ) : null}
                  </g>
                )
              })}
            </svg>

            {nodes.map((node) => {
              const dimensions = nodeDimensions(node.node_type)
              const selected = selectedNodeToken === node.token
              const running = node.persistedId != null && runningNodeIdSet.has(node.persistedId)
              return (
                <button
                  key={node.token}
                  type="button"
                  className={`flow-ws-node is-type-${normalizeNodeType(node.node_type)}${selected ? ' is-selected' : ''}${running ? ' is-running' : ''}`}
                  style={{
                    left: `${toNumber(node.x, 0)}px`,
                    top: `${toNumber(node.y, 0)}px`,
                    width: `${dimensions.width}px`,
                    height: `${dimensions.height}px`,
                  }}
                  onPointerDown={(event) => beginDrag(event, node)}
                  onClick={() => {
                    setSelectedNodeToken(node.token)
                    setSelectedEdgeId('')
                  }}
                >
                  <span className="flow-ws-node-content">
                    <span className="flow-ws-node-title">{node.title || titleForType(node.node_type)}</span>
                    {node.ref_id ? <span className="flow-ws-node-meta">ref {node.ref_id}</span> : null}
                  </span>
                  {HANDLE_IDS.map((handleId) => {
                    const connector = connectorPosition(node, handleId)
                    const hot = connectStart && connectStart.nodeToken === node.token && connectStart.handleId === handleId
                    return (
                      <span
                        key={handleId}
                        className={`flow-ws-node-connector${hot ? ' is-hot' : ''}`}
                        style={{
                          left: `${connector.x - toNumber(node.x, 0)}px`,
                          top: `${connector.y - toNumber(node.y, 0)}px`,
                        }}
                        onClick={(event) => {
                          event.stopPropagation()
                          toggleConnector(node.token, handleId)
                        }}
                        title={`${node.title || node.node_type} ${handleId}`}
                      />
                    )
                  })}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <aside className="flow-ws-inspector">
        {selectedNode ? (
          <div className="stack-sm">
            <h3>Node Inspector</h3>
            <label className="field">
              <span>title</span>
              <input
                type="text"
                value={selectedNode.title || ''}
                onChange={(event) => updateNode(selectedNode.token, { title: event.target.value })}
              />
            </label>
            <label className="field">
              <span>type</span>
              <select
                value={normalizeNodeType(selectedNode.node_type)}
                onChange={(event) => handleNodeTypeChange(selectedNode, event.target.value)}
              >
                {availableNodeTypes.map((nodeType) => (
                  <option key={nodeType} value={nodeType}>
                    {nodeType}
                  </option>
                ))}
              </select>
            </label>
            {NODE_TYPE_WITH_REF.has(normalizeNodeType(selectedNode.node_type)) ? (
              <label className="field">
                <span>ref</span>
                {selectedNodeRefOptions.length > 0 ? (
                  <select
                    value={selectedNode.ref_id ?? ''}
                    onChange={(event) => updateNode(selectedNode.token, { ref_id: parseOptionalInt(event.target.value) })}
                  >
                    <option value="">{NODE_TYPE_REQUIRES_REF.has(normalizeNodeType(selectedNode.node_type)) ? 'Select...' : 'None'}</option>
                    {selectedNodeRefOptions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {refLabel(item, normalizeNodeType(selectedNode.node_type))}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={selectedNode.ref_id ?? ''}
                    onChange={(event) => updateNode(selectedNode.token, { ref_id: parseOptionalInt(event.target.value) })}
                    placeholder={NODE_TYPE_REQUIRES_REF.has(normalizeNodeType(selectedNode.node_type)) ? 'required' : 'optional'}
                  />
                )}
              </label>
            ) : null}
            {normalizeNodeType(selectedNode.node_type) === 'task' ? (
              <label className="field">
                <span>task prompt (used when no ref)</span>
                <textarea
                  value={String(selectedNode.config?.task_prompt || '')}
                  onChange={(event) => updateNode(selectedNode.token, (current) => ({
                    ...current,
                    config: {
                      ...(current.config && typeof current.config === 'object' ? current.config : {}),
                      task_prompt: event.target.value,
                    },
                  }))}
                />
              </label>
            ) : null}
            <label className="field">
              <span>model</span>
              <select
                value={selectedNode.model_id ?? ''}
                onChange={(event) => updateNode(selectedNode.token, { model_id: parseOptionalInt(event.target.value) })}
              >
                <option value="">None</option>
                {modelOptions.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name || `Model ${model.id}`}
                  </option>
                ))}
              </select>
            </label>
            <div className="flow-ws-position-grid">
              <label className="field">
                <span>x</span>
                <input
                  type="number"
                  value={Math.round(toNumber(selectedNode.x, 0))}
                  onChange={(event) => updateNode(selectedNode.token, { x: toNumber(event.target.value, selectedNode.x) })}
                />
              </label>
              <label className="field">
                <span>y</span>
                <input
                  type="number"
                  value={Math.round(toNumber(selectedNode.y, 0))}
                  onChange={(event) => updateNode(selectedNode.token, { y: toNumber(event.target.value, selectedNode.y) })}
                />
              </label>
            </div>
            {NODE_TYPE_REQUIRES_REF.has(normalizeNodeType(selectedNode.node_type)) && !selectedNode.ref_id ? (
              <p className="error-text">This node type requires a ref_id before save/validate.</p>
            ) : null}
            <div className="form-actions">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => removeNode(selectedNode.token)}
              >
                <i className="fa-solid fa-trash" />
                delete node
              </button>
            </div>
          </div>
        ) : null}

        {!selectedNode && selectedEdge ? (
          <div className="stack-sm">
            <h3>Edge Inspector</h3>
            <label className="field">
              <span>mode</span>
              <select
                value={normalizeEdgeMode(selectedEdge.edge_mode)}
                onChange={(event) => updateEdge(selectedEdge.localId, { edge_mode: normalizeEdgeMode(event.target.value) })}
              >
                {EDGE_MODE_OPTIONS.map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>condition key</span>
              <input
                type="text"
                value={selectedEdge.condition_key || ''}
                onChange={(event) => updateEdge(selectedEdge.localId, { condition_key: event.target.value })}
              />
            </label>
            <label className="field">
              <span>label</span>
              <input
                type="text"
                value={selectedEdge.label || ''}
                onChange={(event) => updateEdge(selectedEdge.localId, { label: event.target.value })}
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => removeEdge(selectedEdge.localId)}
              >
                <i className="fa-solid fa-trash" />
                delete edge
              </button>
            </div>
          </div>
        ) : null}

        {!selectedNode && !selectedEdge ? (
          <div className="stack-sm">
            <h3>Inspector</h3>
            <p className="toolbar-meta">Select a node or edge to edit.</p>
            <p className="toolbar-meta">Keyboard: Delete/Backspace removes selected node or edge.</p>
          </div>
        ) : null}
      </aside>
    </div>
  )
}

import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import PanelHeader from './PanelHeader'
import PersistedDetails from './PersistedDetails'

const DEFAULT_NODE_TYPES = ['start', 'end', 'flowchart', 'task', 'plan', 'milestone', 'memory', 'decision', 'rag']
const NODE_TYPE_WITH_REF = new Set(['flowchart', 'plan', 'milestone', 'memory'])
const NODE_TYPE_WITH_EDITABLE_REF = new Set(['flowchart'])
const NODE_TYPE_REQUIRES_REF = new Set(['flowchart'])
const HANDLE_IDS = ['top', 'right', 'bottom', 'left']
const EDGE_MODE_OPTIONS = ['solid', 'dotted']
const EDGE_CONTROL_STYLE_HARD = 'hard'
const EDGE_CONTROL_STYLE_CURVED = 'curved'
const EDGE_CONTROL_STYLE_OPTIONS = [
  { value: EDGE_CONTROL_STYLE_HARD, label: 'hard bends' },
  { value: EDGE_CONTROL_STYLE_CURVED, label: 'curved' },
]
const FAN_IN_MODE_ALL = 'all'
const FAN_IN_MODE_ANY = 'any'
const FAN_IN_MODE_CUSTOM = 'custom'
const DECISION_NO_MATCH_POLICY_FAIL = 'fail'
const DECISION_NO_MATCH_POLICY_FALLBACK = 'fallback'
const ROUTING_FOCUS_FIELD_FAN_IN_MODE = 'fanInMode'
const ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT = 'fanInCustomCount'
const ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR = 'fallbackConnector'
const FLOW_WS_ROUTING_DETAILS_ID = 'flow-ws-routing-details'
const EMPTY_ROUTING_VALIDATION = {
  hasErrors: false,
  errors: [],
  fieldErrors: {},
  firstInvalidField: '',
}
const MILESTONE_ACTION_OPTIONS = [
  { value: 'create_or_update', label: 'Create/Update milestone' },
  { value: 'mark_complete', label: 'Mark milestone complete' },
]
const MEMORY_ACTION_OPTIONS = [
  { value: 'add', label: 'Add memory' },
  { value: 'retrieve', label: 'Retrieve memory' },
]
const PLAN_ACTION_CREATE_OR_UPDATE = 'create_or_update_plan'
const PLAN_ACTION_COMPLETE_PLAN_ITEM = 'complete_plan_item'
const PLAN_ACTION_OPTIONS = [
  { value: PLAN_ACTION_CREATE_OR_UPDATE, label: 'Create or update plan' },
  { value: PLAN_ACTION_COMPLETE_PLAN_ITEM, label: 'Complete plan item' },
]
const MILESTONE_RETENTION_OPTIONS = [
  { value: 'ttl', label: 'TTL' },
  { value: 'max_count', label: 'Max count' },
  { value: 'ttl_max_count', label: 'TTL + max count' },
  { value: 'forever', label: 'Forever' },
]
const DEFAULT_MILESTONE_RETENTION_TTL_SECONDS = 3600
const DEFAULT_MILESTONE_RETENTION_MAX_COUNT = 25
const DEFAULT_PLAN_RETENTION_TTL_SECONDS = 3600
const DEFAULT_PLAN_RETENTION_MAX_COUNT = 25
const TYPE_TO_REF_CATALOG_KEY = {
  flowchart: 'flowcharts',
  plan: 'plans',
  milestone: 'milestones',
  memory: 'memories',
}
const NODE_TYPES_WITH_MODEL = new Set(['task', 'rag'])
const SPECIALIZED_NODE_TYPES = new Set(['milestone', 'memory', 'plan'])
const RAG_MODE_QUERY = 'query'
const RAG_MODE_FRESH_INDEX = 'fresh_index'
const RAG_MODE_DELTA_INDEX = 'delta_index'
const RAG_MODE_OPTIONS = [
  { value: RAG_MODE_FRESH_INDEX, label: 'index' },
  { value: RAG_MODE_DELTA_INDEX, label: 'delta index' },
  { value: RAG_MODE_QUERY, label: 'query' },
]
const RAG_EMBEDDING_MODEL_PROVIDERS = new Set(['codex', 'gemini'])

const WORLD_WIDTH = 16000
const WORLD_HEIGHT = 12000
const WORLD_PADDING = 24
const WORLD_ORIGIN_X = WORLD_WIDTH / 2
const WORLD_ORIGIN_Y = WORLD_HEIGHT / 2
const MIN_ZOOM = 0.5
const MAX_ZOOM = 1.8
const ZOOM_STEP = 0.1
const WHEEL_ZOOM_SENSITIVITY = 0.0008
const PALETTE_DRAG_TYPE = 'application/x-llmctl-flow-node-type'
const MAX_EDGE_CONTROL_POINTS = 24
const EDGE_POINT_MIN_X = -WORLD_ORIGIN_X + WORLD_PADDING
const EDGE_POINT_MIN_Y = -WORLD_ORIGIN_Y + WORLD_PADDING
const EDGE_POINT_MAX_X = WORLD_ORIGIN_X - WORLD_PADDING
const EDGE_POINT_MAX_Y = WORLD_ORIGIN_Y - WORLD_PADDING

const NODE_DIMENSIONS = {
  start: { width: 108, height: 108 },
  end: { width: 108, height: 108 },
  flowchart: { width: 108, height: 108 },
  decision: { width: 148, height: 148 },
  plan: { width: 132, height: 132 },
  memory: { width: 190, height: 108 },
  default: { width: 190, height: 96 },
}

const CORE_CONNECTOR_LAYOUT = [
  { id: 't1', side: 'top', x: 22, y: 0 },
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 't3', side: 'top', x: 78, y: 0 },
  { id: 'l1', side: 'left', x: 0, y: 50 },
  { id: 'l2', side: 'left', x: 0, y: 22 },
  { id: 'l3', side: 'left', x: 0, y: 78 },
  { id: 'r1', side: 'right', x: 100, y: 50 },
  { id: 'r2', side: 'right', x: 100, y: 22 },
  { id: 'r3', side: 'right', x: 100, y: 78 },
  { id: 'b1', side: 'bottom', x: 22, y: 100 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'b3', side: 'bottom', x: 78, y: 100 },
]
const DEFAULT_CONNECTOR_LAYOUT = [
  { id: 't1', side: 'top', x: 22, y: 0 },
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 't3', side: 'top', x: 78, y: 0 },
  { id: 'l1', side: 'left', x: 0, y: 50 },
  { id: 'r1', side: 'right', x: 100, y: 50 },
  { id: 'b1', side: 'bottom', x: 22, y: 100 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'b3', side: 'bottom', x: 78, y: 100 },
]
const START_CONNECTOR_LAYOUT = [
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 'r1', side: 'right', x: 100, y: 50 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'l1', side: 'left', x: 0, y: 50 },
]
const END_CONNECTOR_LAYOUT = [
  { id: 't1', side: 'oct-top-left', x: 29.3, y: 0 },
  { id: 't3', side: 'oct-top-right', x: 70.7, y: 0 },
  { id: 'r2', side: 'oct-right-top', x: 100, y: 29.3 },
  { id: 'r3', side: 'oct-right-bottom', x: 100, y: 70.7 },
  { id: 'b3', side: 'oct-bottom-right', x: 70.7, y: 100 },
  { id: 'b1', side: 'oct-bottom-left', x: 29.3, y: 100 },
  { id: 'l3', side: 'oct-left-bottom', x: 0, y: 70.7 },
  { id: 'l2', side: 'oct-left-top', x: 0, y: 29.3 },
]
const MILESTONE_CONNECTOR_LAYOUT = [
  { id: 't1', side: 'top', x: 12.1, y: 0 },
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 't3', side: 'top', x: 87.9, y: 0 },
  { id: 'l1', side: 'left', x: 0, y: 50 },
  { id: 'r1', side: 'right', x: 100, y: 50 },
  { id: 'b1', side: 'bottom', x: 12.1, y: 100 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'b3', side: 'bottom', x: 87.9, y: 100 },
]
const MEMORY_CONNECTOR_LAYOUT = [
  { id: 'm1', side: 'top', x: 14.2, y: 0 },
  { id: 'm2', side: 'top', x: 50, y: 0 },
  { id: 'm3', side: 'top', x: 85.8, y: 0 },
  { id: 'm4', side: 'left', x: 7.1, y: 50 },
  { id: 'm5', side: 'right', x: 92.9, y: 50 },
  { id: 'm6', side: 'bottom', x: 0, y: 100 },
  { id: 'm7', side: 'bottom', x: 50, y: 100 },
  { id: 'm8', side: 'bottom', x: 100, y: 100 },
]
const RAG_CONNECTOR_LAYOUT = [
  { id: 't1', side: 'top', x: 0, y: 0 },
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 't3', side: 'top', x: 100, y: 0 },
  { id: 'l1', side: 'left', x: 7, y: 50 },
  { id: 'l2', side: 'left', x: 3.1, y: 22 },
  { id: 'l3', side: 'left', x: 10.9, y: 78 },
  { id: 'r1', side: 'right', x: 93, y: 50 },
  { id: 'r2', side: 'right', x: 96.9, y: 22 },
  { id: 'r3', side: 'right', x: 89.1, y: 78 },
  { id: 'b1', side: 'bottom', x: 14, y: 100 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'b3', side: 'bottom', x: 86, y: 100 },
]
const DECISION_CONNECTOR_LAYOUT = [
  { id: 't2', side: 'top', x: 50, y: 0 },
  { id: 't3', side: 'decision-top-right', x: 75, y: 25 },
  { id: 'r1', side: 'right', x: 100, y: 50 },
  { id: 'b3', side: 'decision-bottom-right', x: 75, y: 75 },
  { id: 'b2', side: 'bottom', x: 50, y: 100 },
  { id: 'b1', side: 'decision-bottom-left', x: 25, y: 75 },
  { id: 'l1', side: 'left', x: 0, y: 50 },
  { id: 't1', side: 'decision-top-left', x: 25, y: 25 },
]

const CORE_CONNECTOR_BY_ID = new Map(CORE_CONNECTOR_LAYOUT.map((item) => [item.id, item]))
const END_CONNECTOR_BY_ID = new Map(END_CONNECTOR_LAYOUT.map((item) => [item.id, item]))
const DECISION_CONNECTOR_BY_ID = new Map(DECISION_CONNECTOR_LAYOUT.map((item) => [item.id, item]))
const MILESTONE_CONNECTOR_BY_ID = new Map(MILESTONE_CONNECTOR_LAYOUT.map((item) => [item.id, item]))
const RAG_CONNECTOR_BY_ID = new Map(RAG_CONNECTOR_LAYOUT.map((item) => [item.id, item]))
const CONNECTOR_BY_ID = new Map([...CORE_CONNECTOR_LAYOUT, ...MEMORY_CONNECTOR_LAYOUT].map((item) => [item.id, item]))

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

function normalizeZoom(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return 1
  }
  return clamp(parsed, MIN_ZOOM, MAX_ZOOM)
}

function normalizeNodeType(value) {
  const type = String(value || '').trim().toLowerCase()
  return DEFAULT_NODE_TYPES.includes(type) ? type : 'task'
}

function nodeSupportsRoutingConfig(nodeType) {
  const normalized = normalizeNodeType(nodeType)
  return normalized !== 'start'
}

function normalizeFanInMode(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === FAN_IN_MODE_ANY) {
    return FAN_IN_MODE_ANY
  }
  if (normalized === FAN_IN_MODE_CUSTOM || normalized === 'custom_n' || normalized === 'custom-n') {
    return FAN_IN_MODE_CUSTOM
  }
  return FAN_IN_MODE_ALL
}

function normalizeDecisionNoMatchPolicy(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === DECISION_NO_MATCH_POLICY_FALLBACK) {
    return DECISION_NO_MATCH_POLICY_FALLBACK
  }
  if (normalized === DECISION_NO_MATCH_POLICY_FAIL) {
    return DECISION_NO_MATCH_POLICY_FAIL
  }
  return ''
}

function normalizeRagMode(value) {
  const mode = String(value || '').trim().toLowerCase()
  if (mode === 'index' || mode === 'fresh' || mode === 'indexing') {
    return RAG_MODE_FRESH_INDEX
  }
  if (mode === 'delta' || mode === 'delta_indexing') {
    return RAG_MODE_DELTA_INDEX
  }
  if (mode === RAG_MODE_QUERY || mode === RAG_MODE_FRESH_INDEX || mode === RAG_MODE_DELTA_INDEX) {
    return mode
  }
  return RAG_MODE_QUERY
}

function normalizeRagCollections(value) {
  if (!Array.isArray(value)) {
    return []
  }
  const seen = new Set()
  const normalized = []
  for (const item of value) {
    const collection = String(item || '').trim()
    if (!collection || seen.has(collection)) {
      continue
    }
    seen.add(collection)
    normalized.push(collection)
  }
  return normalized
}

function isRagEmbeddingProvider(provider) {
  return RAG_EMBEDDING_MODEL_PROVIDERS.has(String(provider || '').trim().toLowerCase())
}

function isEmbeddingModelOption(model) {
  if (model && model.is_embedding === true) {
    return isRagEmbeddingProvider(model?.provider)
  }
  if (!isRagEmbeddingProvider(model?.provider)) {
    return false
  }
  const modelName = String(model?.model_name || '').trim().toLowerCase()
  const name = String(model?.name || '').trim().toLowerCase()
  return modelName.includes('embed') || name.includes('embed')
}

function nodeSupportsRuntimeBindings(nodeType) {
  const normalized = normalizeNodeType(nodeType)
  return normalized !== 'start' && normalized !== 'end'
}

function nodeSupportsMcpServerBindings(nodeType) {
  const normalized = normalizeNodeType(nodeType)
  return nodeSupportsRuntimeBindings(normalized) && normalized !== 'rag'
}

function normalizeMcpServerIds(value) {
  if (!Array.isArray(value)) {
    return []
  }
  const seen = new Set()
  const normalized = []
  for (const item of value) {
    const serverId = parsePositiveInt(item)
    if (serverId == null || seen.has(serverId)) {
      continue
    }
    seen.add(serverId)
    normalized.push(serverId)
  }
  return normalized
}

function withRequiredMcpServer(value, requiredServerId) {
  const normalized = normalizeMcpServerIds(value)
  const requiredId = parsePositiveInt(requiredServerId)
  if (requiredId == null || normalized.includes(requiredId)) {
    return normalized
  }
  return [...normalized, requiredId]
}

function normalizeNodeMcpServerIds(nodeType, value, llmctlMcpServerId = null) {
  if (!nodeSupportsMcpServerBindings(nodeType)) {
    return []
  }
  return withRequiredMcpServer(value, llmctlMcpServerId)
}

function numberListEqual(left, right) {
  if (left.length !== right.length) {
    return false
  }
  return left.every((value, index) => value === right[index])
}

function titleForType(type) {
  const normalized = normalizeNodeType(type)
  return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function nodeDimensions(type) {
  const normalized = normalizeNodeType(type)
  return NODE_DIMENSIONS[normalized] || NODE_DIMENSIONS.default
}

function graphToWorldX(value) {
  return toNumber(value, 0) + WORLD_ORIGIN_X
}

function graphToWorldY(value) {
  return toNumber(value, 0) + WORLD_ORIGIN_Y
}

function worldToGraphX(value) {
  return toNumber(value, WORLD_ORIGIN_X) - WORLD_ORIGIN_X
}

function worldToGraphY(value) {
  return toNumber(value, WORLD_ORIGIN_Y) - WORLD_ORIGIN_Y
}

function clampEdgeControlPoint(point) {
  return {
    x: Number(clamp(toNumber(point?.x, 0), EDGE_POINT_MIN_X, EDGE_POINT_MAX_X).toFixed(2)),
    y: Number(clamp(toNumber(point?.y, 0), EDGE_POINT_MIN_Y, EDGE_POINT_MAX_Y).toFixed(2)),
  }
}

function normalizeEdgeControlPoints(value) {
  if (!Array.isArray(value)) {
    return []
  }
  const points = []
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue
    }
    points.push(clampEdgeControlPoint(item))
    if (points.length >= MAX_EDGE_CONTROL_POINTS) {
      break
    }
  }
  return points
}

function normalizeEdgeControlPointStyle(value) {
  const normalized = String(value || '').trim().toLowerCase()
  return normalized === EDGE_CONTROL_STYLE_CURVED
    ? EDGE_CONTROL_STYLE_CURVED
    : EDGE_CONTROL_STYLE_HARD
}

function clampNodePosition(nodeType, x, y) {
  const dimensions = nodeDimensions(nodeType)
  const minX = -WORLD_ORIGIN_X + WORLD_PADDING
  const minY = -WORLD_ORIGIN_Y + WORLD_PADDING
  const maxX = WORLD_ORIGIN_X - WORLD_PADDING - dimensions.width
  const maxY = WORLD_ORIGIN_Y - WORLD_PADDING - dimensions.height
  return {
    x: clamp(toNumber(x, 0), minX, maxX),
    y: clamp(toNumber(y, 0), minY, maxY),
  }
}

function centeredNodePosition(nodeType) {
  const dimensions = nodeDimensions(nodeType)
  return clampNodePosition(nodeType, -dimensions.width / 2, -dimensions.height / 2)
}

function connectorLayoutForNodeType(nodeType) {
  const normalizedType = normalizeNodeType(nodeType)
  if (normalizedType === 'start' || normalizedType === 'flowchart') {
    return START_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'end') {
    return END_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'task' || normalizedType === 'plan') {
    return CORE_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'rag') {
    return RAG_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'milestone') {
    return MILESTONE_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'memory') {
    return MEMORY_CONNECTOR_LAYOUT
  }
  if (normalizedType === 'decision') {
    return DECISION_CONNECTOR_LAYOUT
  }
  return DEFAULT_CONNECTOR_LAYOUT
}

function defaultSourceHandleId(source, target) {
  const sourceDimensions = nodeDimensions(source.node_type)
  const targetDimensions = nodeDimensions(target.node_type)
  const deltaX = (toNumber(target.x, 0) + targetDimensions.width / 2) - (toNumber(source.x, 0) + sourceDimensions.width / 2)
  const deltaY = (toNumber(target.y, 0) + targetDimensions.height / 2) - (toNumber(source.y, 0) + sourceDimensions.height / 2)
  if (Math.abs(deltaX) >= Math.abs(deltaY)) {
    return deltaX >= 0 ? 'r1' : 'l1'
  }
  return deltaY >= 0 ? 'b2' : 't2'
}

function defaultTargetHandleId(source, target) {
  const sourceDimensions = nodeDimensions(source.node_type)
  const targetDimensions = nodeDimensions(target.node_type)
  const deltaX = (toNumber(target.x, 0) + targetDimensions.width / 2) - (toNumber(source.x, 0) + sourceDimensions.width / 2)
  const deltaY = (toNumber(target.y, 0) + targetDimensions.height / 2) - (toNumber(source.y, 0) + sourceDimensions.height / 2)
  if (Math.abs(deltaX) >= Math.abs(deltaY)) {
    return deltaX >= 0 ? 'l1' : 'r1'
  }
  return deltaY >= 0 ? 't2' : 'b2'
}

function resolveStartHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (normalized.startsWith('t')) {
    return 't2'
  }
  if (normalized.startsWith('b')) {
    return 'b2'
  }
  if (normalized === 'left' || normalized === 'l1') {
    return 'l1'
  }
  if (normalized === 'right' || normalized === 'r1') {
    return 'r1'
  }
  return null
}

function resolveEndHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (END_CONNECTOR_BY_ID.has(normalized)) {
    return normalized
  }
  if (normalized.startsWith('t')) {
    return 't1'
  }
  if (normalized.startsWith('b')) {
    return 'b3'
  }
  if (normalized === 'left' || normalized.startsWith('l')) {
    return 'l2'
  }
  if (normalized === 'right' || normalized.startsWith('r')) {
    return 'r2'
  }
  return null
}

function resolveTaskHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (normalized === 'top') {
    return 't2'
  }
  if (normalized === 'right') {
    return 'r1'
  }
  if (normalized === 'bottom') {
    return 'b2'
  }
  if (normalized === 'left') {
    return 'l1'
  }
  return CORE_CONNECTOR_BY_ID.has(normalized) ? normalized : null
}

function resolveMilestoneHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (MILESTONE_CONNECTOR_BY_ID.has(normalized)) {
    return normalized
  }
  if (normalized.startsWith('t')) {
    return 't2'
  }
  if (normalized.startsWith('b')) {
    return 'b2'
  }
  if (normalized === 'left' || normalized.startsWith('l')) {
    return 'l1'
  }
  if (normalized === 'right' || normalized.startsWith('r')) {
    return 'r1'
  }
  return null
}

function resolveDecisionHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (DECISION_CONNECTOR_BY_ID.has(normalized)) {
    return normalized
  }
  if (normalized.startsWith('t')) {
    return 't2'
  }
  if (normalized.startsWith('b')) {
    return 'b2'
  }
  if (normalized === 'left' || normalized.startsWith('l')) {
    return 'l1'
  }
  if (normalized === 'right' || normalized.startsWith('r')) {
    return 'r1'
  }
  return null
}

function resolveMemoryHandleId(handleId) {
  const normalized = String(handleId || '').trim().toLowerCase()
  if (!normalized) {
    return null
  }
  if (/^m[1-8]$/.test(normalized)) {
    return normalized
  }
  if (normalized.startsWith('t')) {
    return 'm2'
  }
  if (normalized.startsWith('b')) {
    return 'm7'
  }
  if (normalized === 'left' || normalized.startsWith('l')) {
    return 'm4'
  }
  if (normalized === 'right' || normalized.startsWith('r')) {
    return 'm5'
  }
  return null
}

function normalizeHandleIdForNode(nodeType, handleId) {
  const normalizedType = normalizeNodeType(nodeType)
  if (normalizedType === 'start' || normalizedType === 'flowchart') {
    return resolveStartHandleId(handleId)
  }
  if (normalizedType === 'end') {
    return resolveEndHandleId(handleId)
  }
  if (normalizedType === 'milestone') {
    return resolveMilestoneHandleId(handleId)
  }
  if (normalizedType === 'memory') {
    return resolveMemoryHandleId(handleId)
  }
  if (normalizedType === 'decision') {
    return resolveDecisionHandleId(handleId)
  }
  return resolveTaskHandleId(handleId)
}

function connectorPosition(node, handleId) {
  const dimensions = nodeDimensions(node.node_type)
  const normalizedType = normalizeNodeType(node.node_type)
  let normalizedHandleId = normalizeHandleIdForNode(normalizedType, handleId)
  if (!normalizedHandleId) {
    normalizedHandleId = normalizedType === 'memory' ? 'm5' : 'r1'
  }
  const point = (normalizedType === 'rag' ? RAG_CONNECTOR_BY_ID.get(normalizedHandleId) : null)
    || CONNECTOR_BY_ID.get(normalizedHandleId)
    || END_CONNECTOR_BY_ID.get(normalizedHandleId)
    || MILESTONE_CONNECTOR_BY_ID.get(normalizedHandleId)
    || DECISION_CONNECTOR_BY_ID.get(normalizedHandleId)
    || (normalizedType === 'rag' ? RAG_CONNECTOR_BY_ID.get('r1') : null)
    || CONNECTOR_BY_ID.get(normalizedType === 'memory' ? 'm5' : 'r1')
  return {
    x: graphToWorldX(toNumber(node.x, 0) + dimensions.width * (point?.x ?? 100) / 100),
    y: graphToWorldY(toNumber(node.y, 0) + dimensions.height * (point?.y ?? 50) / 100),
    side: point?.side || 'right',
    handleId: normalizedHandleId,
  }
}

function sideVector(side) {
  if (side === 'left') {
    return { x: -1, y: 0 }
  }
  if (side === 'right') {
    return { x: 1, y: 0 }
  }
  if (side === 'oct-top-right') {
    return { x: 0.3826834323650898, y: -0.9238795325112867 }
  }
  if (side === 'oct-right-top') {
    return { x: 0.9238795325112867, y: -0.3826834323650898 }
  }
  if (side === 'oct-right-bottom') {
    return { x: 0.9238795325112867, y: 0.3826834323650898 }
  }
  if (side === 'oct-bottom-right') {
    return { x: 0.3826834323650898, y: 0.9238795325112867 }
  }
  if (side === 'oct-bottom-left') {
    return { x: -0.3826834323650898, y: 0.9238795325112867 }
  }
  if (side === 'oct-left-bottom') {
    return { x: -0.9238795325112867, y: 0.3826834323650898 }
  }
  if (side === 'oct-left-top') {
    return { x: -0.9238795325112867, y: -0.3826834323650898 }
  }
  if (side === 'oct-top-left') {
    return { x: -0.3826834323650898, y: -0.9238795325112867 }
  }
  if (side === 'decision-top-right') {
    return { x: Math.SQRT1_2, y: -Math.SQRT1_2 }
  }
  if (side === 'decision-bottom-right') {
    return { x: Math.SQRT1_2, y: Math.SQRT1_2 }
  }
  if (side === 'decision-bottom-left') {
    return { x: -Math.SQRT1_2, y: Math.SQRT1_2 }
  }
  if (side === 'decision-top-left') {
    return { x: -Math.SQRT1_2, y: -Math.SQRT1_2 }
  }
  if (side === 'top') {
    return { x: 0, y: -1 }
  }
  return { x: 0, y: 1 }
}

function pointToSegmentDistance(point, start, end) {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const lengthSquared = dx * dx + dy * dy
  if (lengthSquared <= 0.0001) {
    return Math.hypot(point.x - start.x, point.y - start.y)
  }
  const t = clamp(
    ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared,
    0,
    1,
  )
  const projectedX = start.x + dx * t
  const projectedY = start.y + dy * t
  return Math.hypot(point.x - projectedX, point.y - projectedY)
}

function controlPointInsertIndex(start, end, controlPoints, point) {
  const worldControlPoints = Array.isArray(controlPoints) ? controlPoints : []
  const route = [start, ...worldControlPoints, end]
  if (route.length < 2) {
    return 0
  }
  let bestSegmentIndex = 0
  let bestDistance = Number.POSITIVE_INFINITY
  for (let segmentIndex = 0; segmentIndex < route.length - 1; segmentIndex += 1) {
    const distance = pointToSegmentDistance(point, route[segmentIndex], route[segmentIndex + 1])
    if (distance < bestDistance) {
      bestDistance = distance
      bestSegmentIndex = segmentIndex
    }
  }
  return clamp(bestSegmentIndex, 0, worldControlPoints.length)
}

function polylinePathMeta(points) {
  const route = Array.isArray(points) ? points : []
  if (route.length < 2) {
    const fallback = route[0] || { x: 0, y: 0 }
    return {
      d: `M ${fallback.x} ${fallback.y}`,
      labelX: fallback.x,
      labelY: fallback.y,
    }
  }
  let d = `M ${route[0].x} ${route[0].y}`
  let totalLength = 0
  const segments = []
  for (let index = 0; index < route.length - 1; index += 1) {
    const segmentStart = route[index]
    const segmentEnd = route[index + 1]
    d += ` L ${segmentEnd.x} ${segmentEnd.y}`
    const dx = segmentEnd.x - segmentStart.x
    const dy = segmentEnd.y - segmentStart.y
    const length = Math.hypot(dx, dy)
    segments.push({ segmentStart, segmentEnd, dx, dy, length })
    totalLength += length
  }
  if (totalLength <= 0.001) {
    return {
      d,
      labelX: route[0].x,
      labelY: route[0].y - 10,
    }
  }
  const midpointOffset = totalLength / 2
  let traversed = 0
  let labelBaseX = route[0].x
  let labelBaseY = route[0].y
  let normalX = 0
  let normalY = -1
  for (const segment of segments) {
    if (segment.length <= 0.001) {
      continue
    }
    if (traversed + segment.length >= midpointOffset) {
      const localOffset = midpointOffset - traversed
      const t = localOffset / segment.length
      labelBaseX = segment.segmentStart.x + segment.dx * t
      labelBaseY = segment.segmentStart.y + segment.dy * t
      normalX = -segment.dy / segment.length
      normalY = segment.dx / segment.length
      break
    }
    traversed += segment.length
  }
  return {
    d,
    labelX: labelBaseX + normalX * 10,
    labelY: labelBaseY + normalY * 10,
  }
}

function curvedPathMeta(points) {
  const route = Array.isArray(points) ? points : []
  if (route.length < 2) {
    return polylinePathMeta(route)
  }
  let d = `M ${route[0].x} ${route[0].y}`
  for (let index = 0; index < route.length - 1; index += 1) {
    const point0 = index > 0 ? route[index - 1] : route[index]
    const point1 = route[index]
    const point2 = route[index + 1]
    const point3 = (index + 2) < route.length ? route[index + 2] : route[index + 1]
    const c1x = point1.x + (point2.x - point0.x) / 6
    const c1y = point1.y + (point2.y - point0.y) / 6
    const c2x = point2.x - (point3.x - point1.x) / 6
    const c2y = point2.y - (point3.y - point1.y) / 6
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${point2.x} ${point2.y}`
  }
  const labelMeta = polylinePathMeta(route)
  return {
    d,
    labelX: labelMeta.labelX,
    labelY: labelMeta.labelY,
  }
}

function edgePath(start, end, controlPoints = [], controlPointStyle = EDGE_CONTROL_STYLE_HARD) {
  if (Array.isArray(controlPoints) && controlPoints.length > 0) {
    const route = [start, ...controlPoints, end]
    if (normalizeEdgeControlPointStyle(controlPointStyle) === EDGE_CONTROL_STYLE_CURVED) {
      return curvedPathMeta(route)
    }
    return polylinePathMeta(route)
  }
  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const bend = Math.max(44, Math.min(220, distance * 0.42))
  const sourceVector = sideVector(start.side)
  const targetVector = sideVector(end.side)
  const c1x = start.x + sourceVector.x * bend
  const c1y = start.y + sourceVector.y * bend
  const c2x = end.x + targetVector.x * bend
  const c2y = end.y + targetVector.y * bend
  const t = 0.5
  const oneMinusT = 1 - t
  const labelBaseX = (
    oneMinusT * oneMinusT * oneMinusT * start.x
    + 3 * oneMinusT * oneMinusT * t * c1x
    + 3 * oneMinusT * t * t * c2x
    + t * t * t * end.x
  )
  const labelBaseY = (
    oneMinusT * oneMinusT * oneMinusT * start.y
    + 3 * oneMinusT * oneMinusT * t * c1y
    + 3 * oneMinusT * t * t * c2y
    + t * t * t * end.y
  )
  const tangentX = (
    3 * oneMinusT * oneMinusT * (c1x - start.x)
    + 6 * oneMinusT * t * (c2x - c1x)
    + 3 * t * t * (end.x - c2x)
  )
  const tangentY = (
    3 * oneMinusT * oneMinusT * (c1y - start.y)
    + 6 * oneMinusT * t * (c2y - c1y)
    + 3 * t * t * (end.y - c2y)
  )
  const tangentLength = Math.hypot(tangentX, tangentY) || 1
  const normalX = -tangentY / tangentLength
  const normalY = tangentX / tangentLength
  const labelOffset = 10
  return {
    d: `M ${start.x} ${start.y} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${end.x} ${end.y}`,
    labelX: labelBaseX + normalX * labelOffset,
    labelY: labelBaseY + normalY * labelOffset,
  }
}

function pointerSideForDraft(sourcePoint, pointer) {
  const deltaX = pointer.x - sourcePoint.x
  const deltaY = pointer.y - sourcePoint.y
  if (Math.abs(deltaX) >= Math.abs(deltaY)) {
    return deltaX >= 0 ? 'left' : 'right'
  }
  return deltaY >= 0 ? 'top' : 'bottom'
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
  if (normalized === 'plan') {
    return {
      action: PLAN_ACTION_CREATE_OR_UPDATE,
      additive_prompt: '',
      retention_mode: 'ttl',
      retention_ttl_seconds: DEFAULT_PLAN_RETENTION_TTL_SECONDS,
      retention_max_count: DEFAULT_PLAN_RETENTION_MAX_COUNT,
      plan_item_id: null,
      stage_key: '',
      task_key: '',
      completion_source_path: '',
    }
  }
  if (normalized === 'milestone') {
    return {
      action: 'create_or_update',
      additive_prompt: '',
      retention_mode: 'ttl',
      retention_ttl_seconds: DEFAULT_MILESTONE_RETENTION_TTL_SECONDS,
      retention_max_count: DEFAULT_MILESTONE_RETENTION_MAX_COUNT,
    }
  }
  if (normalized === 'memory') {
    return {
      action: 'add',
      additive_prompt: '',
      retention_mode: 'ttl',
      retention_ttl_seconds: DEFAULT_MILESTONE_RETENTION_TTL_SECONDS,
      retention_max_count: DEFAULT_MILESTONE_RETENTION_MAX_COUNT,
    }
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

function normalizeMilestoneAction(value) {
  const action = String(value || '').trim().toLowerCase()
  return action === 'mark_complete' || action === 'complete'
    ? 'mark_complete'
    : 'create_or_update'
}

function normalizePlanAction(value) {
  const action = String(value || '').trim().toLowerCase()
  if ([
    'complete_plan_item',
    'complete plan item',
    'mark_plan_item_complete',
    'mark_task_complete',
  ].includes(action)) {
    return PLAN_ACTION_COMPLETE_PLAN_ITEM
  }
  return PLAN_ACTION_CREATE_OR_UPDATE
}

function normalizeMemoryAction(value) {
  const action = String(value || '').trim().toLowerCase()
  if (['retrieve', 'fetch', 'read', 'query', 'search', 'list'].includes(action)) {
    return 'retrieve'
  }
  return 'add'
}

const SPECIALIZED_NODE_CONTROL_REGISTRY = {
  milestone: {
    actionOptions: MILESTONE_ACTION_OPTIONS,
    normalizeAction: normalizeMilestoneAction,
    lockLlmctlMcp: false,
    showPlanCompletionTargetFields: false,
  },
  memory: {
    actionOptions: MEMORY_ACTION_OPTIONS,
    normalizeAction: normalizeMemoryAction,
    lockLlmctlMcp: false,
    showPlanCompletionTargetFields: false,
  },
  plan: {
    actionOptions: PLAN_ACTION_OPTIONS,
    normalizeAction: normalizePlanAction,
    lockLlmctlMcp: false,
    showPlanCompletionTargetFields: true,
  },
}

function normalizeMilestoneRetentionMode(value) {
  const mode = String(value || '').trim().toLowerCase()
  if (mode === 'forever' || mode === 'none') {
    return 'forever'
  }
  if (mode === 'max_count' || mode === 'max') {
    return 'max_count'
  }
  if (mode === 'ttl_max_count' || mode === 'ttl_max' || mode === 'ttl+max') {
    return 'ttl_max_count'
  }
  return 'ttl'
}

function retentionModeUsesTtl(mode) {
  const normalized = normalizeMilestoneRetentionMode(mode)
  return normalized === 'ttl' || normalized === 'ttl_max_count'
}

function retentionModeUsesMaxCount(mode) {
  const normalized = normalizeMilestoneRetentionMode(mode)
  return normalized === 'max_count' || normalized === 'ttl_max_count'
}

function normalizeNodeConfig(config, nodeType = '') {
  const normalizedType = normalizeNodeType(nodeType)
  const nextConfig = config && typeof config === 'object' ? { ...config } : {}
  if (nodeSupportsRoutingConfig(normalizedType)) {
    const fanInMode = normalizeFanInMode(nextConfig.fan_in_mode)
    if (fanInMode === FAN_IN_MODE_ALL) {
      delete nextConfig.fan_in_mode
      delete nextConfig.fan_in_custom_count
    } else if (fanInMode === FAN_IN_MODE_ANY) {
      nextConfig.fan_in_mode = FAN_IN_MODE_ANY
      delete nextConfig.fan_in_custom_count
    } else {
      nextConfig.fan_in_mode = FAN_IN_MODE_CUSTOM
      const fanInCustomCount = parsePositiveInt(nextConfig.fan_in_custom_count)
      if (fanInCustomCount == null) {
        delete nextConfig.fan_in_custom_count
      } else {
        nextConfig.fan_in_custom_count = fanInCustomCount
      }
    }
  } else {
    delete nextConfig.fan_in_mode
    delete nextConfig.fan_in_custom_count
  }
  if (normalizedType === 'decision') {
    const noMatchPolicy = normalizeDecisionNoMatchPolicy(nextConfig.no_match_policy)
    if (noMatchPolicy) {
      nextConfig.no_match_policy = noMatchPolicy
    } else {
      delete nextConfig.no_match_policy
    }
    const fallbackConditionKey = String(nextConfig.fallback_condition_key || '').trim()
    if (fallbackConditionKey) {
      nextConfig.fallback_condition_key = fallbackConditionKey
    } else {
      delete nextConfig.fallback_condition_key
    }
  } else {
    delete nextConfig.no_match_policy
    delete nextConfig.fallback_condition_key
  }
  if (normalizedType === 'plan') {
    nextConfig.action = normalizePlanAction(nextConfig.action)
    nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
    nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
    nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_PLAN_RETENTION_TTL_SECONDS
    nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_PLAN_RETENTION_MAX_COUNT
    const planItemId = parsePositiveInt(nextConfig.plan_item_id)
    if (planItemId == null) {
      delete nextConfig.plan_item_id
    } else {
      nextConfig.plan_item_id = planItemId
    }
    nextConfig.stage_key = String(nextConfig.stage_key || '').trim()
    nextConfig.task_key = String(nextConfig.task_key || '').trim()
    nextConfig.completion_source_path = String(nextConfig.completion_source_path || '').trim()
  }
  if (normalizedType === 'milestone') {
    nextConfig.action = normalizeMilestoneAction(nextConfig.action)
    nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
    nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
    nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_MILESTONE_RETENTION_TTL_SECONDS
    nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_MILESTONE_RETENTION_MAX_COUNT
  }
  if (normalizedType === 'memory') {
    nextConfig.action = normalizeMemoryAction(nextConfig.action)
    nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
    nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
    nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_MILESTONE_RETENTION_TTL_SECONDS
    nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_MILESTONE_RETENTION_MAX_COUNT
  }
  if (normalizedType === 'rag') {
    nextConfig.mode = normalizeRagMode(nextConfig.mode)
    nextConfig.collections = normalizeRagCollections(nextConfig.collections)
    nextConfig.question_prompt = String(nextConfig.question_prompt || '')
  }
  if (!nodeSupportsRuntimeBindings(normalizedType)) {
    delete nextConfig.agent_id
    return nextConfig
  }
  const agentId = parsePositiveInt(nextConfig.agent_id)
  if (agentId == null) {
    delete nextConfig.agent_id
  } else {
    nextConfig.agent_id = agentId
  }
  return nextConfig
}

function normalizeDecisionConditions(value) {
  if (!Array.isArray(value)) {
    return []
  }
  const seen = new Set()
  const normalized = []
  for (const item of value) {
    if (!item || typeof item !== 'object') {
      continue
    }
    const connectorId = String(item.connector_id || '').trim()
    if (!connectorId || seen.has(connectorId)) {
      continue
    }
    seen.add(connectorId)
    normalized.push({
      connector_id: connectorId,
      condition_text: String(item.condition_text || '').trim(),
    })
  }
  return normalized
}

function validateRoutingConfig({
  nodeType,
  config,
  solidIncomingConnectorCount,
  decisionSolidOutgoingConnectorIds,
}) {
  const nextConfig = config && typeof config === 'object' ? config : {}
  const errors = []
  const fieldErrors = {}
  const fanInMode = normalizeFanInMode(nextConfig.fan_in_mode)
  const fanInCustomCount = parsePositiveInt(nextConfig.fan_in_custom_count)
  if (fanInMode === FAN_IN_MODE_CUSTOM) {
    if (fanInCustomCount == null) {
      fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT] = 'Custom N is required when fan-in mode is custom.'
      errors.push(fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT])
    } else if (solidIncomingConnectorCount === 0) {
      fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT] = 'Custom N requires at least one solid incoming connector.'
      errors.push(fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT])
    } else if (fanInCustomCount > solidIncomingConnectorCount) {
      fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT] = `Custom N must be <= solid incoming connector count (${solidIncomingConnectorCount}).`
      errors.push(fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT])
    }
  }

  const normalizedType = normalizeNodeType(nodeType)
  if (normalizedType === 'decision') {
    const noMatchPolicy = normalizeDecisionNoMatchPolicy(nextConfig.no_match_policy)
    const fallbackConditionKey = String(nextConfig.fallback_condition_key || '').trim()
    const connectorIds = decisionSolidOutgoingConnectorIds || new Set()
    if (noMatchPolicy === DECISION_NO_MATCH_POLICY_FALLBACK && !fallbackConditionKey) {
      fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR] = 'Fallback policy requires selecting a fallback connector.'
      errors.push(fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR])
    }
    if (fallbackConditionKey && !connectorIds.has(fallbackConditionKey)) {
      fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR] = 'Fallback connector must match a solid outgoing connector.'
      errors.push(fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR])
    }
  }

  const firstInvalidField = (
    fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT]
      ? ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT
      : (
        fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR]
          ? ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR
          : (
            fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_MODE]
              ? ROUTING_FOCUS_FIELD_FAN_IN_MODE
              : ''
          )
      )
  )

  return {
    hasErrors: errors.length > 0,
    errors,
    fieldErrors,
    firstInvalidField,
  }
}

function decisionConditionsEqual(left, right) {
  if (left.length !== right.length) {
    return false
  }
  return left.every((entry, index) => (
    entry.connector_id === right[index]?.connector_id
    && entry.condition_text === right[index]?.condition_text
  ))
}

function syncDecisionNodeConditions(nodes, edges) {
  if (!Array.isArray(nodes) || !Array.isArray(edges)) {
    return { nodes, edges, changed: false }
  }

  const nodeTypeByToken = new Map(nodes.map((node) => [node.token, normalizeNodeType(node.node_type)]))
  const connectorIdsByNodeToken = new Map()
  const usedConnectorIdsByNodeToken = new Map()
  const nextConnectorIndexByNodeToken = new Map()
  let changed = false

  function nextConnectorId(nodeToken) {
    const used = usedConnectorIdsByNodeToken.get(nodeToken) || new Set()
    usedConnectorIdsByNodeToken.set(nodeToken, used)
    let nextIndex = nextConnectorIndexByNodeToken.get(nodeToken) || 1
    while (used.has(`connector_${nextIndex}`)) {
      nextIndex += 1
    }
    const connectorId = `connector_${nextIndex}`
    used.add(connectorId)
    nextConnectorIndexByNodeToken.set(nodeToken, nextIndex + 1)
    return connectorId
  }

  const nextEdges = edges.map((edge) => {
    const sourceNodeType = nodeTypeByToken.get(edge.sourceToken) || 'task'
    if (sourceNodeType !== 'decision' || normalizeEdgeMode(edge.edge_mode) !== 'solid') {
      return edge
    }
    const used = usedConnectorIdsByNodeToken.get(edge.sourceToken) || new Set()
    usedConnectorIdsByNodeToken.set(edge.sourceToken, used)
    let connectorId = String(edge.condition_key || '').trim()
    if (!connectorId || used.has(connectorId)) {
      connectorId = nextConnectorId(edge.sourceToken)
    } else {
      used.add(connectorId)
    }
    const nodeConnectorIds = connectorIdsByNodeToken.get(edge.sourceToken) || []
    nodeConnectorIds.push(connectorId)
    connectorIdsByNodeToken.set(edge.sourceToken, nodeConnectorIds)
    if (connectorId === String(edge.condition_key || '').trim()) {
      return edge
    }
    changed = true
    return {
      ...edge,
      condition_key: connectorId,
    }
  })

  const nextNodes = nodes.map((node) => {
    const nodeType = normalizeNodeType(node.node_type)
    const currentConfig = node.config && typeof node.config === 'object' ? node.config : {}
    if (nodeType !== 'decision') {
      if (!Object.prototype.hasOwnProperty.call(currentConfig, 'decision_conditions')) {
        return node
      }
      const nextConfig = { ...currentConfig }
      delete nextConfig.decision_conditions
      changed = true
      return {
        ...node,
        config: nextConfig,
      }
    }
    const connectorIds = connectorIdsByNodeToken.get(node.token) || []
    const existingConditions = normalizeDecisionConditions(currentConfig.decision_conditions)
    const conditionTextByConnector = new Map(
      existingConditions.map((entry) => [entry.connector_id, entry.condition_text]),
    )
    const nextConditions = connectorIds.map((connectorId) => ({
      connector_id: connectorId,
      condition_text: conditionTextByConnector.get(connectorId) || '',
    }))
    if (decisionConditionsEqual(existingConditions, nextConditions)) {
      return node
    }
    changed = true
    return {
      ...node,
      config: {
        ...currentConfig,
        decision_conditions: nextConditions,
      },
    }
  })

  if (!changed) {
    return { nodes, edges, changed: false }
  }
  return { nodes: nextNodes, edges: nextEdges, changed: true }
}

function hasTaskPrompt(config) {
  if (!config || typeof config !== 'object') {
    return false
  }
  const prompt = config.task_prompt
  return typeof prompt === 'string' && Boolean(prompt.trim())
}

function refLabel(item) {
  if (!item || typeof item !== 'object') {
    return '-'
  }
  return String(item.name || item.title || item.id)
}

function normalizeEdgeMode(value) {
  const mode = String(value || '').trim().toLowerCase()
  return EDGE_MODE_OPTIONS.includes(mode) ? mode : 'solid'
}

function buildNodePayload(node, llmctlMcpServerId = null) {
  const nodeType = normalizeNodeType(node.node_type)
  const mcpServerIds = normalizeNodeMcpServerIds(nodeType, node.mcp_server_ids, llmctlMcpServerId)
  const payload = {
    id: node.persistedId || null,
    node_type: nodeType,
    title: String(node.title || '').trim() || null,
    ref_id: NODE_TYPE_WITH_REF.has(nodeType)
      ? (node.ref_id == null ? null : parseOptionalInt(node.ref_id))
      : null,
    x: Number(toNumber(node.x, 0).toFixed(2)),
    y: Number(toNumber(node.y, 0).toFixed(2)),
    config: normalizeNodeConfig(node.config, nodeType),
    model_id: node.model_id == null ? null : parseOptionalInt(node.model_id),
    mcp_server_ids: mcpServerIds,
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
    control_points: normalizeEdgeControlPoints(edge.controlPoints),
    control_point_style: normalizeEdgeControlPointStyle(edge.controlPointStyle),
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
      ref_id: NODE_TYPE_WITH_REF.has(nodeType) ? parseOptionalInt(raw?.ref_id) : null,
      x: toNumber(raw?.x, 0),
      y: toNumber(raw?.y, 0),
      config: normalizeNodeConfig(
        raw?.config && typeof raw.config === 'object'
          ? { ...raw.config }
          : defaultConfigForType(nodeType),
        nodeType,
      ),
      model_id: parseOptionalInt(raw?.model_id),
      mcp_server_ids: normalizeNodeMcpServerIds(nodeType, raw?.mcp_server_ids),
      script_ids: Array.isArray(raw?.script_ids) ? raw.script_ids.filter((value) => parsePositiveInt(value) != null) : [],
      attachment_ids: Array.isArray(raw?.attachment_ids) ? raw.attachment_ids.filter((value) => parsePositiveInt(value) != null) : [],
    }
    normalizedNodes.push(node)
    tokenLookup.set(String(raw?.id), token)
    tokenLookup.set(`id:${raw?.id}`, token)
    tokenLookup.set(String(clientId), token)
    tokenLookup.set(`client:${clientId}`, token)
  }

  const firstStartNode = normalizedNodes.find((node) => normalizeNodeType(node.node_type) === 'start') || null
  if (!firstStartNode) {
    const clientId = Math.max(maxClientNodeId + 1, 1)
    maxClientNodeId = clientId
    const centered = centeredNodePosition('start')
    const startNode = {
      token: makeNodeToken(null, clientId),
      persistedId: null,
      clientId,
      node_type: 'start',
      title: 'Start',
      ref_id: null,
      x: centered.x,
      y: centered.y,
      config: normalizeNodeConfig(defaultConfigForType('start'), 'start'),
      model_id: null,
      mcp_server_ids: [],
      script_ids: [],
      attachment_ids: [],
    }
    normalizedNodes.unshift(startNode)
    tokenLookup.set(String(clientId), startNode.token)
    tokenLookup.set(`client:${clientId}`, startNode.token)
  } else if (
    normalizedNodes.length === 1 &&
    Math.abs(toNumber(firstStartNode.x, 0)) < 0.001 &&
    Math.abs(toNumber(firstStartNode.y, 0)) < 0.001
  ) {
    const centered = centeredNodePosition('start')
    firstStartNode.x = centered.x
    firstStartNode.y = centered.y
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
      sourceHandleId: String(raw?.source_handle_id || '').trim() || 'r1',
      targetHandleId: String(raw?.target_handle_id || '').trim() || 'l1',
      edge_mode: normalizeEdgeMode(raw?.edge_mode),
      condition_key: String(raw?.condition_key || '').trim(),
      label: String(raw?.label || '').trim(),
      controlPoints: normalizeEdgeControlPoints(raw?.control_points),
      controlPointStyle: normalizeEdgeControlPointStyle(raw?.control_point_style),
    })
  }

  const synchronized = syncDecisionNodeConditions(normalizedNodes, normalizedEdges)
  return {
    nodes: synchronized.nodes,
    edges: synchronized.edges,
    nextClientNodeId: Math.max(maxClientNodeId + 1, 1),
    nextClientEdgeId: Math.max(maxClientEdgeId + 1, 1),
  }
}

function buildNodeSelectionSnapshot(node) {
  if (!node || typeof node !== 'object') {
    return null
  }
  return {
    persistedId: parsePositiveInt(node.persistedId),
    clientId: parsePositiveInt(node.clientId),
    nodeType: normalizeNodeType(node.node_type),
    title: String(node.title || '').trim(),
    x: toNumber(node.x, 0),
    y: toNumber(node.y, 0),
  }
}

function resolveNodeTokenFromSnapshot(nodes, snapshot) {
  if (!Array.isArray(nodes) || !snapshot || typeof snapshot !== 'object') {
    return ''
  }
  if (snapshot.persistedId) {
    const byId = nodes.find((node) => node.persistedId === snapshot.persistedId)
    if (byId) {
      return byId.token
    }
  }
  if (snapshot.clientId) {
    const byClientId = nodes.find((node) => node.clientId === snapshot.clientId)
    if (byClientId) {
      return byClientId.token
    }
  }
  const nextType = normalizeNodeType(snapshot.nodeType)
  const nextTitle = String(snapshot.title || '').trim()
  const nextX = toNumber(snapshot.x, 0)
  const nextY = toNumber(snapshot.y, 0)
  const byPositionAndTitle = nodes.find((node) => (
    normalizeNodeType(node.node_type) === nextType
    && Math.abs(toNumber(node.x, 0) - nextX) < 0.01
    && Math.abs(toNumber(node.y, 0) - nextY) < 0.01
    && String(node.title || '').trim() === nextTitle
  ))
  if (byPositionAndTitle) {
    return byPositionAndTitle.token
  }
  const byPosition = nodes.find((node) => (
    normalizeNodeType(node.node_type) === nextType
    && Math.abs(toNumber(node.x, 0) - nextX) < 0.01
    && Math.abs(toNumber(node.y, 0) - nextY) < 0.01
  ))
  return byPosition ? byPosition.token : ''
}

function buildEdgeSelectionSnapshot(edge, nodesByToken) {
  if (!edge || typeof edge !== 'object' || !nodesByToken) {
    return null
  }
  const sourceNode = nodesByToken.get(edge.sourceToken)
  const targetNode = nodesByToken.get(edge.targetToken)
  if (!sourceNode || !targetNode) {
    return null
  }
  return {
    persistedId: parsePositiveInt(edge.persistedId),
    sourcePersistedId: parsePositiveInt(sourceNode.persistedId),
    sourceClientId: parsePositiveInt(sourceNode.clientId),
    targetPersistedId: parsePositiveInt(targetNode.persistedId),
    targetClientId: parsePositiveInt(targetNode.clientId),
    sourceHandleId: String(edge.sourceHandleId || ''),
    targetHandleId: String(edge.targetHandleId || ''),
    edgeMode: normalizeEdgeMode(edge.edge_mode),
    conditionKey: String(edge.condition_key || ''),
    label: String(edge.label || ''),
    controlPoints: normalizeEdgeControlPoints(edge.controlPoints),
    controlPointStyle: normalizeEdgeControlPointStyle(edge.controlPointStyle),
  }
}

function matchesEdgeNode(node, persistedId, clientId) {
  if (!node || typeof node !== 'object') {
    return false
  }
  if (persistedId && node.persistedId === persistedId) {
    return true
  }
  if (clientId && node.clientId === clientId) {
    return true
  }
  return false
}

function resolveEdgeIdFromSnapshot(edges, nodesByToken, snapshot) {
  if (!Array.isArray(edges) || !nodesByToken || !snapshot || typeof snapshot !== 'object') {
    return ''
  }
  if (snapshot.persistedId) {
    const byId = edges.find((edge) => edge.persistedId === snapshot.persistedId)
    if (byId) {
      return byId.localId
    }
  }
  const byShape = edges.find((edge) => {
    const sourceNode = nodesByToken.get(edge.sourceToken)
    const targetNode = nodesByToken.get(edge.targetToken)
    if (!sourceNode || !targetNode) {
      return false
    }
    return (
      matchesEdgeNode(sourceNode, snapshot.sourcePersistedId, snapshot.sourceClientId)
      && matchesEdgeNode(targetNode, snapshot.targetPersistedId, snapshot.targetClientId)
      && String(edge.sourceHandleId || '') === snapshot.sourceHandleId
      && String(edge.targetHandleId || '') === snapshot.targetHandleId
      && normalizeEdgeMode(edge.edge_mode) === snapshot.edgeMode
      && String(edge.condition_key || '') === snapshot.conditionKey
      && String(edge.label || '') === snapshot.label
      && JSON.stringify(normalizeEdgeControlPoints(edge.controlPoints)) === JSON.stringify(snapshot.controlPoints || [])
      && normalizeEdgeControlPointStyle(edge.controlPointStyle) === normalizeEdgeControlPointStyle(snapshot.controlPointStyle)
    )
  })
  return byShape ? byShape.localId : ''
}

const FlowchartWorkspaceEditor = forwardRef(function FlowchartWorkspaceEditor({
  initialNodes = [],
  initialEdges = [],
  catalog = null,
  nodeTypes = DEFAULT_NODE_TYPES,
  runningNodeIds = [],
  onGraphChange,
  onNodeSelectionChange,
  onNotice,
  onSaveGraph,
  saveGraphBusy = false,
}, ref) {
  const initialWorkspace = useMemo(
    () => buildInitialWorkspace(initialNodes, initialEdges),
    [initialNodes, initialEdges],
  )
  const viewportRef = useRef(null)
  const hasCenteredInitialViewRef = useRef(false)
  const nextClientNodeIdRef = useRef(initialWorkspace.nextClientNodeId)
  const nextClientEdgeIdRef = useRef(initialWorkspace.nextClientEdgeId)
  const connectDragRef = useRef(null)
  const edgePointDragRef = useRef(null)
  const viewportPanRef = useRef(null)
  const zoomRef = useRef(1)
  const wheelZoomFrameRef = useRef(0)
  const wheelZoomTargetRef = useRef(null)
  const wheelZoomAnchorRef = useRef(null)
  const wheelZoomCommitRef = useRef(null)
  const routingFieldRefs = useRef({
    [ROUTING_FOCUS_FIELD_FAN_IN_MODE]: null,
    [ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT]: null,
    [ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR]: null,
  })
  const previousSolidIncomingConnectorCountByNodeTokenRef = useRef(new Map())

  const [nodes, setNodes] = useState(() => initialWorkspace.nodes)
  const [edges, setEdges] = useState(() => initialWorkspace.edges)
  const [selectedNodeToken, setSelectedNodeToken] = useState('')
  const [selectedEdgeId, setSelectedEdgeId] = useState('')
  const [connectStart, setConnectStart] = useState(null)
  const [connectDrag, setConnectDrag] = useState(null)
  const [edgePointDrag, setEdgePointDrag] = useState(null)
  const [dragging, setDragging] = useState(null)
  const [isViewportPanning, setIsViewportPanning] = useState(false)
  const [zoom, setZoom] = useState(1)

  useEffect(() => {
    connectDragRef.current = connectDrag
  }, [connectDrag])

  useEffect(() => {
    edgePointDragRef.current = edgePointDrag
  }, [edgePointDrag])

  useEffect(() => {
    zoomRef.current = zoom
  }, [zoom])

  useEffect(() => {
    return () => {
      if (wheelZoomFrameRef.current) {
        window.cancelAnimationFrame(wheelZoomFrameRef.current)
      }
      wheelZoomTargetRef.current = null
      wheelZoomAnchorRef.current = null
      wheelZoomCommitRef.current = null
    }
  }, [])

  useLayoutEffect(() => {
    const commit = wheelZoomCommitRef.current
    const viewport = viewportRef.current
    if (!commit || !viewport) {
      return
    }
    if (Math.abs(commit.zoom - zoom) >= 0.0001) {
      return
    }
    wheelZoomCommitRef.current = null
    const maxScrollLeft = Math.max(0, WORLD_WIDTH * zoom - viewport.clientWidth)
    const maxScrollTop = Math.max(0, WORLD_HEIGHT * zoom - viewport.clientHeight)
    viewport.scrollLeft = clamp(
      commit.anchor.pointerWorldX * zoom - commit.anchor.pointerViewportX,
      0,
      maxScrollLeft,
    )
    viewport.scrollTop = clamp(
      commit.anchor.pointerWorldY * zoom - commit.anchor.pointerViewportY,
      0,
      maxScrollTop,
    )
  }, [zoom])

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
  const paletteNodeTypes = useMemo(
    () => availableNodeTypes.filter((nodeType) => nodeType !== 'start'),
    [availableNodeTypes],
  )
  const llmctlMcpServerId = useMemo(() => {
    const mcpServers = catalog && typeof catalog === 'object' && Array.isArray(catalog.mcp_servers)
      ? catalog.mcp_servers
      : []
    const llmctlServer = mcpServers.find(
      (server) => String(server?.server_key || '').trim().toLowerCase() === 'llmctl-mcp',
    )
    return parsePositiveInt(llmctlServer?.id)
  }, [catalog])

  const centerViewportOnGraphPoint = useCallback((graphX, graphY, zoomValue) => {
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    const maxScrollLeft = Math.max(0, WORLD_WIDTH * zoomValue - viewport.clientWidth)
    const maxScrollTop = Math.max(0, WORLD_HEIGHT * zoomValue - viewport.clientHeight)
    const worldCenterX = graphToWorldX(graphX) * zoomValue
    const worldCenterY = graphToWorldY(graphY) * zoomValue
    viewport.scrollLeft = clamp(worldCenterX - viewport.clientWidth / 2, 0, maxScrollLeft)
    viewport.scrollTop = clamp(worldCenterY - viewport.clientHeight / 2, 0, maxScrollTop)
  }, [])

  const viewportCenterInGraph = useCallback((viewport, zoomValue) => {
    const worldCenterX = (viewport.scrollLeft + viewport.clientWidth / 2) / zoomValue
    const worldCenterY = (viewport.scrollTop + viewport.clientHeight / 2) / zoomValue
    return {
      x: worldToGraphX(worldCenterX),
      y: worldToGraphY(worldCenterY),
    }
  }, [])

  useEffect(() => {
    if (hasCenteredInitialViewRef.current) {
      return
    }
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    const startNode = nodes.find((node) => normalizeNodeType(node.node_type) === 'start') || nodes[0] || null
    if (startNode) {
      const dimensions = nodeDimensions(startNode.node_type)
      const centerX = toNumber(startNode.x, 0) + dimensions.width / 2
      const centerY = toNumber(startNode.y, 0) + dimensions.height / 2
      centerViewportOnGraphPoint(centerX, centerY, zoom)
    } else {
      centerViewportOnGraphPoint(0, 0, zoom)
    }
    hasCenteredInitialViewRef.current = true
  }, [nodes, centerViewportOnGraphPoint, zoom])

  const nodesByToken = useMemo(() => {
    const map = new Map()
    for (const node of nodes) {
      map.set(node.token, node)
    }
    return map
  }, [nodes])

  useEffect(() => {
    const synchronized = syncDecisionNodeConditions(nodes, edges)
    if (!synchronized.changed) {
      return
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNodes(synchronized.nodes)
    setEdges(synchronized.edges)
    if (selectedEdgeId && !synchronized.edges.some((edge) => edge.localId === selectedEdgeId)) {
      setSelectedEdgeId('')
    }
  }, [nodes, edges, selectedEdgeId])

  useEffect(() => {
    if (llmctlMcpServerId == null) {
      return
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNodes((current) => {
      let changed = false
      const next = current.map((node) => {
        const existing = normalizeMcpServerIds(node.mcp_server_ids)
        const required = normalizeNodeMcpServerIds(node.node_type, existing, llmctlMcpServerId)
        if (numberListEqual(existing, required)) {
          return node
        }
        changed = true
        return { ...node, mcp_server_ids: required }
      })
      return changed ? next : current
    })
  }, [llmctlMcpServerId])

  useEffect(() => {
    if (typeof onGraphChange !== 'function') {
      return
    }
    if (syncDecisionNodeConditions(nodes, edges).changed) {
      return
    }
    const payloadNodes = nodes.map((node) => buildNodePayload(node, llmctlMcpServerId))
    const payloadEdges = edges
      .map((edge) => buildEdgePayload(edge, nodesByToken))
      .filter((edge) => edge != null)
    onGraphChange({ nodes: payloadNodes, edges: payloadEdges })
  }, [nodes, edges, nodesByToken, llmctlMcpServerId, onGraphChange])

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

  const graphPointFromClient = useCallback((clientX, clientY) => {
    const viewport = viewportRef.current
    if (!viewport) {
      return null
    }
    const currentZoom = zoomRef.current
    const rect = viewport.getBoundingClientRect()
    const worldX = (clientX - rect.left + viewport.scrollLeft) / currentZoom
    const worldY = (clientY - rect.top + viewport.scrollTop) / currentZoom
    return {
      x: worldToGraphX(worldX),
      y: worldToGraphY(worldY),
    }
  }, [])

  const connectorAtClientPoint = useCallback((clientX, clientY) => {
    if (typeof document.elementFromPoint !== 'function') {
      return null
    }
    const element = document.elementFromPoint(clientX, clientY)
    const connectorElement = element && element.closest ? element.closest('.flow-ws-node-connector') : null
    if (!connectorElement?.dataset) {
      return null
    }
    const nodeToken = String(connectorElement.dataset.nodeToken || '').trim()
    const handleId = String(connectorElement.dataset.handleId || '').trim()
    if (!nodeToken || !handleId) {
      return null
    }
    return { nodeToken, handleId }
  }, [])

  useEffect(() => {
    if (!dragging) {
      return undefined
    }

    function onPointerMove(event) {
      const pointer = graphPointFromClient(event.clientX, event.clientY)
      if (!pointer) {
        return
      }
      setNodes((current) => current.map((node) => {
        if (node.token !== dragging.token) {
          return node
        }
        const nextPosition = clampNodePosition(node.node_type, pointer.x - dragging.offsetX, pointer.y - dragging.offsetY)
        return {
          ...node,
          x: nextPosition.x,
          y: nextPosition.y,
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
  }, [dragging, graphPointFromClient])

  useEffect(() => {
    if (!edgePointDragRef.current) {
      return undefined
    }

    function onPointerMove(event) {
      const currentDrag = edgePointDragRef.current
      if (!currentDrag) {
        return
      }
      const pointer = graphPointFromClient(event.clientX, event.clientY)
      if (!pointer) {
        return
      }
      const nextPoint = clampEdgeControlPoint(pointer)
      setEdges((currentEdges) => currentEdges.map((edge) => {
        if (edge.localId !== currentDrag.edgeLocalId) {
          return edge
        }
        const controlPoints = normalizeEdgeControlPoints(edge.controlPoints)
        if (!controlPoints[currentDrag.pointIndex]) {
          return edge
        }
        const nextControlPoints = [...controlPoints]
        nextControlPoints[currentDrag.pointIndex] = nextPoint
        return {
          ...edge,
          controlPoints: nextControlPoints,
        }
      }))
    }

    function onPointerUp() {
      setEdgePointDrag(null)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onPointerUp)
    }
  }, [edgePointDrag, graphPointFromClient])

  const selectedNode = selectedNodeToken ? nodesByToken.get(selectedNodeToken) || null : null
  const selectedNodeType = selectedNode ? normalizeNodeType(selectedNode.node_type) : ''
  const canSaveGraph = typeof onSaveGraph === 'function'
  const saveButtonDisabled = saveGraphBusy || !canSaveGraph
  const selectedEdge = selectedEdgeId
    ? edges.find((edge) => edge.localId === selectedEdgeId) || null
    : null
  const selectedEdgeControlPointCount = selectedEdge
    ? normalizeEdgeControlPoints(selectedEdge.controlPoints).length
    : 0
  const decisionConditionLookupByNodeToken = useMemo(() => {
    const lookup = new Map()
    for (const node of nodes) {
      if (normalizeNodeType(node.node_type) !== 'decision') {
        continue
      }
      const entries = normalizeDecisionConditions(node.config?.decision_conditions)
      lookup.set(
        node.token,
        new Map(entries.map((entry) => [entry.connector_id, entry.condition_text])),
      )
    }
    return lookup
  }, [nodes])
  const selectedEdgeSourceNode = selectedEdge ? nodesByToken.get(selectedEdge.sourceToken) || null : null
  const selectedEdgeIsDecisionManaged = Boolean(
    selectedEdge
    && selectedEdgeSourceNode
    && normalizeNodeType(selectedEdgeSourceNode.node_type) === 'decision'
    && normalizeEdgeMode(selectedEdge.edge_mode) === 'solid',
  )
  const selectedDecisionConditions = useMemo(() => {
    if (!selectedNode || selectedNodeType !== 'decision') {
      return []
    }
    const configured = new Map(
      normalizeDecisionConditions(selectedNode.config?.decision_conditions)
        .map((entry) => [entry.connector_id, entry.condition_text]),
    )
    return edges
      .filter((edge) => (
        edge.sourceToken === selectedNode.token
        && normalizeEdgeMode(edge.edge_mode) === 'solid'
      ))
      .map((edge) => {
        const connectorId = String(edge.condition_key || '').trim()
        const targetNode = nodesByToken.get(edge.targetToken)
        const targetLabel = targetNode
          ? String(targetNode.title || titleForType(targetNode.node_type) || '').trim()
          : ''
        return {
          connectorId,
          targetLabel: targetLabel || 'Unresolved',
          conditionText: configured.get(connectorId) || '',
        }
      })
      .filter((entry) => Boolean(entry.connectorId))
  }, [selectedNode, selectedNodeType, edges, nodesByToken])
  const solidIncomingConnectorCountByNodeToken = useMemo(() => {
    const parentTokensByNodeToken = new Map()
    for (const edge of edges) {
      if (normalizeEdgeMode(edge.edge_mode) !== 'solid') {
        continue
      }
      const sourceToken = String(edge.sourceToken || '')
      const targetToken = String(edge.targetToken || '')
      if (!sourceToken || !targetToken) {
        continue
      }
      const parentTokens = parentTokensByNodeToken.get(targetToken) || new Set()
      parentTokens.add(sourceToken)
      parentTokensByNodeToken.set(targetToken, parentTokens)
    }
    const counts = new Map()
    for (const [token, parentTokens] of parentTokensByNodeToken.entries()) {
      counts.set(token, parentTokens.size)
    }
    return counts
  }, [edges])
  const decisionSolidOutgoingConnectorOptionsByNodeToken = useMemo(() => {
    const optionsByToken = new Map()
    const seenByToken = new Map()
    for (const edge of edges) {
      if (normalizeEdgeMode(edge.edge_mode) !== 'solid') {
        continue
      }
      const sourceToken = String(edge.sourceToken || '').trim()
      const sourceNode = nodesByToken.get(sourceToken)
      if (!sourceNode || normalizeNodeType(sourceNode.node_type) !== 'decision') {
        continue
      }
      const connectorId = String(edge.condition_key || '').trim()
      if (!connectorId) {
        continue
      }
      const seen = seenByToken.get(sourceToken) || new Set()
      if (seen.has(connectorId)) {
        continue
      }
      seen.add(connectorId)
      seenByToken.set(sourceToken, seen)
      const targetNode = nodesByToken.get(edge.targetToken)
      const targetLabel = targetNode
        ? String(targetNode.title || titleForType(targetNode.node_type)).trim()
        : ''
      const options = optionsByToken.get(sourceToken) || []
      options.push({
        connectorId,
        targetLabel: targetLabel || 'Unresolved',
      })
      optionsByToken.set(sourceToken, options)
    }
    return optionsByToken
  }, [edges, nodesByToken])
  const routingValidationByNodeToken = useMemo(() => {
    const validations = new Map()
    for (const node of nodes) {
      const solidIncomingConnectorCount = solidIncomingConnectorCountByNodeToken.get(node.token) || 0
      const outgoingOptions = decisionSolidOutgoingConnectorOptionsByNodeToken.get(node.token) || []
      const outgoingConnectorIds = new Set(outgoingOptions.map((entry) => entry.connectorId))
      validations.set(
        node.token,
        validateRoutingConfig({
          nodeType: node.node_type,
          config: node.config,
          solidIncomingConnectorCount,
          decisionSolidOutgoingConnectorIds: outgoingConnectorIds,
        }),
      )
    }
    return validations
  }, [nodes, solidIncomingConnectorCountByNodeToken, decisionSolidOutgoingConnectorOptionsByNodeToken])
  const selectedRoutingValidation = selectedNode
    ? (routingValidationByNodeToken.get(selectedNode.token) || EMPTY_ROUTING_VALIDATION)
    : null
  const selectedSolidIncomingConnectorCount = selectedNode
    ? (solidIncomingConnectorCountByNodeToken.get(selectedNode.token) || 0)
    : 0
  const selectedRoutingConfig = selectedNode
    ? (selectedNode.config && typeof selectedNode.config === 'object' ? selectedNode.config : {})
    : {}
  const selectedFanInMode = normalizeFanInMode(selectedRoutingConfig.fan_in_mode)
  const selectedFanInCustomCount = parsePositiveInt(selectedRoutingConfig.fan_in_custom_count)
  const selectedDecisionNoMatchPolicy = normalizeDecisionNoMatchPolicy(selectedRoutingConfig.no_match_policy)
  const selectedDecisionFallbackConnectorId = String(selectedRoutingConfig.fallback_condition_key || '').trim()
  const selectedDecisionFallbackConnectorOptions = selectedNode
    ? (decisionSolidOutgoingConnectorOptionsByNodeToken.get(selectedNode.token) || [])
    : []
  const selectedRoutingSummaryChips = useMemo(() => {
    if (!selectedNode || !nodeSupportsRoutingConfig(selectedNodeType)) {
      return []
    }
    const chips = []
    if (selectedFanInMode === FAN_IN_MODE_CUSTOM) {
      chips.push({
        key: 'fan-in-custom',
        label: `custom ${selectedFanInCustomCount ?? '?'}`,
        className: 'chip flow-ws-routing-chip',
      })
    } else {
      chips.push({
        key: 'fan-in-mode',
        label: selectedFanInMode,
        className: 'chip flow-ws-routing-chip',
      })
    }
    if (selectedNodeType === 'decision') {
      const fallbackLabel = selectedDecisionFallbackConnectorId
        ? `fallback ${selectedDecisionFallbackConnectorId}`
        : (selectedDecisionNoMatchPolicy === DECISION_NO_MATCH_POLICY_FAIL ? 'no match: fail' : 'no match: fail')
      chips.push({
        key: 'decision-fallback',
        label: fallbackLabel,
        className: 'chip flow-ws-routing-chip',
      })
    }
    if (selectedRoutingValidation?.hasErrors) {
      chips.push({
        key: 'invalid',
        label: `invalid ${selectedRoutingValidation.errors.length}`,
        className: 'status-chip status-failed flow-ws-routing-chip',
      })
    }
    return chips
  }, [
    selectedNode,
    selectedNodeType,
    selectedFanInMode,
    selectedFanInCustomCount,
    selectedDecisionNoMatchPolicy,
    selectedDecisionFallbackConnectorId,
    selectedRoutingValidation,
  ])
  const selectedSpecializedControls = selectedNode
    ? SPECIALIZED_NODE_CONTROL_REGISTRY[selectedNodeType] || null
    : null
  const selectedSpecializedConfig = (
    selectedNode && selectedSpecializedControls
      ? normalizeNodeConfig(selectedNode.config, selectedNodeType)
      : null
  )
  const selectedRagConfig = (
    selectedNode && selectedNodeType === 'rag'
      ? normalizeNodeConfig(selectedNode.config, selectedNodeType)
      : null
  )
  const selectedRagMode = normalizeRagMode(selectedRagConfig?.mode)
  const ragModeRequiresEmbeddingModel = selectedNodeType === 'rag'
    && (selectedRagMode === RAG_MODE_FRESH_INDEX || selectedRagMode === RAG_MODE_DELTA_INDEX)
  const selectedRagCollectionSet = new Set(normalizeRagCollections(selectedRagConfig?.collections))
  const selectedPlanConfig = (
    selectedNode && selectedNodeType === 'plan'
      ? selectedSpecializedConfig
      : null
  )
  const selectedPlanNodeNeedsCompletionTarget = Boolean(
    selectedPlanConfig
    && selectedPlanConfig.action === PLAN_ACTION_COMPLETE_PLAN_ITEM
    && !selectedPlanConfig.plan_item_id
    && !(selectedPlanConfig.stage_key && selectedPlanConfig.task_key)
    && !selectedPlanConfig.completion_source_path,
  )
  const selectedTaskNodeNeedsPrompt = Boolean(
    selectedNode
    && selectedNodeType === 'task'
    && !hasTaskPrompt(selectedNode.config),
  )
  const inspectorTitle = selectedNode
    ? 'Node Inspector'
    : (selectedEdge ? 'Edge Inspector' : 'Inspector')

  const emitNotice = useCallback((message) => {
    if (typeof onNotice === 'function') {
      onNotice(String(message || ''))
    }
  }, [onNotice])

  useEffect(() => {
    const clampTargets = []
    const previousCounts = previousSolidIncomingConnectorCountByNodeTokenRef.current
    const nextCounts = new Map()
    for (const node of nodes) {
      if (!nodeSupportsRoutingConfig(node.node_type)) {
        continue
      }
      const nextConfig = node.config && typeof node.config === 'object' ? node.config : {}
      if (normalizeFanInMode(nextConfig.fan_in_mode) !== FAN_IN_MODE_CUSTOM) {
        const solidIncomingConnectorCount = solidIncomingConnectorCountByNodeToken.get(node.token) || 0
        nextCounts.set(node.token, solidIncomingConnectorCount)
        continue
      }
      const currentCustomCount = parsePositiveInt(nextConfig.fan_in_custom_count)
      const solidIncomingConnectorCount = solidIncomingConnectorCountByNodeToken.get(node.token) || 0
      nextCounts.set(node.token, solidIncomingConnectorCount)
      const previousSolidIncomingConnectorCount = previousCounts.get(node.token)
      const incomingShrinkDetected = (
        Number.isInteger(previousSolidIncomingConnectorCount)
        && previousSolidIncomingConnectorCount > solidIncomingConnectorCount
      )
      if (
        currentCustomCount == null
        || solidIncomingConnectorCount < 1
        || currentCustomCount <= solidIncomingConnectorCount
        || !incomingShrinkDetected
      ) {
        continue
      }
      clampTargets.push({
        token: node.token,
        nodeType: node.node_type,
        title: node.title,
        previousCount: currentCustomCount,
        nextCount: solidIncomingConnectorCount,
      })
    }
    previousSolidIncomingConnectorCountByNodeTokenRef.current = nextCounts

    if (clampTargets.length === 0) {
      return
    }

    const clampByToken = new Map(clampTargets.map((item) => [item.token, item]))
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNodes((current) => current.map((node) => {
      const target = clampByToken.get(node.token)
      if (!target) {
        return node
      }
      const nextConfig = node.config && typeof node.config === 'object' ? { ...node.config } : {}
      nextConfig.fan_in_mode = FAN_IN_MODE_CUSTOM
      nextConfig.fan_in_custom_count = target.nextCount
      return {
        ...node,
        config: nextConfig,
      }
    }))

    for (const target of clampTargets) {
      const label = String(target.title || titleForType(target.nodeType) || 'node').trim() || 'node'
      emitNotice(`Routing warning: ${label} custom N auto-clamped from ${target.previousCount} to ${target.nextCount}.`)
    }
  }, [emitNotice, nodes, solidIncomingConnectorCountByNodeToken])

  const focusRoutingField = useCallback((fieldKey) => {
    const field = routingFieldRefs.current[fieldKey]
    if (!field) {
      return
    }
    if (typeof field.scrollIntoView === 'function') {
      field.scrollIntoView({ block: 'center', inline: 'nearest' })
    }
    if (typeof field.focus === 'function') {
      field.focus()
    }
  }, [])

  const validateRoutingBeforeSave = useCallback(() => {
    let firstInvalid = null
    for (const node of nodes) {
      const validation = routingValidationByNodeToken.get(node.token)
      if (!validation?.hasErrors) {
        continue
      }
      firstInvalid = {
        nodeToken: node.token,
        validation,
      }
      break
    }
    if (!firstInvalid) {
      return true
    }

    if (selectedNodeToken !== firstInvalid.nodeToken) {
      setSelectedNodeToken(firstInvalid.nodeToken)
      setSelectedEdgeId('')
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const routingDetails = document.getElementById(FLOW_WS_ROUTING_DETAILS_ID)
        if (routingDetails && !routingDetails.open) {
          routingDetails.open = true
        }
        if (firstInvalid.validation.firstInvalidField) {
          focusRoutingField(firstInvalid.validation.firstInvalidField)
        }
      })
    })

    const firstMessage = firstInvalid.validation.errors[0] || 'Invalid routing configuration.'
    emitNotice(`Save blocked. ${firstMessage}`)
    return false
  }, [emitNotice, focusRoutingField, nodes, routingValidationByNodeToken, selectedNodeToken])

  function updateNode(token, updater) {
    setNodes((current) => current.map((node) => {
      if (node.token !== token) {
        return node
      }
      const nextNode = typeof updater === 'function' ? updater(node) : { ...node, ...updater }
      const normalizedType = normalizeNodeType(nextNode.node_type)
      const normalizedModelId = NODE_TYPES_WITH_MODEL.has(normalizedType)
        ? parseOptionalInt(nextNode.model_id)
        : null
      const nextMcpServerIds = normalizeNodeMcpServerIds(
        normalizedType,
        nextNode.mcp_server_ids,
        llmctlMcpServerId,
      )
      return {
        ...nextNode,
        node_type: normalizedType,
        model_id: normalizedModelId,
        mcp_server_ids: nextMcpServerIds,
        config: normalizeNodeConfig(
          nextNode.config && typeof nextNode.config === 'object'
            ? nextNode.config
            : defaultConfigForType(normalizedType),
          normalizedType,
        ),
      }
    }))
  }

  function updateEdge(localId, updater) {
    setEdges((current) => current.map((edge) => {
      if (edge.localId !== localId) {
        return edge
      }
      const nextEdge = typeof updater === 'function' ? updater(edge) : { ...edge, ...updater }
      return {
        ...nextEdge,
        controlPoints: normalizeEdgeControlPoints(nextEdge.controlPoints),
        controlPointStyle: normalizeEdgeControlPointStyle(nextEdge.controlPointStyle),
      }
    }))
  }

  function addEdgeControlPoint(localId, clientX, clientY) {
    const pointer = graphPointFromClient(clientX, clientY)
    if (!pointer) {
      return
    }
    const edge = edges.find((item) => item.localId === localId)
    if (!edge) {
      return
    }
    const sourceNode = nodesByToken.get(edge.sourceToken)
    const targetNode = nodesByToken.get(edge.targetToken)
    if (!sourceNode || !targetNode) {
      return
    }
    const start = connectorPosition(sourceNode, edge.sourceHandleId)
    const end = connectorPosition(targetNode, edge.targetHandleId)
    const controlPoints = normalizeEdgeControlPoints(edge.controlPoints)
    const worldControlPoints = controlPoints.map((point) => ({
      x: graphToWorldX(point.x),
      y: graphToWorldY(point.y),
    }))
    const insertAt = controlPointInsertIndex(
      start,
      end,
      worldControlPoints,
      { x: graphToWorldX(pointer.x), y: graphToWorldY(pointer.y) },
    )
    const nextControlPoints = [...controlPoints]
    if (nextControlPoints.length < MAX_EDGE_CONTROL_POINTS) {
      nextControlPoints.splice(insertAt, 0, clampEdgeControlPoint(pointer))
      updateEdge(localId, { controlPoints: nextControlPoints })
    }
    setSelectedEdgeId(localId)
    setSelectedNodeToken('')
  }

  function removeEdgeControlPoint(localId, pointIndex) {
    updateEdge(localId, (edge) => {
      const controlPoints = normalizeEdgeControlPoints(edge.controlPoints)
      if (!controlPoints[pointIndex]) {
        return edge
      }
      const nextControlPoints = [...controlPoints]
      nextControlPoints.splice(pointIndex, 1)
      return {
        ...edge,
        controlPoints: nextControlPoints,
      }
    })
  }

  function beginEdgeControlPointDrag(event, edgeLocalId, pointIndex) {
    if (event.button !== 0) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    setSelectedEdgeId(edgeLocalId)
    setSelectedNodeToken('')
    setEdgePointDrag({ edgeLocalId, pointIndex })
  }

  function addNodeAt(nodeType, centerX, centerY) {
    const normalizedType = normalizeNodeType(nodeType)
    if (normalizedType === 'start' && nodes.some((node) => normalizeNodeType(node.node_type) === 'start')) {
      emitNotice('Only one start node is allowed.')
      return
    }

    const dimensions = nodeDimensions(normalizedType)
    const x = toNumber(centerX, 0) - dimensions.width / 2
    const y = toNumber(centerY, 0) - dimensions.height / 2
    const nextPosition = clampNodePosition(normalizedType, x, y)

    const clientId = nextClientNodeIdRef.current++
    const node = {
      token: makeNodeToken(null, clientId),
      persistedId: null,
      clientId,
      node_type: normalizedType,
      title: titleForType(normalizedType),
      ref_id: null,
      x: nextPosition.x,
      y: nextPosition.y,
      config: normalizeNodeConfig(defaultConfigForType(normalizedType), normalizedType),
      model_id: null,
      mcp_server_ids: normalizeNodeMcpServerIds(normalizedType, [], llmctlMcpServerId),
      script_ids: [],
      attachment_ids: [],
    }

    setNodes((current) => [...current, node])
    setSelectedNodeToken(node.token)
    setSelectedEdgeId('')
  }

  function addNode(nodeType) {
    const viewport = viewportRef.current
    const center = viewport ? viewportCenterInGraph(viewport, zoom) : { x: 0, y: 0 }
    const centerX = center.x
    const centerY = center.y
    addNodeAt(nodeType, centerX, centerY)
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
    setEdgePointDrag(null)
  }, [emitNotice, nodesByToken])

  const confirmAndRemoveNode = useCallback((node) => {
    if (!node) {
      return
    }
    const fallbackLabel = titleForType(node.node_type)
    const label = String(node.title || fallbackLabel || 'node').trim()
    if (!window.confirm(`Delete node "${label}"?`)) {
      return
    }
    removeNode(node.token)
  }, [removeNode])

  const removeEdge = useCallback((localId) => {
    setEdges((current) => current.filter((edge) => edge.localId !== localId))
    setSelectedEdgeId('')
    setEdgePointDrag(null)
  }, [])

  function applyServerGraph(nextNodesRaw, nextEdgesRaw) {
    const nextWorkspace = buildInitialWorkspace(nextNodesRaw, nextEdgesRaw)
    const selectedNodeSnapshot = buildNodeSelectionSnapshot(
      selectedNodeToken ? nodesByToken.get(selectedNodeToken) : null,
    )
    const selectedEdge = selectedEdgeId
      ? edges.find((edge) => edge.localId === selectedEdgeId) || null
      : null
    const selectedEdgeSnapshot = buildEdgeSelectionSnapshot(selectedEdge, nodesByToken)
    const nextNodesByToken = new Map(nextWorkspace.nodes.map((node) => [node.token, node]))
    const nextSelectedNodeToken = resolveNodeTokenFromSnapshot(nextWorkspace.nodes, selectedNodeSnapshot)
    const nextSelectedEdgeId = nextSelectedNodeToken
      ? ''
      : resolveEdgeIdFromSnapshot(nextWorkspace.edges, nextNodesByToken, selectedEdgeSnapshot)

    nextClientNodeIdRef.current = nextWorkspace.nextClientNodeId
    nextClientEdgeIdRef.current = nextWorkspace.nextClientEdgeId
    setNodes(nextWorkspace.nodes)
    setEdges(nextWorkspace.edges)
    setSelectedNodeToken(nextSelectedNodeToken)
    setSelectedEdgeId(nextSelectedEdgeId)
    setEdgePointDrag(null)
    return true
  }

  useImperativeHandle(ref, () => ({
    applyServerGraph,
    validateBeforeSave: validateRoutingBeforeSave,
  }))

  useEffect(() => {
    function onKeyDown(event) {
      const tagName = String(event?.target?.tagName || '').toLowerCase()
      if (tagName === 'input' || tagName === 'textarea' || tagName === 'select' || event.metaKey || event.ctrlKey) {
        return
      }
      if (event.key === 'Escape') {
        setConnectStart(null)
        setConnectDrag(null)
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
    event.preventDefault()
    const pointer = graphPointFromClient(event.clientX, event.clientY)
    if (!pointer) {
      return
    }
    setDragging({
      token: node.token,
      offsetX: pointer.x - toNumber(node.x, 0),
      offsetY: pointer.y - toNumber(node.y, 0),
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
    const resolvedSourceHandleId = normalizeHandleIdForNode(
      sourceNode.node_type,
      sourceHandleId || defaultSourceHandleId(sourceNode, targetNode),
    ) || defaultSourceHandleId(sourceNode, targetNode)
    const resolvedTargetHandleId = normalizeHandleIdForNode(
      targetNode.node_type,
      targetHandleId || defaultTargetHandleId(sourceNode, targetNode),
    ) || defaultTargetHandleId(sourceNode, targetNode)
    const duplicate = edges.some((edge) => (
      edge.sourceToken === sourceToken &&
      edge.targetToken === targetToken &&
      edge.sourceHandleId === resolvedSourceHandleId &&
      edge.targetHandleId === resolvedTargetHandleId
    ))
    if (duplicate) {
      return
    }

    const edge = {
      localId: `client-edge:${nextClientEdgeIdRef.current++}`,
      persistedId: null,
      sourceToken,
      targetToken,
      sourceHandleId: resolvedSourceHandleId,
      targetHandleId: resolvedTargetHandleId,
      edge_mode: 'solid',
      condition_key: '',
      label: '',
      controlPoints: [],
      controlPointStyle: EDGE_CONTROL_STYLE_HARD,
    }
    setEdges((current) => [...current, edge])
    setSelectedEdgeId(edge.localId)
    setSelectedNodeToken('')
  }

  const toggleConnector = useCallback((nodeToken, handleId) => {
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
  }, [connectStart, createEdge])

  function beginConnectorInteraction(event, nodeToken, handleId) {
    if (event.button !== 0) {
      return
    }
    const pointer = graphPointFromClient(event.clientX, event.clientY)
    if (!pointer) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    setConnectDrag({
      sourceToken: nodeToken,
      sourceHandleId: handleId,
      pointerX: pointer.x,
      pointerY: pointer.y,
      hoverNodeToken: '',
      hoverHandleId: '',
      moved: false,
      startClientX: event.clientX,
      startClientY: event.clientY,
    })
    setSelectedNodeToken(nodeToken)
    setSelectedEdgeId('')
  }

  const hasConnectDrag = Boolean(connectDrag)

  useEffect(() => {
    if (!connectDragRef.current) {
      return undefined
    }

    function onPointerMove(event) {
      const pointer = graphPointFromClient(event.clientX, event.clientY)
      if (!pointer) {
        return
      }
      const hovered = connectorAtClientPoint(event.clientX, event.clientY)
      setConnectDrag((current) => {
        if (!current) {
          return current
        }
        const moved = current.moved || Math.hypot(
          event.clientX - current.startClientX,
          event.clientY - current.startClientY,
        ) > 4
        return {
          ...current,
          pointerX: pointer.x,
          pointerY: pointer.y,
          hoverNodeToken: hovered?.nodeToken || '',
          hoverHandleId: hovered?.handleId || '',
          moved,
        }
      })
    }

    function onPointerUp(event) {
      const current = connectDragRef.current
      if (!current) {
        return
      }
      const hovered = connectorAtClientPoint(event.clientX, event.clientY)
      const targetNodeToken = hovered?.nodeToken || current.hoverNodeToken
      const targetHandleId = hovered?.handleId || current.hoverHandleId
      if (current.moved) {
        if (
          targetNodeToken
          && targetHandleId
          && !(targetNodeToken === current.sourceToken && targetHandleId === current.sourceHandleId)
        ) {
          createEdge(current.sourceToken, current.sourceHandleId, targetNodeToken, targetHandleId)
        }
        setConnectStart(null)
      } else {
        toggleConnector(current.sourceToken, current.sourceHandleId)
      }
      setConnectDrag(null)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
    }
  }, [hasConnectDrag, connectorAtClientPoint, createEdge, graphPointFromClient, toggleConnector])

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
      if (!SPECIALIZED_NODE_TYPES.has(normalizedType)) {
        delete nextConfig.action
        delete nextConfig.additive_prompt
        delete nextConfig.retention_mode
        delete nextConfig.retention_ttl_seconds
        delete nextConfig.retention_max_count
      }
      if (normalizedType !== 'plan') {
        delete nextConfig.plan_item_id
        delete nextConfig.stage_key
        delete nextConfig.task_key
        delete nextConfig.completion_source_path
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
      if (normalizedType === 'milestone') {
        nextConfig.action = normalizeMilestoneAction(nextConfig.action)
        nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
        nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
        nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_MILESTONE_RETENTION_TTL_SECONDS
        nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_MILESTONE_RETENTION_MAX_COUNT
      }
      if (normalizedType === 'memory') {
        nextConfig.action = normalizeMemoryAction(nextConfig.action)
        nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
        nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
        nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_MILESTONE_RETENTION_TTL_SECONDS
        nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_MILESTONE_RETENTION_MAX_COUNT
      }
      if (normalizedType === 'plan') {
        nextConfig.action = normalizePlanAction(nextConfig.action)
        nextConfig.additive_prompt = String(nextConfig.additive_prompt || '')
        nextConfig.retention_mode = normalizeMilestoneRetentionMode(nextConfig.retention_mode)
        nextConfig.retention_ttl_seconds = parseOptionalInt(nextConfig.retention_ttl_seconds) ?? DEFAULT_PLAN_RETENTION_TTL_SECONDS
        nextConfig.retention_max_count = parseOptionalInt(nextConfig.retention_max_count) ?? DEFAULT_PLAN_RETENTION_MAX_COUNT
        nextConfig.plan_item_id = parsePositiveInt(nextConfig.plan_item_id)
        nextConfig.stage_key = String(nextConfig.stage_key || '').trim()
        nextConfig.task_key = String(nextConfig.task_key || '').trim()
        nextConfig.completion_source_path = String(nextConfig.completion_source_path || '').trim()
      }
      return {
        ...current,
        node_type: normalizedType,
        ref_id: (() => {
          const currentType = normalizeNodeType(current.node_type)
          if (!NODE_TYPE_WITH_REF.has(normalizedType)) {
            return null
          }
          if (normalizedType === 'flowchart') {
            return current.ref_id
          }
          return currentType === normalizedType ? current.ref_id : null
        })(),
        config: nextConfig,
        mcp_server_ids: normalizeNodeMcpServerIds(
          normalizedType,
          current.mcp_server_ids,
          llmctlMcpServerId,
        ),
      }
    })
  }

  const selectedNodeRefCatalogKey = NODE_TYPE_WITH_EDITABLE_REF.has(selectedNodeType)
    ? TYPE_TO_REF_CATALOG_KEY[selectedNodeType]
    : null
  const selectedNodeRefRows = selectedNodeRefCatalogKey && catalog && typeof catalog === 'object'
    ? catalog[selectedNodeRefCatalogKey]
    : []
  const selectedNodeRefOptions = Array.isArray(selectedNodeRefRows) ? selectedNodeRefRows : []
  const modelOptions = useMemo(() => (
    catalog && typeof catalog === 'object' && Array.isArray(catalog.models)
      ? catalog.models
      : []
  ), [catalog])
  const modelById = useMemo(() => {
    const map = new Map()
    for (const model of modelOptions) {
      const modelId = parsePositiveInt(model?.id)
      if (modelId == null) {
        continue
      }
      map.set(modelId, model)
    }
    return map
  }, [modelOptions])
  const embeddingModelOptions = useMemo(
    () => modelOptions.filter((model) => isEmbeddingModelOption(model)),
    [modelOptions],
  )
  const selectedNodeModelOptions = (
    selectedNodeType === 'rag' && ragModeRequiresEmbeddingModel
      ? embeddingModelOptions
      : modelOptions
  )
  const selectedNodeModelProvider = selectedNode
    ? modelById.get(parsePositiveInt(selectedNode.model_id))?.provider
    : ''
  const selectedRagModelIsEmbedding = isEmbeddingModelOption(
    selectedNode ? modelById.get(parsePositiveInt(selectedNode.model_id)) : null,
  )
  const selectedNodeMcpBindingsLocked = selectedNodeType === 'rag' || !nodeSupportsMcpServerBindings(selectedNodeType)
  const ragCollectionRows = useMemo(() => (
    catalog && typeof catalog === 'object' && Array.isArray(catalog.rag_collections)
      ? catalog.rag_collections
      : []
  ), [catalog])
  const ragCollectionOptions = useMemo(() => (
    ragCollectionRows
      .map((item) => {
        const id = String(item?.id || '').trim()
        if (!id) {
          return null
        }
        const name = String(item?.name || '').trim() || id
        const status = String(item?.status || '').trim()
        return {
          id,
          label: status ? `${name} (${status})` : name,
        }
      })
      .filter((item) => item != null)
  ), [ragCollectionRows])
  const agentOptions = catalog && typeof catalog === 'object' && Array.isArray(catalog.agents)
    ? catalog.agents
    : []
  const mcpServerOptions = catalog && typeof catalog === 'object' && Array.isArray(catalog.mcp_servers)
    ? catalog.mcp_servers
    : []

  function setZoomKeepingCenter(nextZoomValue) {
    const viewport = viewportRef.current
    const currentZoom = zoomRef.current
    const nextZoom = normalizeZoom(nextZoomValue)
    if (!viewport) {
      zoomRef.current = nextZoom
      setZoom(nextZoom)
      return
    }
    if (Math.abs(nextZoom - currentZoom) < 0.001) {
      return
    }
    const center = viewportCenterInGraph(viewport, currentZoom)
    zoomRef.current = nextZoom
    setZoom(nextZoom)
    window.requestAnimationFrame(() => {
      centerViewportOnGraphPoint(center.x, center.y, nextZoom)
    })
  }

  function resetViewport() {
    const viewport = viewportRef.current
    const focusNode = nodes.find((node) => normalizeNodeType(node.node_type) === 'start') || nodes[0] || null
    const nextZoom = 1
    zoomRef.current = nextZoom
    setZoom(nextZoom)
    if (!viewport) {
      return
    }
    window.requestAnimationFrame(() => {
      if (focusNode) {
        const dimensions = nodeDimensions(focusNode.node_type)
        const centerX = toNumber(focusNode.x, 0) + dimensions.width / 2
        const centerY = toNumber(focusNode.y, 0) + dimensions.height / 2
        centerViewportOnGraphPoint(centerX, centerY, nextZoom)
        return
      }
      centerViewportOnGraphPoint(0, 0, nextZoom)
    })
  }

  useEffect(() => {
    function onPointerMove(event) {
      const panState = viewportPanRef.current
      const viewport = viewportRef.current
      if (!panState || !viewport) {
        return
      }
      const deltaX = event.clientX - panState.startClientX
      const deltaY = event.clientY - panState.startClientY
      const currentZoom = zoomRef.current
      const maxScrollLeft = Math.max(0, WORLD_WIDTH * currentZoom - viewport.clientWidth)
      const maxScrollTop = Math.max(0, WORLD_HEIGHT * currentZoom - viewport.clientHeight)
      viewport.scrollLeft = clamp(panState.startScrollLeft - deltaX, 0, maxScrollLeft)
      viewport.scrollTop = clamp(panState.startScrollTop - deltaY, 0, maxScrollTop)
      if (!panState.moved && Math.hypot(deltaX, deltaY) > 2) {
        viewportPanRef.current = { ...panState, moved: true }
        setIsViewportPanning(true)
      }
    }

    function clearViewportPan() {
      if (!viewportPanRef.current) {
        return
      }
      viewportPanRef.current = null
      setIsViewportPanning(false)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', clearViewportPan)
    window.addEventListener('pointercancel', clearViewportPan)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', clearViewportPan)
      window.removeEventListener('pointercancel', clearViewportPan)
    }
  }, [])

  function beginViewportPan(event) {
    if (event.button !== 0) {
      return
    }
    if (dragging || connectDragRef.current) {
      return
    }
    const interactiveElement = event.target?.closest?.(
      '.flow-ws-node, .flow-ws-node-connector, .flow-ws-edge-hit, .flow-ws-edge-control, .flow-ws-edge-control-hit, a, button, input, select, textarea, label, summary, details',
    )
    if (interactiveElement) {
      return
    }
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    event.preventDefault()
    viewportPanRef.current = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startScrollLeft: viewport.scrollLeft,
      startScrollTop: viewport.scrollTop,
      moved: false,
    }
  }

  const handleViewportWheel = useCallback((event) => {
    const viewport = viewportRef.current
    if (!viewport) {
      return
    }
    if (event.deltaY === 0) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    const currentZoom = zoomRef.current
    const baseZoom = wheelZoomTargetRef.current != null ? wheelZoomTargetRef.current : currentZoom
    const zoomFactor = Math.exp(-event.deltaY * WHEEL_ZOOM_SENSITIVITY)
    const nextZoom = normalizeZoom(baseZoom * zoomFactor)
    if (Math.abs(nextZoom - baseZoom) < 0.001) {
      return
    }
    const rect = viewport.getBoundingClientRect()
    const pointerViewportX = event.clientX - rect.left
    const pointerViewportY = event.clientY - rect.top
    const pointerWorldX = (pointerViewportX + viewport.scrollLeft) / currentZoom
    const pointerWorldY = (pointerViewportY + viewport.scrollTop) / currentZoom
    wheelZoomTargetRef.current = nextZoom
    wheelZoomAnchorRef.current = {
      pointerViewportX,
      pointerViewportY,
      pointerWorldX,
      pointerWorldY,
    }
    if (wheelZoomFrameRef.current) {
      return
    }
    wheelZoomFrameRef.current = window.requestAnimationFrame(() => {
      wheelZoomFrameRef.current = 0
      const pendingZoom = wheelZoomTargetRef.current
      const anchor = wheelZoomAnchorRef.current
      wheelZoomTargetRef.current = null
      wheelZoomAnchorRef.current = null
      if (pendingZoom == null || !anchor) {
        return
      }
      wheelZoomCommitRef.current = { zoom: pendingZoom, anchor }
      zoomRef.current = pendingZoom
      setZoom(pendingZoom)
    })
  }, [])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) {
      return undefined
    }
    viewport.addEventListener('wheel', handleViewportWheel, { passive: false })
    return () => {
      viewport.removeEventListener('wheel', handleViewportWheel)
    }
  }, [handleViewportWheel])

  function handlePaletteDragStart(event, nodeType) {
    if (!event.dataTransfer) {
      return
    }
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData(PALETTE_DRAG_TYPE, nodeType)
    event.dataTransfer.setData('text/plain', nodeType)
  }

  function handleViewportDragOver(event) {
    if (!event.dataTransfer) {
      return
    }
    const types = Array.from(event.dataTransfer.types || [])
    if (!types.includes(PALETTE_DRAG_TYPE) && !types.includes('text/plain')) {
      return
    }
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  function handleViewportDrop(event) {
    if (!event.dataTransfer) {
      return
    }
    const droppedType = event.dataTransfer.getData(PALETTE_DRAG_TYPE) || event.dataTransfer.getData('text/plain')
    const normalizedType = normalizeNodeType(droppedType)
    event.preventDefault()
    const pointer = graphPointFromClient(event.clientX, event.clientY)
    if (!pointer) {
      return
    }
    addNodeAt(normalizedType, pointer.x, pointer.y)
  }

  return (
    <div className="flow-ws-layout">
      <aside className="flow-ws-sidebar">
        <PanelHeader className="flow-ws-panel-header" title="Node Bar" />
        <div className="flow-ws-panel-body">
          <div className="flow-ws-palette">
            {paletteNodeTypes.map((nodeType) => {
              return (
                <button
                  key={nodeType}
                  type="button"
                  className="btn btn-secondary flow-ws-palette-item"
                  draggable
                  onDragStart={(event) => handlePaletteDragStart(event, nodeType)}
                  onClick={() => addNode(nodeType)}
                >
                  {nodeType}
                </button>
              )
            })}
          </div>
        </div>
      </aside>

      <div className="flow-ws-editor">
        <div className="flow-ws-toolbar">
          <div className="flow-ws-toolbar-actions">
            <button type="button" className="btn btn-secondary" onClick={() => setZoomKeepingCenter(zoom - ZOOM_STEP)}>
              <i className="fa-solid fa-magnifying-glass-minus" />
            </button>
            <span className="flow-ws-zoom-label">{Math.round(zoom * 100)}%</span>
            <button type="button" className="btn btn-secondary" onClick={() => setZoomKeepingCenter(zoom + ZOOM_STEP)}>
              <i className="fa-solid fa-magnifying-glass-plus" />
            </button>
            <button type="button" className="btn btn-secondary" onClick={resetViewport}>
              <i className="fa-solid fa-arrows-to-dot" />
              reset view
            </button>
            {(connectStart || connectDrag) ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setConnectStart(null)
                  setConnectDrag(null)
                }}
              >
                cancel connect
              </button>
            ) : null}
          </div>
        </div>
        <div
          className={`flow-ws-viewport${isViewportPanning ? ' is-panning' : ''}`}
          ref={viewportRef}
          onPointerDown={beginViewportPan}
          onDragOver={handleViewportDragOver}
          onDrop={handleViewportDrop}
        >
          <div
            className="flow-ws-world-stage"
            style={{ width: `${WORLD_WIDTH * zoom}px`, height: `${WORLD_HEIGHT * zoom}px` }}
          >
            <div
              className="flow-ws-world"
              style={{
                width: `${WORLD_WIDTH}px`,
                height: `${WORLD_HEIGHT}px`,
                transform: `scale(${zoom})`,
              }}
            >
              <svg className="flow-ws-edge-layer" viewBox={`0 0 ${WORLD_WIDTH} ${WORLD_HEIGHT}`} preserveAspectRatio="none">
                <defs>
                  <marker
                    id="flow-ws-arrow"
                    markerWidth="10"
                    markerHeight="8"
                    refX="8"
                    refY="4"
                    orient="auto"
                    markerUnits="strokeWidth"
                  >
                    <path d="M0,0 L10,4 L0,8 z" fill="currentColor" />
                  </marker>
                </defs>
                {edges.map((edge) => {
                  const sourceNode = nodesByToken.get(edge.sourceToken)
                  const targetNode = nodesByToken.get(edge.targetToken)
                  if (!sourceNode || !targetNode) {
                    return null
                  }
                  const connectorId = String(edge.condition_key || '').trim()
                  const sourceConditionLookup = decisionConditionLookupByNodeToken.get(sourceNode.token)
                  const decisionConditionText = connectorId
                    ? String(sourceConditionLookup?.get(connectorId) || '').trim()
                    : ''
                  const edgeCaption = String(edge.label || '').trim()
                    || decisionConditionText
                    || connectorId
                  const sourceConfig = sourceNode.config && typeof sourceNode.config === 'object' ? sourceNode.config : {}
                  const sourceFallbackConnectorId = String(sourceConfig.fallback_condition_key || '').trim()
                  const sourceNoMatchPolicy = normalizeDecisionNoMatchPolicy(sourceConfig.no_match_policy)
                  const isFallbackConnector = (
                    normalizeNodeType(sourceNode.node_type) === 'decision'
                    && normalizeEdgeMode(edge.edge_mode) === 'solid'
                    && sourceNoMatchPolicy === DECISION_NO_MATCH_POLICY_FALLBACK
                    && connectorId
                    && sourceFallbackConnectorId
                    && connectorId === sourceFallbackConnectorId
                  )
                  const start = connectorPosition(sourceNode, edge.sourceHandleId)
                  const end = connectorPosition(targetNode, edge.targetHandleId)
                  const controlPoints = normalizeEdgeControlPoints(edge.controlPoints)
                  const controlPointStyle = normalizeEdgeControlPointStyle(edge.controlPointStyle)
                  const worldControlPoints = controlPoints.map((point) => ({
                    x: graphToWorldX(point.x),
                    y: graphToWorldY(point.y),
                  }))
                  const pathMeta = edgePath(start, end, worldControlPoints, controlPointStyle)
                  const selected = edge.localId === selectedEdgeId
                  return (
                    <g key={edge.localId}>
                      <path
                        d={pathMeta.d}
                        className={`flow-ws-edge-path${edge.edge_mode === 'dotted' ? ' is-dotted' : ''}${selected ? ' is-selected' : ''}`}
                        markerEnd="url(#flow-ws-arrow)"
                      />
                      {edgeCaption ? (
                        <text x={pathMeta.labelX} y={pathMeta.labelY} className="flow-ws-edge-label">
                          {edgeCaption}
                        </text>
                      ) : null}
                      {isFallbackConnector ? (
                        <g
                          className="flow-ws-edge-fallback-badge"
                          transform={`translate(${pathMeta.labelX} ${pathMeta.labelY - (edgeCaption ? 18 : 0)})`}
                        >
                          <rect className="flow-ws-edge-fallback-pill" x="-30" y="-8" width="60" height="16" rx="8" />
                          <text className="flow-ws-edge-fallback-pill-text" textAnchor="middle" dominantBaseline="middle">
                            fallback
                          </text>
                        </g>
                      ) : null}
                      <path
                        d={pathMeta.d}
                        className="flow-ws-edge-hit"
                        onClick={() => {
                          setSelectedEdgeId(edge.localId)
                          setSelectedNodeToken('')
                        }}
                        onDoubleClick={(event) => {
                          event.preventDefault()
                          event.stopPropagation()
                          addEdgeControlPoint(edge.localId, event.clientX, event.clientY)
                        }}
                      />
                      {selected ? worldControlPoints.map((point, pointIndex) => (
                        <g key={`${edge.localId}:point:${pointIndex}`}>
                          <circle
                            cx={point.x}
                            cy={point.y}
                            r="9"
                            className="flow-ws-edge-control-hit"
                            onPointerDown={(event) => beginEdgeControlPointDrag(event, edge.localId, pointIndex)}
                            onDoubleClick={(event) => {
                              event.preventDefault()
                              event.stopPropagation()
                              removeEdgeControlPoint(edge.localId, pointIndex)
                            }}
                          />
                          <circle
                            cx={point.x}
                            cy={point.y}
                            r="4.5"
                            className="flow-ws-edge-control"
                            onPointerDown={(event) => beginEdgeControlPointDrag(event, edge.localId, pointIndex)}
                            onDoubleClick={(event) => {
                              event.preventDefault()
                              event.stopPropagation()
                              removeEdgeControlPoint(edge.localId, pointIndex)
                            }}
                          />
                        </g>
                      )) : null}
                    </g>
                  )
                })}
                {connectDrag ? (() => {
                  const sourceNode = nodesByToken.get(connectDrag.sourceToken)
                  if (!sourceNode) {
                    return null
                  }
                  const start = connectorPosition(sourceNode, connectDrag.sourceHandleId)
                  let end = null
                  if (connectDrag.hoverNodeToken && connectDrag.hoverHandleId) {
                    const hoverNode = nodesByToken.get(connectDrag.hoverNodeToken)
                    if (hoverNode) {
                      end = connectorPosition(hoverNode, connectDrag.hoverHandleId)
                    }
                  }
                  if (!end) {
                    const pointer = { x: graphToWorldX(connectDrag.pointerX), y: graphToWorldY(connectDrag.pointerY) }
                    end = {
                      ...pointer,
                      side: pointerSideForDraft(start, pointer),
                    }
                  }
                  const pathMeta = edgePath(start, end)
                  return (
                    <path
                      d={pathMeta.d}
                      className="flow-ws-edge-path is-selected is-draft"
                      markerEnd="url(#flow-ws-arrow)"
                    />
                  )
                })() : null}
              </svg>

              {nodes.map((node) => {
                const dimensions = nodeDimensions(node.node_type)
                const connectorLayout = connectorLayoutForNodeType(node.node_type)
                const selected = selectedNodeToken === node.token
                const persistedNodeId = parsePositiveInt(node.persistedId)
                const running = persistedNodeId != null && runningNodeIdSet.has(persistedNodeId)
                const connecting = Boolean(connectStart || connectDrag)
                return (
                  <button
                    key={node.token}
                    type="button"
                    className={`flow-ws-node is-type-${normalizeNodeType(node.node_type)}${selected ? ' is-selected' : ''}${running ? ' is-running' : ''}${connecting ? ' is-connecting' : ''}`}
                    data-node-token={node.token}
                    style={{
                      left: `${graphToWorldX(node.x)}px`,
                      top: `${graphToWorldY(node.y)}px`,
                      width: `${dimensions.width}px`,
                      height: `${dimensions.height}px`,
                    }}
                    onPointerDown={(event) => beginDrag(event, node)}
                    onClick={() => {
                      setSelectedNodeToken(node.token)
                      setSelectedEdgeId('')
                    }}
                  >
                    <span className="flow-ws-node-shape" />
                    <span className="flow-ws-node-content">
                      <span className="flow-ws-node-title">{node.title || titleForType(node.node_type)}</span>
                    </span>
                    {connectorLayout.map((connector) => {
                      const handleId = connector.id
                      const hot = (
                        (connectStart && connectStart.nodeToken === node.token && connectStart.handleId === handleId)
                        || (connectDrag && connectDrag.sourceToken === node.token && connectDrag.sourceHandleId === handleId)
                        || (connectDrag && connectDrag.hoverNodeToken === node.token && connectDrag.hoverHandleId === handleId)
                      )
                      return (
                        <span
                          key={handleId}
                          className={`flow-ws-node-connector${hot ? ' is-hot' : ''}`}
                          data-node-token={node.token}
                          data-handle-id={handleId}
                          style={{
                            left: `${(dimensions.width * connector.x) / 100}px`,
                            top: `${(dimensions.height * connector.y) / 100}px`,
                          }}
                          onPointerDown={(event) => beginConnectorInteraction(event, node.token, handleId)}
                          title="Drag to connect"
                        />
                      )
                    })}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      <aside className="flow-ws-inspector">
        <PanelHeader
          className="flow-ws-panel-header flow-ws-inspector-header"
          title={inspectorTitle}
          actions={selectedNode ? (
            <>
              <button
                type="button"
                className="icon-button"
                aria-label="Save graph"
                title="Save graph"
                disabled={saveButtonDisabled}
                onClick={() => {
                  if (!validateRoutingBeforeSave()) {
                    return
                  }
                  if (typeof onSaveGraph === 'function') {
                    onSaveGraph()
                  }
                }}
              >
                <i className="fa-solid fa-floppy-disk" />
              </button>
              <button
                type="button"
                className="icon-button icon-button-danger"
                aria-label="Delete node"
                title="Delete node"
                onClick={() => confirmAndRemoveNode(selectedNode)}
              >
                <i className="fa-solid fa-trash" />
              </button>
            </>
          ) : null}
        />
        <div className="flow-ws-panel-body">
        {selectedNode ? (
          <div className="stack-sm">
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
                value={selectedNodeType}
                onChange={(event) => handleNodeTypeChange(selectedNode, event.target.value)}
              >
                {availableNodeTypes.map((nodeType) => (
                  <option key={nodeType} value={nodeType}>
                    {nodeType}
                  </option>
                ))}
              </select>
            </label>
            {nodeSupportsRoutingConfig(selectedNodeType) ? (
              <PersistedDetails
                className="flow-ws-routing-details"
                id={FLOW_WS_ROUTING_DETAILS_ID}
                storageKey="flow-ws:inspector:routing"
                defaultOpen={false}
              >
                <summary>
                  <span className="chat-picker-summary">
                    <i className="fa-solid fa-route" />
                    <span>Routing</span>
                  </span>
                  <span className="flow-ws-routing-chip-row">
                    {selectedRoutingSummaryChips.map((chip) => (
                      <span key={chip.key} className={chip.className}>
                        {chip.label}
                      </span>
                    ))}
                  </span>
                </summary>
                <div className="stack-sm flow-ws-routing-body">
                  <label className="field">
                    <span>fan-in mode</span>
                    <select
                      ref={(node) => {
                        routingFieldRefs.current[ROUTING_FOCUS_FIELD_FAN_IN_MODE] = node
                      }}
                      value={selectedFanInMode}
                      onChange={(event) => {
                        const nextMode = normalizeFanInMode(event.target.value)
                        updateNode(selectedNode.token, (current) => {
                          const nextConfig = current.config && typeof current.config === 'object'
                            ? { ...current.config }
                            : {}
                          if (nextMode === FAN_IN_MODE_ALL) {
                            delete nextConfig.fan_in_mode
                            delete nextConfig.fan_in_custom_count
                          } else if (nextMode === FAN_IN_MODE_ANY) {
                            nextConfig.fan_in_mode = FAN_IN_MODE_ANY
                            delete nextConfig.fan_in_custom_count
                          } else {
                            nextConfig.fan_in_mode = FAN_IN_MODE_CUSTOM
                            const nextCount = parsePositiveInt(nextConfig.fan_in_custom_count)
                            nextConfig.fan_in_custom_count = nextCount ?? Math.max(1, selectedSolidIncomingConnectorCount)
                          }
                          return {
                            ...current,
                            config: nextConfig,
                          }
                        })
                      }}
                    >
                      <option value={FAN_IN_MODE_ALL}>all parents</option>
                      <option value={FAN_IN_MODE_ANY}>any parent</option>
                      <option value={FAN_IN_MODE_CUSTOM}>custom N</option>
                    </select>
                  </label>
                  <p className="toolbar-meta">
                    Solid incoming connectors: {selectedSolidIncomingConnectorCount}
                  </p>
                  {selectedFanInMode === FAN_IN_MODE_CUSTOM ? (
                    <label className="field">
                      <span>custom N</span>
                      <input
                        ref={(node) => {
                          routingFieldRefs.current[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT] = node
                        }}
                        type="number"
                        min="1"
                        step="1"
                        max={selectedSolidIncomingConnectorCount || undefined}
                        value={selectedFanInCustomCount ?? ''}
                        onChange={(event) => {
                          updateNode(selectedNode.token, (current) => {
                            const nextConfig = current.config && typeof current.config === 'object'
                              ? { ...current.config }
                              : {}
                            const nextCount = parsePositiveInt(event.target.value)
                            if (nextCount == null) {
                              delete nextConfig.fan_in_custom_count
                            } else {
                              nextConfig.fan_in_custom_count = nextCount
                            }
                            return {
                              ...current,
                              config: nextConfig,
                            }
                          })
                        }}
                      />
                    </label>
                  ) : null}
                  {selectedRoutingValidation?.fieldErrors?.[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT] ? (
                    <p className="error-text">{selectedRoutingValidation.fieldErrors[ROUTING_FOCUS_FIELD_FAN_IN_CUSTOM_COUNT]}</p>
                  ) : null}
                  {selectedNodeType === 'decision' ? (
                    <>
                      <label className="field">
                        <span>fallback connector</span>
                        <select
                          ref={(node) => {
                            routingFieldRefs.current[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR] = node
                          }}
                          value={selectedDecisionFallbackConnectorId}
                          onChange={(event) => {
                            const nextFallbackConnectorId = String(event.target.value || '').trim()
                            updateNode(selectedNode.token, (current) => {
                              const nextConfig = current.config && typeof current.config === 'object'
                                ? { ...current.config }
                                : {}
                              if (!nextFallbackConnectorId) {
                                nextConfig.no_match_policy = DECISION_NO_MATCH_POLICY_FAIL
                                delete nextConfig.fallback_condition_key
                              } else {
                                nextConfig.no_match_policy = DECISION_NO_MATCH_POLICY_FALLBACK
                                nextConfig.fallback_condition_key = nextFallbackConnectorId
                              }
                              return {
                                ...current,
                                config: nextConfig,
                              }
                            })
                          }}
                        >
                          <option value="">fail on no match</option>
                          {selectedDecisionFallbackConnectorOptions.map((entry) => (
                            <option key={entry.connectorId} value={entry.connectorId}>
                              {`${entry.connectorId} -> ${entry.targetLabel}`}
                            </option>
                          ))}
                        </select>
                      </label>
                      {selectedDecisionFallbackConnectorOptions.length === 0 ? (
                        <p className="toolbar-meta">Add a solid outgoing connector to enable fallback routing.</p>
                      ) : null}
                      {selectedRoutingValidation?.fieldErrors?.[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR] ? (
                        <p className="error-text">{selectedRoutingValidation.fieldErrors[ROUTING_FOCUS_FIELD_FALLBACK_CONNECTOR]}</p>
                      ) : null}
                    </>
                  ) : null}
                  {selectedRoutingValidation?.hasErrors
                    ? selectedRoutingValidation.errors
                      .filter((message) => !Object.values(selectedRoutingValidation.fieldErrors || {}).includes(message))
                      .map((message) => (
                        <p key={message} className="error-text">{message}</p>
                      ))
                    : null}
                </div>
              </PersistedDetails>
            ) : null}
            {NODE_TYPE_WITH_EDITABLE_REF.has(selectedNodeType) ? (
              <label className="field">
                <span>ref</span>
                {selectedNodeRefOptions.length > 0 ? (
                  <select
                    value={selectedNode.ref_id ?? ''}
                    onChange={(event) => updateNode(selectedNode.token, { ref_id: parseOptionalInt(event.target.value) })}
                  >
                    <option value="">{NODE_TYPE_REQUIRES_REF.has(selectedNodeType) ? 'Select...' : 'None'}</option>
                    {selectedNodeRefOptions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {refLabel(item, selectedNodeType)}
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
                    placeholder={NODE_TYPE_REQUIRES_REF.has(selectedNodeType) ? 'required' : 'optional'}
                  />
                )}
              </label>
            ) : null}
            {selectedNodeType === 'task' ? (
              <label className="field">
                <span>task prompt</span>
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
            {selectedSpecializedControls && selectedSpecializedConfig ? (
              <div className="stack-sm">
                <label className="field">
                  <span>action</span>
                  <select
                    required
                    value={selectedSpecializedConfig.action}
                    onChange={(event) => updateNode(selectedNode.token, (current) => ({
                      ...current,
                      config: {
                        ...(current.config && typeof current.config === 'object' ? current.config : {}),
                        action: selectedSpecializedControls.normalizeAction(event.target.value),
                      },
                    }))}
                  >
                    {selectedSpecializedControls.actionOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>optional additive prompt</span>
                  <textarea
                    value={selectedSpecializedConfig.additive_prompt}
                    onChange={(event) => updateNode(selectedNode.token, (current) => ({
                      ...current,
                      config: {
                        ...(current.config && typeof current.config === 'object' ? current.config : {}),
                        additive_prompt: event.target.value,
                      },
                    }))}
                  />
                </label>
                <label className="field">
                  <span>artifact retention</span>
                  <select
                    value={selectedSpecializedConfig.retention_mode}
                    onChange={(event) => updateNode(selectedNode.token, (current) => ({
                      ...current,
                      config: {
                        ...(current.config && typeof current.config === 'object' ? current.config : {}),
                        retention_mode: normalizeMilestoneRetentionMode(event.target.value),
                      },
                    }))}
                  >
                    {MILESTONE_RETENTION_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                {retentionModeUsesTtl(selectedSpecializedConfig.retention_mode) ? (
                  <label className="field">
                    <span>retention ttl (seconds)</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={selectedSpecializedConfig.retention_ttl_seconds ?? ''}
                      onChange={(event) => updateNode(selectedNode.token, (current) => ({
                        ...current,
                        config: {
                          ...(current.config && typeof current.config === 'object' ? current.config : {}),
                          retention_ttl_seconds: parseOptionalInt(event.target.value),
                        },
                      }))}
                    />
                  </label>
                ) : null}
                {retentionModeUsesMaxCount(selectedSpecializedConfig.retention_mode) ? (
                  <label className="field">
                    <span>retention max count</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={selectedSpecializedConfig.retention_max_count ?? ''}
                      onChange={(event) => updateNode(selectedNode.token, (current) => ({
                        ...current,
                        config: {
                          ...(current.config && typeof current.config === 'object' ? current.config : {}),
                          retention_max_count: parseOptionalInt(event.target.value),
                        },
                      }))}
                    />
                  </label>
                ) : null}
                {selectedSpecializedControls.showPlanCompletionTargetFields
                && selectedSpecializedConfig.action === PLAN_ACTION_COMPLETE_PLAN_ITEM ? (
                  <>
                    <label className="field">
                      <span>plan item id (preferred)</span>
                      <input
                        type="number"
                        min="1"
                        step="1"
                        value={selectedSpecializedConfig.plan_item_id ?? ''}
                        onChange={(event) => updateNode(selectedNode.token, (current) => ({
                          ...current,
                          config: {
                            ...(current.config && typeof current.config === 'object' ? current.config : {}),
                            plan_item_id: parsePositiveInt(event.target.value),
                          },
                        }))}
                      />
                    </label>
                    <label className="field">
                      <span>stage key</span>
                      <input
                        type="text"
                        value={selectedSpecializedConfig.stage_key || ''}
                        onChange={(event) => updateNode(selectedNode.token, (current) => ({
                          ...current,
                          config: {
                            ...(current.config && typeof current.config === 'object' ? current.config : {}),
                            stage_key: event.target.value,
                          },
                        }))}
                      />
                    </label>
                    <label className="field">
                      <span>task key</span>
                      <input
                        type="text"
                        value={selectedSpecializedConfig.task_key || ''}
                        onChange={(event) => updateNode(selectedNode.token, (current) => ({
                          ...current,
                          config: {
                            ...(current.config && typeof current.config === 'object' ? current.config : {}),
                            task_key: event.target.value,
                          },
                        }))}
                      />
                    </label>
                    <label className="field">
                      <span>completion source path</span>
                      <input
                        type="text"
                        value={selectedSpecializedConfig.completion_source_path || ''}
                        onChange={(event) => updateNode(selectedNode.token, (current) => ({
                          ...current,
                          config: {
                            ...(current.config && typeof current.config === 'object' ? current.config : {}),
                            completion_source_path: event.target.value,
                          },
                        }))}
                      />
                    </label>
                  </>
                ) : null}
                {selectedSpecializedControls.lockLlmctlMcp ? (
                  <label className="field">
                    <span>LLMCTL MCP</span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                      <input
                        type="checkbox"
                        checked={llmctlMcpServerId != null}
                        disabled
                        readOnly
                        aria-label="LLMCTL MCP (required)"
                      />
                      <span>{llmctlMcpServerId != null ? 'llmctl-mcp (required)' : 'llmctl-mcp unavailable'}</span>
                    </span>
                  </label>
                ) : null}
              </div>
            ) : null}
            {selectedTaskNodeNeedsPrompt ? (
              <p className="error-text">Task nodes require a non-empty task prompt before save/validate.</p>
            ) : null}
            {selectedRagConfig ? (
              <div className="stack-sm">
                <label className="field">
                  <span>rag mode</span>
                  <select
                    value={selectedRagMode}
                    onChange={(event) => {
                      const nextMode = normalizeRagMode(event.target.value)
                      updateNode(selectedNode.token, (current) => {
                        const nextConfig = current.config && typeof current.config === 'object'
                          ? { ...current.config }
                          : {}
                        nextConfig.mode = nextMode
                        if (nextMode !== RAG_MODE_QUERY) {
                          delete nextConfig.question_prompt
                        }
                        const currentModel = modelById.get(parsePositiveInt(current.model_id))
                        const nextModelId = (
                          (nextMode === RAG_MODE_FRESH_INDEX || nextMode === RAG_MODE_DELTA_INDEX)
                          && !isEmbeddingModelOption(currentModel)
                        )
                          ? null
                          : current.model_id
                        return {
                          ...current,
                          model_id: nextModelId,
                          config: nextConfig,
                        }
                      })
                    }}
                  >
                    {RAG_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <PersistedDetails
                  className="chat-picker chat-picker-group flow-ws-mcp-picker"
                  storageKey="flow-ws:inspector:rag-collections"
                  defaultOpen
                >
                  <summary>
                    <span className="chat-picker-summary">
                      <i className="fa-solid fa-database" />
                      <span>collections</span>
                    </span>
                  </summary>
                  {ragCollectionOptions.length > 0 ? (
                    <div className="chat-checklist flow-ws-mcp-checklist">
                      {ragCollectionOptions.map((option) => (
                        <label key={option.id} className="flow-ws-mcp-option">
                          <input
                            type="checkbox"
                            checked={selectedRagCollectionSet.has(option.id)}
                            onChange={(event) => {
                              const nextChecked = Boolean(event.target.checked)
                              updateNode(selectedNode.token, (current) => {
                                const nextConfig = current.config && typeof current.config === 'object'
                                  ? { ...current.config }
                                  : {}
                                const currentCollections = normalizeRagCollections(nextConfig.collections)
                                nextConfig.collections = nextChecked
                                  ? normalizeRagCollections([...currentCollections, option.id])
                                  : currentCollections.filter((collectionId) => collectionId !== option.id)
                                return {
                                  ...current,
                                  config: nextConfig,
                                }
                              })
                            }}
                          />
                          <span className="flow-ws-mcp-option-content">
                            <span className="flow-ws-mcp-option-title">{option.label}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <p className="toolbar-meta">No RAG collections available.</p>
                  )}
                </PersistedDetails>
                {selectedRagMode === RAG_MODE_QUERY ? (
                  <label className="field">
                    <span>query prompt</span>
                    <textarea
                      value={String(selectedRagConfig.question_prompt || '')}
                      onChange={(event) => updateNode(selectedNode.token, (current) => ({
                        ...current,
                        config: {
                          ...(current.config && typeof current.config === 'object' ? current.config : {}),
                          question_prompt: event.target.value,
                        },
                      }))}
                    />
                  </label>
                ) : null}
                {selectedRagCollectionSet.size === 0 ? (
                  <p className="error-text">RAG nodes require at least one selected collection.</p>
                ) : null}
                {selectedRagMode === RAG_MODE_QUERY && !String(selectedRagConfig.question_prompt || '').trim() ? (
                  <p className="error-text">RAG query mode requires a query prompt.</p>
                ) : null}
                {ragModeRequiresEmbeddingModel && embeddingModelOptions.length === 0 ? (
                  <p className="error-text">No embedding models are available for index modes.</p>
                ) : null}
                {ragModeRequiresEmbeddingModel && selectedNode.model_id != null && !selectedRagModelIsEmbedding ? (
                  <p className="error-text">Index modes require an embedding model selection.</p>
                ) : null}
              </div>
            ) : null}
            {selectedPlanNodeNeedsCompletionTarget ? (
              <p className="error-text">Complete plan item requires plan item id, stage+task keys, or completion source path.</p>
            ) : null}
            {selectedNodeType === 'decision' ? (
              <div className="stack-sm">
                <p className="toolbar-meta">Decision conditions are synced from solid outgoing connectors.</p>
                {selectedDecisionConditions.length === 0 ? (
                  <p className="toolbar-meta">Add a solid outgoing connector to define the first condition.</p>
                ) : null}
                {selectedDecisionConditions.map((entry) => (
                  <label className="field" key={entry.connectorId}>
                    <span>{`${entry.connectorId} -> ${entry.targetLabel}`}</span>
                    <input
                      type="text"
                      value={entry.conditionText}
                      onChange={(event) => {
                        const nextConditionText = event.target.value
                        updateNode(selectedNode.token, (current) => {
                          const nextConfig = current.config && typeof current.config === 'object'
                            ? { ...current.config }
                            : {}
                          const existingConditions = normalizeDecisionConditions(nextConfig.decision_conditions)
                          const conditionTextByConnector = new Map(
                            existingConditions.map((condition) => [condition.connector_id, condition.condition_text]),
                          )
                          conditionTextByConnector.set(entry.connectorId, nextConditionText)
                          const connectorIds = edges
                            .filter((edge) => (
                              edge.sourceToken === current.token
                              && normalizeEdgeMode(edge.edge_mode) === 'solid'
                            ))
                            .map((edge) => String(edge.condition_key || '').trim())
                            .filter((connectorId) => Boolean(connectorId))
                          nextConfig.decision_conditions = connectorIds.map((connectorId) => ({
                            connector_id: connectorId,
                            condition_text: conditionTextByConnector.get(connectorId) || '',
                          }))
                          return { ...current, config: nextConfig }
                        })
                      }}
                    />
                  </label>
                ))}
              </div>
            ) : null}
            {NODE_TYPES_WITH_MODEL.has(selectedNodeType) ? (
              <label className="field">
                <span>model</span>
                <select
                  value={selectedNode.model_id ?? ''}
                  onChange={(event) => updateNode(selectedNode.token, { model_id: parseOptionalInt(event.target.value) })}
                >
                  <option value="">None</option>
                  {selectedNodeModelOptions.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name || `Model ${model.id}`}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {selectedNodeType === 'rag' && ragModeRequiresEmbeddingModel && selectedNodeModelProvider && !isRagEmbeddingProvider(selectedNodeModelProvider) ? (
              <p className="error-text">RAG index modes require an embedding-capable model provider.</p>
            ) : null}
            {nodeSupportsRuntimeBindings(selectedNodeType) ? (
              <label className="chat-control flow-ws-binding-control">
                <span>agent</span>
                <select
                  value={selectedNode.config?.agent_id ?? ''}
                  onChange={(event) => {
                    const nextAgentId = parsePositiveInt(event.target.value)
                    updateNode(selectedNode.token, (current) => {
                      const nextConfig = current.config && typeof current.config === 'object'
                        ? { ...current.config }
                        : {}
                      if (nextAgentId == null) {
                        delete nextConfig.agent_id
                      } else {
                        nextConfig.agent_id = nextAgentId
                      }
                      return { ...current, config: nextConfig }
                    })
                  }}
                >
                  <option value="">None</option>
                  {agentOptions.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name || `Agent ${agent.id}`}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {nodeSupportsRuntimeBindings(selectedNodeType) ? (
              <PersistedDetails
                className="chat-picker chat-picker-group flow-ws-mcp-picker"
                storageKey="flow-ws:inspector:mcp-servers"
                defaultOpen
              >
                <summary>
                  <span className="chat-picker-summary">
                    <i className="fa-solid fa-plug" />
                    <span>MCP servers</span>
                  </span>
                </summary>
                {mcpServerOptions.length > 0 ? (
                  <div className="chat-checklist flow-ws-mcp-checklist">
                    {mcpServerOptions.map((server) => {
                      const serverId = parsePositiveInt(server?.id)
                      if (serverId == null) {
                        return null
                      }
                      const required = !selectedNodeMcpBindingsLocked && llmctlMcpServerId === serverId
                      const selectedNodeMcpServerIds = normalizeMcpServerIds(selectedNode.mcp_server_ids)
                      const checked = required || selectedNodeMcpServerIds.includes(serverId)
                      const serverName = String(server.name || `MCP ${server.id}`).trim()
                      const serverKey = String(server.server_key || '').trim()
                      return (
                        <label key={serverId} className={`flow-ws-mcp-option${required ? ' is-required' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={selectedNodeMcpBindingsLocked || required}
                            onChange={(event) => {
                              if (selectedNodeMcpBindingsLocked) {
                                return
                              }
                              const nextChecked = Boolean(event.target.checked)
                              updateNode(selectedNode.token, (current) => {
                                const currentNodeType = normalizeNodeType(current.node_type)
                                const currentServerIds = normalizeMcpServerIds(current.mcp_server_ids)
                                let nextServerIds = nextChecked
                                  ? [...currentServerIds, serverId]
                                  : currentServerIds.filter((id) => id !== serverId)
                                nextServerIds = normalizeNodeMcpServerIds(
                                  currentNodeType,
                                  nextServerIds,
                                  llmctlMcpServerId,
                                )
                                return {
                                  ...current,
                                  mcp_server_ids: nextServerIds,
                                }
                              })
                            }}
                          />
                          <span className="flow-ws-mcp-option-content">
                            <span className="flow-ws-mcp-option-title">{serverName}</span>
                            {serverKey ? (
                              <span className="muted flow-ws-mcp-option-meta">
                                {serverKey}
                                {required ? ' (required)' : ''}
                              </span>
                            ) : (
                              required ? <span className="muted flow-ws-mcp-option-meta">required</span> : null
                            )}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                ) : (
                  <p className="toolbar-meta">No MCP servers available.</p>
                )}
                {selectedNodeType === 'rag' ? (
                  <p className="toolbar-meta">RAG nodes do not support MCP servers.</p>
                ) : null}
              </PersistedDetails>
            ) : null}
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
            {NODE_TYPE_REQUIRES_REF.has(selectedNodeType) && !selectedNode.ref_id ? (
              <p className="error-text">This node type requires a ref_id before save/validate.</p>
            ) : null}
          </div>
        ) : null}

        {!selectedNode && selectedEdge ? (
          <div className="stack-sm">
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
            {selectedEdgeIsDecisionManaged ? (
              <label className="field">
                <span>connector id</span>
                <input type="text" value={selectedEdge.condition_key || ''} readOnly />
              </label>
            ) : (
              <label className="field">
                <span>condition key</span>
                <input
                  type="text"
                  value={selectedEdge.condition_key || ''}
                  onChange={(event) => updateEdge(selectedEdge.localId, { condition_key: event.target.value })}
                />
              </label>
            )}
            <label className="field">
              <span>label</span>
              <input
                type="text"
                value={selectedEdge.label || ''}
                onChange={(event) => updateEdge(selectedEdge.localId, { label: event.target.value })}
              />
            </label>
            <label className="field">
              <span>bend points</span>
              <input type="text" value={String(selectedEdgeControlPointCount)} readOnly />
            </label>
            <label className="field">
              <span>bend style</span>
              <select
                value={normalizeEdgeControlPointStyle(selectedEdge.controlPointStyle)}
                onChange={(event) => updateEdge(
                  selectedEdge.localId,
                  { controlPointStyle: normalizeEdgeControlPointStyle(event.target.value) },
                )}
              >
                {EDGE_CONTROL_STYLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            {selectedEdgeControlPointCount > 0 ? (
              <div className="form-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => updateEdge(selectedEdge.localId, { controlPoints: [] })}
                >
                  reset bends
                </button>
              </div>
            ) : null}
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
            <p className="toolbar-meta">Select a node or edge to edit.</p>
            <p className="toolbar-meta">Keyboard: Delete/Backspace removes selected node or edge.</p>
          </div>
        ) : null}
        </div>
      </aside>
    </div>
  )
})

FlowchartWorkspaceEditor.displayName = 'FlowchartWorkspaceEditor'

export default FlowchartWorkspaceEditor

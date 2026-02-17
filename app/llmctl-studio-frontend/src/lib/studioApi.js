import { requestJson } from './httpClient'

export function getBackendHealth() {
  return requestJson('/health')
}

export function getChatActivity({
  limit = 10,
  eventClass = '',
  eventType = '',
  reasonCode = '',
  threadId = '',
} = {}) {
  const params = new URLSearchParams()
  if (Number.isFinite(limit) && limit > 0) {
    params.set('limit', String(Math.floor(limit)))
  }
  const classFilter = String(eventClass || '').trim()
  if (classFilter) {
    params.set('event_class', classFilter)
  }
  const typeFilter = String(eventType || '').trim()
  if (typeFilter) {
    params.set('event_type', typeFilter)
  }
  const reasonFilter = String(reasonCode || '').trim()
  if (reasonFilter) {
    params.set('reason_code', reasonFilter)
  }
  const parsedThreadId = Number.parseInt(String(threadId || '').trim(), 10)
  if (Number.isInteger(parsedThreadId) && parsedThreadId > 0) {
    params.set('thread_id', String(parsedThreadId))
  }
  const query = params.toString()
  const path = query ? `/chat/activity?${query}` : '/chat/activity'
  return requestJson(path)
}

export function getChatThread(threadId) {
  const parsedId = Number.parseInt(String(threadId ?? ''), 10)
  if (!Number.isInteger(parsedId) || parsedId <= 0) {
    throw new Error('threadId must be a positive integer.')
  }
  return requestJson(`/chat/threads/${parsedId}`)
}

export function getChatRuntime({ threadId = '' } = {}) {
  const params = new URLSearchParams()
  const parsedThreadId = Number.parseInt(String(threadId || '').trim(), 10)
  if (String(threadId || '').trim() && (!Number.isInteger(parsedThreadId) || parsedThreadId <= 0)) {
    throw new Error('threadId must be a positive integer.')
  }
  if (Number.isInteger(parsedThreadId) && parsedThreadId > 0) {
    params.set('thread_id', String(parsedThreadId))
  }
  const query = params.toString()
  const path = query ? `/chat/runtime?${query}` : '/chat/runtime'
  return requestJson(path)
}

export function createChatThread({
  title = '',
  modelId = null,
  responseComplexity = '',
  mcpServerIds = null,
  ragCollections = null,
} = {}) {
  const body = {}
  const cleanTitle = String(title || '').trim()
  if (cleanTitle) {
    body.title = cleanTitle
  }
  if (modelId != null && String(modelId).trim() !== '') {
    const parsedModelId = Number.parseInt(String(modelId), 10)
    if (!Number.isInteger(parsedModelId) || parsedModelId <= 0) {
      throw new Error('modelId must be a positive integer when provided.')
    }
    body.model_id = parsedModelId
  }
  const cleanComplexity = String(responseComplexity || '').trim()
  if (cleanComplexity) {
    body.response_complexity = cleanComplexity
  }
  if (Array.isArray(mcpServerIds)) {
    body.mcp_server_ids = mcpServerIds
      .map((value) => Number.parseInt(String(value), 10))
      .filter((value) => Number.isInteger(value) && value > 0)
  }
  if (Array.isArray(ragCollections)) {
    body.rag_collections = ragCollections
      .map((value) => String(value || '').trim())
      .filter((value) => value)
  }
  return requestJson('/chat/threads', {
    method: 'POST',
    body,
  })
}

export function updateChatThreadConfig(
  threadId,
  {
    modelId = null,
    responseComplexity = 'medium',
    mcpServerIds = [],
    ragCollections = [],
  } = {},
) {
  const parsedThreadId = parsePositiveId(threadId, 'threadId')
  const body = {
    model_id: modelId == null || String(modelId).trim() === ''
      ? null
      : parsePositiveId(modelId, 'modelId'),
    response_complexity: String(responseComplexity || '').trim() || 'medium',
    mcp_server_ids: Array.isArray(mcpServerIds)
      ? mcpServerIds
        .map((value) => Number.parseInt(String(value), 10))
        .filter((value) => Number.isInteger(value) && value > 0)
      : [],
    rag_collections: Array.isArray(ragCollections)
      ? ragCollections
        .map((value) => String(value || '').trim())
        .filter((value) => value)
      : [],
  }
  return requestJson(`/chat/threads/${parsedThreadId}/config`, {
    method: 'POST',
    body,
  })
}

export function archiveChatThread(threadId) {
  const parsedThreadId = parsePositiveId(threadId, 'threadId')
  return requestJson(`/chat/threads/${parsedThreadId}/archive`, { method: 'POST' })
}

export function clearChatThread(threadId) {
  const parsedThreadId = parsePositiveId(threadId, 'threadId')
  return requestJson(`/chat/threads/${parsedThreadId}/clear`, { method: 'POST' })
}

export function sendChatTurn(threadId, message) {
  const parsedThreadId = parsePositiveId(threadId, 'threadId')
  const cleanMessage = String(message || '').trim()
  if (!cleanMessage) {
    throw new Error('message is required.')
  }
  return requestJson(`/chat/threads/${parsedThreadId}/turn`, {
    method: 'POST',
    body: { message: cleanMessage },
  })
}

export function getRun(runId) {
  const parsedId = Number.parseInt(String(runId ?? ''), 10)
  if (!Number.isInteger(parsedId) || parsedId <= 0) {
    throw new Error('runId must be a positive integer.')
  }
  return requestJson(`/runs/${parsedId}`)
}

export function getNodeStatus(nodeId) {
  const parsedId = Number.parseInt(String(nodeId ?? ''), 10)
  if (!Number.isInteger(parsedId) || parsedId <= 0) {
    throw new Error('nodeId must be a positive integer.')
  }
  return requestJson(`/nodes/${parsedId}/status`)
}

function parsePositiveId(value, fieldName) {
  const parsedId = Number.parseInt(String(value ?? ''), 10)
  if (!Number.isInteger(parsedId) || parsedId <= 0) {
    throw new Error(`${fieldName} must be a positive integer.`)
  }
  return parsedId
}

export function getAgents() {
  return requestJson('/agents')
}

export function getAgent(agentId) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}`)
}

export function getAgentMeta() {
  return requestJson('/agents/new')
}

export function getRoles() {
  return requestJson('/roles')
}

export function getRoleMeta() {
  return requestJson('/roles/new')
}

export function getRole(roleId) {
  const parsedId = parsePositiveId(roleId, 'roleId')
  return requestJson(`/roles/${parsedId}`)
}

export function getRoleEdit(roleId) {
  const parsedId = parsePositiveId(roleId, 'roleId')
  return requestJson(`/roles/${parsedId}/edit`)
}

export function createRole({ name = '', description = '', detailsJson = '{}' }) {
  return requestJson('/roles', {
    method: 'POST',
    body: {
      name,
      description,
      details_json: detailsJson,
    },
  })
}

export function updateRole(roleId, { name = '', description = '', detailsJson = '{}' }) {
  const parsedId = parsePositiveId(roleId, 'roleId')
  return requestJson(`/roles/${parsedId}`, {
    method: 'POST',
    body: {
      name,
      description,
      details_json: detailsJson,
    },
  })
}

export function deleteRole(roleId) {
  const parsedId = parsePositiveId(roleId, 'roleId')
  return requestJson(`/roles/${parsedId}/delete`, { method: 'POST' })
}

export function createAgent({ name = '', description = '', roleId = null }) {
  return requestJson('/agents', {
    method: 'POST',
    body: {
      name,
      description,
      role_id: roleId,
    },
  })
}

export function updateAgent(agentId, { name = '', description = '', roleId = null }) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}`, {
    method: 'POST',
    body: {
      name,
      description,
      role_id: roleId,
    },
  })
}

export function deleteAgent(agentId) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}/delete`, { method: 'POST' })
}

export function startAgent(agentId) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}/start`, { method: 'POST' })
}

export function stopAgent(agentId) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}/stop`, { method: 'POST' })
}

export function createAgentPriority(agentId, content) {
  const parsedId = parsePositiveId(agentId, 'agentId')
  return requestJson(`/agents/${parsedId}/priorities`, {
    method: 'POST',
    body: { content },
  })
}

export function updateAgentPriority(agentId, priorityId, content) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedPriorityId = parsePositiveId(priorityId, 'priorityId')
  return requestJson(`/agents/${parsedAgentId}/priorities/${parsedPriorityId}`, {
    method: 'POST',
    body: { content },
  })
}

export function moveAgentPriority(agentId, priorityId, direction) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedPriorityId = parsePositiveId(priorityId, 'priorityId')
  return requestJson(`/agents/${parsedAgentId}/priorities/${parsedPriorityId}/move`, {
    method: 'POST',
    body: { direction },
  })
}

export function deleteAgentPriority(agentId, priorityId) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedPriorityId = parsePositiveId(priorityId, 'priorityId')
  return requestJson(`/agents/${parsedAgentId}/priorities/${parsedPriorityId}/delete`, {
    method: 'POST',
  })
}

export function attachAgentSkill(agentId, skillId) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/agents/${parsedAgentId}/skills`, {
    method: 'POST',
    body: { skill_id: parsedSkillId },
  })
}

export function moveAgentSkill(agentId, skillId, direction) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/agents/${parsedAgentId}/skills/${parsedSkillId}/move`, {
    method: 'POST',
    body: { direction },
  })
}

export function detachAgentSkill(agentId, skillId) {
  const parsedAgentId = parsePositiveId(agentId, 'agentId')
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/agents/${parsedAgentId}/skills/${parsedSkillId}/delete`, {
    method: 'POST',
  })
}

function appendQuery(path, params) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value == null || value === '') {
      continue
    }
    query.set(key, String(value))
  }
  const encoded = query.toString()
  return encoded ? `${path}?${encoded}` : path
}

export function getRuns({ page = 1, perPage = 10 } = {}) {
  return requestJson(
    appendQuery('/runs', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 10,
    }),
  )
}

export function getRunMeta({ agentId = null } = {}) {
  return requestJson(appendQuery('/runs/new', { agent_id: agentId }))
}

export function getRunEdit(runId) {
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/runs/${parsedRunId}/edit`)
}

export function deleteRun(runId) {
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/runs/${parsedRunId}/delete`, { method: 'POST' })
}

export function getNodes({
  page = 1,
  perPage = 10,
  agentId = '',
  nodeType = '',
  status = '',
} = {}) {
  return requestJson(
    appendQuery('/nodes', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 10,
      agent_id: agentId,
      node_type: nodeType,
      status,
    }),
  )
}

export function getNode(nodeId) {
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/nodes/${parsedNodeId}`)
}

export function getNodeMeta() {
  return requestJson('/nodes/new')
}

const SCRIPT_TYPE_FORM_FIELDS = {
  pre_init: 'pre_init_script_ids',
  init: 'init_script_ids',
  post_init: 'post_init_script_ids',
  post_run: 'post_run_script_ids',
}

function appendFormValue(formData, key, value) {
  if (value == null || value === '') {
    return
  }
  formData.append(key, String(value))
}

function appendFormValues(formData, key, values) {
  if (!Array.isArray(values)) {
    return
  }
  for (const value of values) {
    if (value == null || value === '') {
      continue
    }
    formData.append(key, String(value))
  }
}

export function createNode({
  agentId,
  prompt,
  integrationKeys = [],
  scriptIdsByType = null,
  scriptIds = [],
  attachments = [],
} = {}) {
  const files = Array.isArray(attachments) ? attachments.filter((file) => file != null) : []
  if (files.length > 0) {
    const formData = new FormData()
    appendFormValue(formData, 'agent_id', agentId)
    appendFormValue(formData, 'prompt', prompt)
    appendFormValues(formData, 'integration_keys', integrationKeys)
    if (scriptIdsByType && typeof scriptIdsByType === 'object') {
      for (const [scriptType, values] of Object.entries(scriptIdsByType)) {
        const fieldName = SCRIPT_TYPE_FORM_FIELDS[String(scriptType)]
        if (!fieldName) {
          continue
        }
        appendFormValues(formData, fieldName, values)
      }
    }
    appendFormValues(formData, 'script_ids', scriptIds)
    for (const file of files) {
      formData.append('attachments', file)
    }
    return requestJson('/nodes/new', {
      method: 'POST',
      body: formData,
    })
  }
  return requestJson('/nodes/new', {
    method: 'POST',
    body: {
      agent_id: agentId,
      prompt,
      integration_keys: integrationKeys,
      script_ids_by_type: scriptIdsByType,
      script_ids: scriptIds,
    },
  })
}

export function cancelNode(nodeId) {
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/nodes/${parsedNodeId}/cancel`, { method: 'POST' })
}

export function deleteNode(nodeId) {
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/nodes/${parsedNodeId}/delete`, { method: 'POST' })
}

export function removeNodeAttachment(nodeId, attachmentId) {
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  const parsedAttachmentId = parsePositiveId(attachmentId, 'attachmentId')
  return requestJson(`/nodes/${parsedNodeId}/attachments/${parsedAttachmentId}/remove`, { method: 'POST' })
}

export function getQuickTaskMeta() {
  return requestJson('/quick')
}

export function createQuickTask({
  prompt,
  agentId = null,
  modelId = null,
  mcpServerIds = [],
  integrationKeys = [],
  attachments = [],
} = {}) {
  const files = Array.isArray(attachments) ? attachments.filter((file) => file != null) : []
  if (files.length > 0) {
    const formData = new FormData()
    appendFormValue(formData, 'prompt', prompt)
    appendFormValue(formData, 'agent_id', agentId)
    appendFormValue(formData, 'model_id', modelId)
    appendFormValues(formData, 'mcp_server_ids', mcpServerIds)
    appendFormValues(formData, 'integration_keys', integrationKeys)
    for (const file of files) {
      formData.append('attachments', file)
    }
    return requestJson('/quick', {
      method: 'POST',
      body: formData,
    })
  }
  return requestJson('/quick', {
    method: 'POST',
    body: {
      prompt,
      agent_id: agentId,
      model_id: modelId,
      mcp_server_ids: mcpServerIds,
      integration_keys: integrationKeys,
    },
  })
}

export function getPlans({ page = 1, perPage = 20 } = {}) {
  return requestJson(
    appendQuery('/plans', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 20,
    }),
  )
}

export function getPlan(planId) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  return requestJson(`/plans/${parsedPlanId}`)
}

export function getPlanMeta() {
  return requestJson('/plans/new')
}

export function getPlanEdit(planId) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  return requestJson(`/plans/${parsedPlanId}/edit`)
}

export function updatePlan(planId, { name = '', description = '', completedAt = '' } = {}) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  return requestJson(`/plans/${parsedPlanId}`, {
    method: 'POST',
    body: {
      name,
      description,
      completed_at: completedAt,
    },
  })
}

export function deletePlan(planId) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  return requestJson(`/plans/${parsedPlanId}/delete`, { method: 'POST' })
}

export function createPlanStage(planId, { name = '', description = '', completedAt = '' } = {}) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  return requestJson(`/plans/${parsedPlanId}/stages`, {
    method: 'POST',
    body: {
      name,
      description,
      completed_at: completedAt,
    },
  })
}

export function updatePlanStage(
  planId,
  stageId,
  { name = '', description = '', completedAt = '' } = {},
) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  const parsedStageId = parsePositiveId(stageId, 'stageId')
  return requestJson(`/plans/${parsedPlanId}/stages/${parsedStageId}`, {
    method: 'POST',
    body: {
      name,
      description,
      completed_at: completedAt,
    },
  })
}

export function deletePlanStage(planId, stageId) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  const parsedStageId = parsePositiveId(stageId, 'stageId')
  return requestJson(`/plans/${parsedPlanId}/stages/${parsedStageId}/delete`, {
    method: 'POST',
  })
}

export function createPlanTask(
  planId,
  stageId,
  { name = '', description = '', completedAt = '' } = {},
) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  const parsedStageId = parsePositiveId(stageId, 'stageId')
  return requestJson(`/plans/${parsedPlanId}/stages/${parsedStageId}/tasks`, {
    method: 'POST',
    body: {
      name,
      description,
      completed_at: completedAt,
    },
  })
}

export function updatePlanTask(
  planId,
  stageId,
  taskId,
  { name = '', description = '', completedAt = '' } = {},
) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  const parsedStageId = parsePositiveId(stageId, 'stageId')
  const parsedTaskId = parsePositiveId(taskId, 'taskId')
  return requestJson(`/plans/${parsedPlanId}/stages/${parsedStageId}/tasks/${parsedTaskId}`, {
    method: 'POST',
    body: {
      name,
      description,
      completed_at: completedAt,
    },
  })
}

export function deletePlanTask(planId, stageId, taskId) {
  const parsedPlanId = parsePositiveId(planId, 'planId')
  const parsedStageId = parsePositiveId(stageId, 'stageId')
  const parsedTaskId = parsePositiveId(taskId, 'taskId')
  return requestJson(`/plans/${parsedPlanId}/stages/${parsedStageId}/tasks/${parsedTaskId}/delete`, {
    method: 'POST',
  })
}

export function getMilestones({ page = 1, perPage = 20 } = {}) {
  return requestJson(
    appendQuery('/milestones', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 20,
    }),
  )
}

export function getMilestoneMeta() {
  return requestJson('/milestones/new')
}

export function getMilestone(milestoneId) {
  const parsedMilestoneId = parsePositiveId(milestoneId, 'milestoneId')
  return requestJson(`/milestones/${parsedMilestoneId}`)
}

export function getMilestoneEdit(milestoneId) {
  const parsedMilestoneId = parsePositiveId(milestoneId, 'milestoneId')
  return requestJson(`/milestones/${parsedMilestoneId}/edit`)
}

export function updateMilestone(
  milestoneId,
  {
    name = '',
    description = '',
    status = '',
    priority = '',
    owner = '',
    startDate = '',
    dueDate = '',
    progressPercent = 0,
    health = '',
    successCriteria = '',
    dependencies = '',
    links = '',
    latestUpdate = '',
  } = {},
) {
  const parsedMilestoneId = parsePositiveId(milestoneId, 'milestoneId')
  return requestJson(`/milestones/${parsedMilestoneId}`, {
    method: 'POST',
    body: {
      name,
      description,
      status,
      priority,
      owner,
      start_date: startDate,
      due_date: dueDate,
      progress_percent: progressPercent,
      health,
      success_criteria: successCriteria,
      dependencies,
      links,
      latest_update: latestUpdate,
    },
  })
}

export function deleteMilestone(milestoneId) {
  const parsedMilestoneId = parsePositiveId(milestoneId, 'milestoneId')
  return requestJson(`/milestones/${parsedMilestoneId}/delete`, { method: 'POST' })
}

export function getMemories({ page = 1, perPage = 20 } = {}) {
  return requestJson(
    appendQuery('/memories', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 20,
    }),
  )
}

export function getMemoryMeta() {
  return requestJson('/memories/new')
}

export function getMemory(memoryId) {
  const parsedMemoryId = parsePositiveId(memoryId, 'memoryId')
  return requestJson(`/memories/${parsedMemoryId}`)
}

export function getMemoryEdit(memoryId) {
  const parsedMemoryId = parsePositiveId(memoryId, 'memoryId')
  return requestJson(`/memories/${parsedMemoryId}/edit`)
}

export function updateMemory(memoryId, { description = '' } = {}) {
  const parsedMemoryId = parsePositiveId(memoryId, 'memoryId')
  return requestJson(`/memories/${parsedMemoryId}`, {
    method: 'POST',
    body: { description },
  })
}

export function deleteMemory(memoryId) {
  const parsedMemoryId = parsePositiveId(memoryId, 'memoryId')
  return requestJson(`/memories/${parsedMemoryId}/delete`, { method: 'POST' })
}

export function getFlowcharts() {
  return requestJson('/flowcharts')
}

export function getFlowchartMeta() {
  return requestJson('/flowcharts/new')
}

export function createFlowchart({
  name = '',
  description = '',
  maxNodeExecutions = null,
  maxRuntimeMinutes = null,
  maxParallelNodes = 1,
} = {}) {
  return requestJson('/flowcharts', {
    method: 'POST',
    body: {
      name,
      description,
      max_node_executions: maxNodeExecutions,
      max_runtime_minutes: maxRuntimeMinutes,
      max_parallel_nodes: maxParallelNodes,
    },
  })
}

export function getFlowchart(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}`)
}

export function getFlowchartEdit(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/edit`)
}

export function updateFlowchart(
  flowchartId,
  {
    name = '',
    description = '',
    maxNodeExecutions = null,
    maxRuntimeMinutes = null,
    maxParallelNodes = 1,
  } = {},
) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}`, {
    method: 'POST',
    body: {
      name,
      description,
      max_node_executions: maxNodeExecutions,
      max_runtime_minutes: maxRuntimeMinutes,
      max_parallel_nodes: maxParallelNodes,
    },
  })
}

export function deleteFlowchart(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/delete`, { method: 'POST' })
}

export function getFlowchartGraph(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/graph`)
}

export function updateFlowchartGraph(flowchartId, { nodes = [], edges = [] } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/graph`, {
    method: 'POST',
    body: { nodes, edges },
  })
}

export function validateFlowchart(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/validate`)
}

export function runFlowchart(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/run`, { method: 'POST' })
}

export function getFlowchartHistory(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/history`)
}

export function getFlowchartHistoryRun(flowchartId, runId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/history/${parsedRunId}`)
}

export function getFlowchartRun(runId) {
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/flowcharts/runs/${parsedRunId}`)
}

export function getFlowchartRunStatus(runId) {
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/flowcharts/runs/${parsedRunId}/status`)
}

export function getFlowchartRuntime(flowchartId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/runtime`)
}

export function cancelFlowchartRun(runId, { force = false } = {}) {
  const parsedRunId = parsePositiveId(runId, 'runId')
  return requestJson(`/flowcharts/runs/${parsedRunId}/cancel`, {
    method: 'POST',
    body: { force },
  })
}

export function getFlowchartNodeUtilities(flowchartId, nodeId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/utilities`)
}

export function setFlowchartNodeModel(flowchartId, nodeId, { modelId = null } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/model`, {
    method: 'POST',
    body: { model_id: modelId },
  })
}

export function attachFlowchartNodeMcp(flowchartId, nodeId, { mcpServerId } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/mcp-servers`, {
    method: 'POST',
    body: { mcp_server_id: mcpServerId },
  })
}

export function detachFlowchartNodeMcp(flowchartId, nodeId, mcpId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  const parsedMcpId = parsePositiveId(mcpId, 'mcpId')
  return requestJson(
    `/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/mcp-servers/${parsedMcpId}/delete`,
    { method: 'POST' },
  )
}

export function attachFlowchartNodeScript(flowchartId, nodeId, { scriptId } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/scripts`, {
    method: 'POST',
    body: { script_id: scriptId },
  })
}

export function detachFlowchartNodeScript(flowchartId, nodeId, scriptId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  const parsedScriptId = parsePositiveId(scriptId, 'scriptId')
  return requestJson(
    `/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/scripts/${parsedScriptId}/delete`,
    { method: 'POST' },
  )
}

export function reorderFlowchartNodeScripts(flowchartId, nodeId, { scriptIds = [] } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/scripts/reorder`, {
    method: 'POST',
    body: { script_ids: scriptIds },
  })
}

const SETTINGS_PROVIDER_IDS = ['codex', 'gemini', 'claude', 'vllm_local', 'vllm_remote']
const SETTINGS_INTEGRATION_IDS = [
  'git',
  'github',
  'jira',
  'confluence',
  'google_cloud',
  'google_workspace',
  'huggingface',
  'chroma',
]

function normalizeProviderSection(section) {
  const normalized = String(section || '').trim().toLowerCase()
  if (!normalized || normalized === 'controls') {
    return 'controls'
  }
  if (normalized === 'vllm-local') {
    return 'vllm_local'
  }
  return normalized
}

function providerSectionPath(section) {
  const normalized = normalizeProviderSection(section)
  if (normalized === 'controls') {
    return '/settings/provider'
  }
  if (normalized === 'vllm_local') {
    return '/settings/provider/vllm-local'
  }
  return `/settings/provider/${normalized}`
}

function normalizeRuntimeSection(section) {
  const normalized = String(section || '').trim().toLowerCase()
  if (!normalized || normalized === 'node') {
    return 'node'
  }
  if (normalized === 'rag' || normalized === 'chat') {
    return normalized
  }
  return 'node'
}

function runtimeSectionPath(section) {
  const normalized = normalizeRuntimeSection(section)
  if (normalized === 'node') {
    return '/settings/runtime'
  }
  return `/settings/runtime/${normalized}`
}

function normalizeIntegrationSection(section) {
  const normalized = String(section || '').trim().toLowerCase()
  if (!normalized || normalized === 'git') {
    return 'git'
  }
  if (normalized === 'google-cloud') {
    return 'google_cloud'
  }
  if (normalized === 'google-workspace') {
    return 'google_workspace'
  }
  if (SETTINGS_INTEGRATION_IDS.includes(normalized)) {
    return normalized
  }
  return 'git'
}

function integrationSectionPath(section) {
  const normalized = normalizeIntegrationSection(section)
  if (normalized === 'google_cloud') {
    return '/settings/integrations/google-cloud'
  }
  if (normalized === 'google_workspace') {
    return '/settings/integrations/google-workspace'
  }
  return `/settings/integrations/${normalized}`
}

export function getSettingsCore() {
  return requestJson('/settings/core')
}

export function getSettingsProvider({ section = 'controls' } = {}) {
  return requestJson(providerSectionPath(section))
}

export function updateSettingsProviderControls({
  defaultProvider = '',
  enabledProviders = [],
} = {}) {
  const enabled = new Set(
    Array.isArray(enabledProviders)
      ? enabledProviders.map((item) => String(item || '').trim().toLowerCase())
      : [],
  )
  const body = { default_provider: defaultProvider }
  SETTINGS_PROVIDER_IDS.forEach((provider) => {
    body[`provider_enabled_${provider}`] = enabled.has(provider)
  })
  return requestJson('/settings/provider', {
    method: 'POST',
    body,
  })
}

export function updateSettingsProviderCodex({ apiKey = '' } = {}) {
  return requestJson('/settings/provider/codex', {
    method: 'POST',
    body: { codex_api_key: apiKey },
  })
}

export function updateSettingsProviderGemini({ apiKey = '' } = {}) {
  return requestJson('/settings/provider/gemini', {
    method: 'POST',
    body: { gemini_api_key: apiKey },
  })
}

export function updateSettingsProviderClaude({ apiKey = '' } = {}) {
  return requestJson('/settings/provider/claude', {
    method: 'POST',
    body: { claude_api_key: apiKey },
  })
}

export function updateSettingsProviderVllmLocal({
  model = '',
  huggingfaceToken,
} = {}) {
  const body = { vllm_local_model: model }
  if (huggingfaceToken !== undefined) {
    body.vllm_local_hf_token = huggingfaceToken
  }
  return requestJson('/settings/provider/vllm-local', {
    method: 'POST',
    body,
  })
}

export function updateSettingsProviderVllmRemote({
  baseUrl = '',
  apiKey = '',
  model = '',
  models = '',
} = {}) {
  return requestJson('/settings/provider/vllm-remote', {
    method: 'POST',
    body: {
      vllm_remote_base_url: baseUrl,
      vllm_remote_api_key: apiKey,
      vllm_remote_model: model,
      vllm_remote_models: models,
    },
  })
}

export function getSettingsRuntime({ section = 'node' } = {}) {
  return requestJson(runtimeSectionPath(section))
}

export function updateSettingsRuntimeInstructions(flags = {}) {
  return requestJson('/settings/runtime/instructions', {
    method: 'POST',
    body: flags,
  })
}

export function updateSettingsRuntimeNodeExecutor({
  provider = 'kubernetes',
  workspaceIdentityKey = '',
  dispatchTimeoutSeconds = '',
  executionTimeoutSeconds = '',
  logCollectionTimeoutSeconds = '',
  cancelGraceTimeoutSeconds = '',
  cancelForceKillEnabled = false,
  k8sKubeconfig = '',
  k8sKubeconfigClear = false,
  k8sNamespace = '',
  k8sImage = '',
  k8sServiceAccount = '',
  k8sGpuLimit = '',
  k8sJobTtlSeconds = '',
  k8sImagePullSecretsJson = '',
  k8sInCluster = false,
} = {}) {
  return requestJson('/settings/runtime/node-executor', {
    method: 'POST',
    body: {
      provider,
      workspace_identity_key: workspaceIdentityKey,
      dispatch_timeout_seconds: dispatchTimeoutSeconds,
      execution_timeout_seconds: executionTimeoutSeconds,
      log_collection_timeout_seconds: logCollectionTimeoutSeconds,
      cancel_grace_timeout_seconds: cancelGraceTimeoutSeconds,
      cancel_force_kill_enabled: cancelForceKillEnabled,
      k8s_kubeconfig: k8sKubeconfig,
      k8s_kubeconfig_clear: k8sKubeconfigClear,
      k8s_namespace: k8sNamespace,
      k8s_image: k8sImage,
      k8s_service_account: k8sServiceAccount,
      k8s_gpu_limit: k8sGpuLimit,
      k8s_job_ttl_seconds: k8sJobTtlSeconds,
      k8s_image_pull_secrets_json: k8sImagePullSecretsJson,
      k8s_in_cluster: k8sInCluster,
    },
  })
}

export function updateSettingsRuntimeRag({
  dbProvider = '',
  embedProvider = '',
  chatProvider = '',
  openaiEmbedModel = '',
  geminiEmbedModel = '',
  openaiChatModel = '',
  geminiChatModel = '',
  chatTemperature = '',
  chatResponseStyle = '',
  chatTopK = '',
  chatMaxHistory = '',
  chatMaxContextChars = '',
  chatSnippetChars = '',
  chatContextBudgetTokens = '',
  indexParallelWorkers = '',
  embedParallelRequests = '',
} = {}) {
  return requestJson('/settings/runtime/rag', {
    method: 'POST',
    body: {
      rag_db_provider: dbProvider,
      rag_embed_provider: embedProvider,
      rag_chat_provider: chatProvider,
      rag_openai_embed_model: openaiEmbedModel,
      rag_gemini_embed_model: geminiEmbedModel,
      rag_openai_chat_model: openaiChatModel,
      rag_gemini_chat_model: geminiChatModel,
      rag_chat_temperature: chatTemperature,
      rag_chat_response_style: chatResponseStyle,
      rag_chat_top_k: chatTopK,
      rag_chat_max_history: chatMaxHistory,
      rag_chat_max_context_chars: chatMaxContextChars,
      rag_chat_snippet_chars: chatSnippetChars,
      rag_chat_context_budget_tokens: chatContextBudgetTokens,
      rag_index_parallel_workers: indexParallelWorkers,
      rag_embed_parallel_requests: embedParallelRequests,
    },
  })
}

export function updateSettingsRuntimeChat({
  historyBudgetPercent = '',
  ragBudgetPercent = '',
  mcpBudgetPercent = '',
  compactionTriggerPercent = '',
  compactionTargetPercent = '',
  preserveRecentTurns = '',
  ragTopK = '',
  defaultContextWindowTokens = '',
  maxCompactionSummaryChars = '',
  returnTo = '',
} = {}) {
  return requestJson('/settings/runtime/chat', {
    method: 'POST',
    body: {
      history_budget_percent: historyBudgetPercent,
      rag_budget_percent: ragBudgetPercent,
      mcp_budget_percent: mcpBudgetPercent,
      compaction_trigger_percent: compactionTriggerPercent,
      compaction_target_percent: compactionTargetPercent,
      preserve_recent_turns: preserveRecentTurns,
      rag_top_k: ragTopK,
      default_context_window_tokens: defaultContextWindowTokens,
      max_compaction_summary_chars: maxCompactionSummaryChars,
      return_to: returnTo,
    },
  })
}

export function getSettingsChat() {
  return requestJson('/settings/chat')
}

export function updateSettingsChatDefaults({
  defaultModelId = null,
  defaultResponseComplexity = '',
  defaultMcpServerIds = [],
  defaultRagCollections = [],
} = {}) {
  return requestJson('/settings/chat/defaults', {
    method: 'POST',
    body: {
      default_model_id: defaultModelId,
      default_response_complexity: defaultResponseComplexity,
      default_mcp_server_ids: defaultMcpServerIds,
      default_rag_collections: defaultRagCollections,
    },
  })
}

export function getSettingsIntegrations({ section = 'git' } = {}) {
  return requestJson(integrationSectionPath(section))
}

export function updateSettingsIntegrationsGit({ gitconfigContent = '' } = {}) {
  return requestJson('/settings/integrations/git', {
    method: 'POST',
    body: { gitconfig_content: gitconfigContent },
  })
}

export function updateSettingsIntegrationsGithub({
  pat = '',
  repo = '',
  clearSshKey = false,
  sshKeyFile = null,
  action = '',
} = {}) {
  if (sshKeyFile instanceof File) {
    const formData = new FormData()
    formData.append('github_pat', String(pat ?? ''))
    formData.append('github_repo', String(repo ?? ''))
    formData.append('github_ssh_key_clear', clearSshKey ? 'true' : 'false')
    formData.append('github_ssh_key', sshKeyFile)
    if (action) {
      formData.append('action', action)
    }
    return requestJson('/settings/integrations/github', {
      method: 'POST',
      body: formData,
    })
  }

  const body = {
    github_pat: pat,
    github_repo: repo,
    github_ssh_key_clear: clearSshKey,
  }
  if (action) {
    body.action = action
  }
  return requestJson('/settings/integrations/github', {
    method: 'POST',
    body,
  })
}

export function updateSettingsIntegrationsJira({
  apiKey = '',
  email = '',
  site = '',
  projectKey = '',
  board = '',
  boardLabel = '',
  action = '',
} = {}) {
  const body = {
    jira_api_key: apiKey,
    jira_email: email,
    jira_site: site,
    jira_project_key: projectKey,
    jira_board: board,
    jira_board_label: boardLabel,
  }
  if (action) {
    body.action = action
  }
  return requestJson('/settings/integrations/jira', {
    method: 'POST',
    body,
  })
}

export function updateSettingsIntegrationsConfluence({
  apiKey = '',
  email = '',
  site = '',
  space = '',
  action = '',
} = {}) {
  const body = {
    confluence_api_key: apiKey,
    confluence_email: email,
    confluence_site: site,
    confluence_space: space,
  }
  if (action) {
    body.action = action
  }
  return requestJson('/settings/integrations/confluence', {
    method: 'POST',
    body,
  })
}

export function updateSettingsIntegrationsGoogleCloud({
  serviceAccountJson = '',
  projectId = '',
} = {}) {
  return requestJson('/settings/integrations/google-cloud', {
    method: 'POST',
    body: {
      google_cloud_service_account_json: serviceAccountJson,
      google_cloud_project_id: projectId,
    },
  })
}

export function updateSettingsIntegrationsGoogleWorkspace({
  serviceAccountJson = '',
  delegatedUserEmail = '',
} = {}) {
  return requestJson('/settings/integrations/google-workspace', {
    method: 'POST',
    body: {
      workspace_service_account_json: serviceAccountJson,
      workspace_delegated_user_email: delegatedUserEmail,
    },
  })
}

export function updateSettingsIntegrationsHuggingface({ token = '' } = {}) {
  return requestJson('/settings/integrations/huggingface', {
    method: 'POST',
    body: {
      vllm_local_hf_token: token,
    },
  })
}

export function updateSettingsIntegrationsChroma({
  host = '',
  port = '',
  ssl = false,
} = {}) {
  return requestJson('/settings/integrations/chroma', {
    method: 'POST',
    body: {
      chroma_host: host,
      chroma_port: port,
      chroma_ssl: Boolean(ssl),
    },
  })
}

export function getSkills() {
  return requestJson('/skills')
}

export function getSkillMeta() {
  return requestJson('/skills/new')
}

export function createSkill({
  name = '',
  displayName = '',
  description = '',
  version = '',
  status = '',
  skillMd = '',
  sourceRef = '',
  extraFiles = [],
} = {}) {
  return requestJson('/skills', {
    method: 'POST',
    body: {
      name,
      display_name: displayName,
      description,
      version,
      status,
      skill_md: skillMd,
      source_ref: sourceRef,
      extra_files: extraFiles,
    },
  })
}

export function getSkillImportMeta() {
  return requestJson('/skills/import')
}

export function previewSkillImport({
  sourceKind = 'upload',
  localPath = '',
  sourceRef = '',
  actor = '',
  gitUrl = '',
  bundlePayload = '',
} = {}) {
  return requestJson('/skills/import', {
    method: 'POST',
    body: {
      action: 'preview',
      source_kind: sourceKind,
      local_path: localPath,
      source_ref: sourceRef,
      actor,
      git_url: gitUrl,
      bundle_payload: bundlePayload,
    },
  })
}

export function importSkillBundle({
  sourceKind = 'upload',
  localPath = '',
  sourceRef = '',
  actor = '',
  gitUrl = '',
  bundlePayload = '',
} = {}) {
  return requestJson('/skills/import', {
    method: 'POST',
    body: {
      action: 'import',
      source_kind: sourceKind,
      local_path: localPath,
      source_ref: sourceRef,
      actor,
      git_url: gitUrl,
      bundle_payload: bundlePayload,
    },
  })
}

export function getSkill(skillId, { version = '' } = {}) {
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(appendQuery(`/skills/${parsedSkillId}`, { version }))
}

export function getSkillEdit(skillId) {
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/skills/${parsedSkillId}/edit`)
}

export function updateSkill(skillId, {
  displayName = '',
  description = '',
  status = '',
  newVersion = '',
  newSkillMd = '',
  existingFiles = [],
  extraFiles = [],
  sourceRef = '',
} = {}) {
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/skills/${parsedSkillId}`, {
    method: 'POST',
    body: {
      display_name: displayName,
      description,
      status,
      new_version: newVersion,
      new_skill_md: newSkillMd,
      existing_files: existingFiles,
      extra_files: extraFiles,
      source_ref: sourceRef,
    },
  })
}

export function deleteSkill(skillId) {
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(`/skills/${parsedSkillId}/delete`, { method: 'POST' })
}

export function getScripts() {
  return requestJson('/scripts')
}

export function getScriptMeta() {
  return requestJson('/scripts/new')
}

export function createScript({
  fileName = '',
  description = '',
  scriptType = '',
  content = '',
} = {}) {
  return requestJson('/scripts', {
    method: 'POST',
    body: {
      file_name: fileName,
      description,
      script_type: scriptType,
      content,
    },
  })
}

export function getScript(scriptId) {
  const parsedScriptId = parsePositiveId(scriptId, 'scriptId')
  return requestJson(`/scripts/${parsedScriptId}`)
}

export function getScriptEdit(scriptId) {
  const parsedScriptId = parsePositiveId(scriptId, 'scriptId')
  return requestJson(`/scripts/${parsedScriptId}/edit`)
}

export function updateScript(scriptId, {
  fileName = '',
  description = '',
  scriptType = '',
  content = '',
} = {}) {
  const parsedScriptId = parsePositiveId(scriptId, 'scriptId')
  return requestJson(`/scripts/${parsedScriptId}`, {
    method: 'POST',
    body: {
      file_name: fileName,
      description,
      script_type: scriptType,
      content,
    },
  })
}

export function deleteScript(scriptId) {
  const parsedScriptId = parsePositiveId(scriptId, 'scriptId')
  return requestJson(`/scripts/${parsedScriptId}/delete`, { method: 'POST' })
}

export function getAttachments() {
  return requestJson('/attachments')
}

export function getAttachment(attachmentId) {
  const parsedAttachmentId = parsePositiveId(attachmentId, 'attachmentId')
  return requestJson(`/attachments/${parsedAttachmentId}`)
}

export function deleteAttachment(attachmentId) {
  const parsedAttachmentId = parsePositiveId(attachmentId, 'attachmentId')
  return requestJson(`/attachments/${parsedAttachmentId}/delete`, { method: 'POST' })
}

export function getModels() {
  return requestJson('/models')
}

export function getModelMeta() {
  return requestJson('/models/new')
}

export function createModel({
  name = '',
  description = '',
  provider = '',
  config = {},
} = {}) {
  return requestJson('/models', {
    method: 'POST',
    body: {
      name,
      description,
      provider,
      config,
    },
  })
}

export function getModel(modelId) {
  const parsedModelId = parsePositiveId(modelId, 'modelId')
  return requestJson(`/models/${parsedModelId}`)
}

export function getModelEdit(modelId) {
  const parsedModelId = parsePositiveId(modelId, 'modelId')
  return requestJson(`/models/${parsedModelId}/edit`)
}

export function updateModel(modelId, {
  name = '',
  description = '',
  provider = '',
  config = {},
} = {}) {
  const parsedModelId = parsePositiveId(modelId, 'modelId')
  return requestJson(`/models/${parsedModelId}`, {
    method: 'POST',
    body: {
      name,
      description,
      provider,
      config,
    },
  })
}

export function updateDefaultModel(modelId, isDefault) {
  const parsedModelId = parsePositiveId(modelId, 'modelId')
  return requestJson('/models/default', {
    method: 'POST',
    body: {
      model_id: parsedModelId,
      is_default: Boolean(isDefault),
    },
  })
}

export function deleteModel(modelId) {
  const parsedModelId = parsePositiveId(modelId, 'modelId')
  return requestJson(`/models/${parsedModelId}/delete`, { method: 'POST' })
}

export function getMcps() {
  return requestJson('/mcps')
}

export function getMcpMeta() {
  return requestJson('/mcps/new')
}

export function createMcp({
  name = '',
  serverKey = '',
  description = '',
  config = {},
} = {}) {
  return requestJson('/mcps', {
    method: 'POST',
    body: {
      name,
      server_key: serverKey,
      description,
      config,
    },
  })
}

export function getMcp(mcpId) {
  const parsedMcpId = parsePositiveId(mcpId, 'mcpId')
  return requestJson(`/mcps/${parsedMcpId}`)
}

export function getMcpEdit(mcpId) {
  const parsedMcpId = parsePositiveId(mcpId, 'mcpId')
  return requestJson(`/mcps/${parsedMcpId}/edit`)
}

export function updateMcp(mcpId, {
  name = '',
  serverKey = '',
  description = '',
  config = {},
} = {}) {
  const parsedMcpId = parsePositiveId(mcpId, 'mcpId')
  return requestJson(`/mcps/${parsedMcpId}`, {
    method: 'POST',
    body: {
      name,
      server_key: serverKey,
      description,
      config,
    },
  })
}

export function deleteMcp(mcpId) {
  const parsedMcpId = parsePositiveId(mcpId, 'mcpId')
  return requestJson(`/mcps/${parsedMcpId}/delete`, { method: 'POST' })
}

export function getGithubWorkspace({
  tab = 'pulls',
  prStatus = 'open',
  prAuthor = '',
  path = '',
} = {}) {
  return requestJson(
    appendQuery('/github', {
      tab,
      pr_status: prStatus,
      pr_author: prAuthor,
      path,
    }),
  )
}

export function getGithubPullRequest(prNumber, { tab = 'conversation' } = {}) {
  const parsedPrNumber = parsePositiveId(prNumber, 'prNumber')
  if (tab === 'commits') {
    return requestJson(`/github/pulls/${parsedPrNumber}/commits`)
  }
  if (tab === 'checks') {
    return requestJson(`/github/pulls/${parsedPrNumber}/checks`)
  }
  if (tab === 'files') {
    return requestJson(`/github/pulls/${parsedPrNumber}/files`)
  }
  return requestJson(`/github/pulls/${parsedPrNumber}`)
}

export function runGithubPullRequestCodeReview(
  prNumber,
  { prTitle = '', prUrl = '' } = {},
) {
  const parsedPrNumber = parsePositiveId(prNumber, 'prNumber')
  return requestJson(`/github/pulls/${parsedPrNumber}/code-review`, {
    method: 'POST',
    body: {
      pr_title: prTitle,
      pr_url: prUrl,
    },
  })
}

export function getJiraWorkspace() {
  return requestJson('/jira')
}

export function getJiraIssue(issueKey) {
  const normalized = String(issueKey || '').trim()
  if (!normalized) {
    throw new Error('issueKey is required.')
  }
  return requestJson(`/jira/issues/${encodeURIComponent(normalized)}`)
}

export function getConfluenceWorkspace({ page = '' } = {}) {
  return requestJson(appendQuery('/confluence', { page }))
}

export function getChromaCollections({ page = 1, perPage = 20 } = {}) {
  return requestJson(
    appendQuery('/chroma/collections', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 20,
    }),
  )
}

export function getChromaCollection(name) {
  const normalized = String(name || '').trim()
  if (!normalized) {
    throw new Error('name is required.')
  }
  return requestJson(appendQuery('/chroma/collections/detail', { name: normalized }))
}

export function deleteChromaCollection(collectionName, { next = '' } = {}) {
  const normalized = String(collectionName || '').trim()
  if (!normalized) {
    throw new Error('collectionName is required.')
  }
  return requestJson('/chroma/collections/delete', {
    method: 'POST',
    body: {
      collection_name: normalized,
      next,
    },
  })
}

export function getRagSources() {
  return requestJson('/rag/sources')
}

export function getRagSourceMeta() {
  return requestJson('/rag/sources/new')
}

export function createRagSource({
  name = '',
  kind = 'local',
  localPath = '',
  gitRepo = '',
  gitBranch = '',
  driveFolderId = '',
  indexScheduleValue = '',
  indexScheduleUnit = '',
  indexScheduleMode = 'fresh',
} = {}) {
  return requestJson('/rag/sources', {
    method: 'POST',
    body: {
      name,
      kind,
      local_path: localPath,
      git_repo: gitRepo,
      git_branch: gitBranch,
      drive_folder_id: driveFolderId,
      index_schedule_value: indexScheduleValue,
      index_schedule_unit: indexScheduleUnit,
      index_schedule_mode: indexScheduleMode,
    },
  })
}

export function getRagSource(sourceId) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}`)
}

export function getRagSourceEdit(sourceId) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}/edit`)
}

export function updateRagSource(
  sourceId,
  {
    name = '',
    kind = 'local',
    localPath = '',
    gitRepo = '',
    gitBranch = '',
    driveFolderId = '',
    indexScheduleValue = '',
    indexScheduleUnit = '',
    indexScheduleMode = 'fresh',
  } = {},
) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}`, {
    method: 'POST',
    body: {
      name,
      kind,
      local_path: localPath,
      git_repo: gitRepo,
      git_branch: gitBranch,
      drive_folder_id: driveFolderId,
      index_schedule_value: indexScheduleValue,
      index_schedule_unit: indexScheduleUnit,
      index_schedule_mode: indexScheduleMode,
    },
  })
}

export function deleteRagSource(sourceId) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}/delete`, { method: 'POST' })
}

export function quickIndexRagSource(sourceId) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}/quick-index`, { method: 'POST' })
}

export function quickDeltaIndexRagSource(sourceId) {
  const parsedSourceId = parsePositiveId(sourceId, 'sourceId')
  return requestJson(`/rag/sources/${parsedSourceId}/quick-delta-index`, { method: 'POST' })
}

export function getRagSourceStatus({ ids = [] } = {}) {
  const normalizedIds = Array.isArray(ids)
    ? ids
        .map((value) => Number.parseInt(String(value ?? ''), 10))
        .filter((value) => Number.isInteger(value) && value > 0)
    : []
  return requestJson(
    appendQuery('/rag/sources/status', {
      ids: normalizedIds.length > 0 ? normalizedIds.join(',') : '',
    }),
  )
}

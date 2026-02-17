import { requestJson } from './httpClient'

export function getBackendHealth() {
  return requestJson('/health')
}

export function getChatActivity({ limit = 10 } = {}) {
  const params = new URLSearchParams()
  if (Number.isFinite(limit) && limit > 0) {
    params.set('limit', String(Math.floor(limit)))
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

export function createNode({
  agentId,
  prompt,
  integrationKeys = [],
  scriptIdsByType = null,
  scriptIds = [],
} = {}) {
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

export function getQuickTaskMeta() {
  return requestJson('/quick')
}

export function createQuickTask({
  prompt,
  agentId = null,
  modelId = null,
  mcpServerIds = [],
  integrationKeys = [],
} = {}) {
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

export function getTaskTemplates({ page = 1, perPage = 20 } = {}) {
  return requestJson(
    appendQuery('/task-templates', {
      page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
      per_page: Number.isFinite(perPage) ? Math.max(1, Math.floor(perPage)) : 20,
    }),
  )
}

export function getTaskTemplateMeta() {
  return requestJson('/task-templates/new')
}

export function getTaskTemplate(templateId) {
  const parsedTemplateId = parsePositiveId(templateId, 'templateId')
  return requestJson(`/task-templates/${parsedTemplateId}`)
}

export function getTaskTemplateEdit(templateId) {
  const parsedTemplateId = parsePositiveId(templateId, 'templateId')
  return requestJson(`/task-templates/${parsedTemplateId}/edit`)
}

export function updateTaskTemplate(
  templateId,
  { name = '', description = '', prompt = '', agentId = null } = {},
) {
  const parsedTemplateId = parsePositiveId(templateId, 'templateId')
  return requestJson(`/task-templates/${parsedTemplateId}`, {
    method: 'POST',
    body: {
      name,
      description,
      prompt,
      agent_id: agentId,
    },
  })
}

export function removeTaskTemplateAttachment(templateId, attachmentId) {
  const parsedTemplateId = parsePositiveId(templateId, 'templateId')
  const parsedAttachmentId = parsePositiveId(attachmentId, 'attachmentId')
  return requestJson(`/task-templates/${parsedTemplateId}/attachments/${parsedAttachmentId}/remove`, {
    method: 'POST',
  })
}

export function deleteTaskTemplate(templateId) {
  const parsedTemplateId = parsePositiveId(templateId, 'templateId')
  return requestJson(`/task-templates/${parsedTemplateId}/delete`, { method: 'POST' })
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

export function attachFlowchartNodeSkill(flowchartId, nodeId, { skillId } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/skills`, {
    method: 'POST',
    body: { skill_id: skillId },
  })
}

export function detachFlowchartNodeSkill(flowchartId, nodeId, skillId) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  const parsedSkillId = parsePositiveId(skillId, 'skillId')
  return requestJson(
    `/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/skills/${parsedSkillId}/delete`,
    { method: 'POST' },
  )
}

export function reorderFlowchartNodeSkills(flowchartId, nodeId, { skillIds = [] } = {}) {
  const parsedFlowchartId = parsePositiveId(flowchartId, 'flowchartId')
  const parsedNodeId = parsePositiveId(nodeId, 'nodeId')
  return requestJson(`/flowcharts/${parsedFlowchartId}/nodes/${parsedNodeId}/skills/reorder`, {
    method: 'POST',
    body: { skill_ids: skillIds },
  })
}

const SETTINGS_PROVIDER_IDS = ['codex', 'gemini', 'claude', 'vllm_local', 'vllm_remote']

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

export function updateSettingsRuntimeNodeSkillBinding({ mode = '' } = {}) {
  return requestJson('/settings/runtime/node-skill-binding', {
    method: 'POST',
    body: { node_skill_binding_mode: mode },
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

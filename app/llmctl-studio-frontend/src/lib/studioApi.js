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

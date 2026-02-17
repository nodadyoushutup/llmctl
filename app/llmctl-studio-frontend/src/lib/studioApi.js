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

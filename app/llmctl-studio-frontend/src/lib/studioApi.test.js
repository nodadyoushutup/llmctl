import { beforeEach, describe, expect, test, vi } from 'vitest'

vi.mock('./httpClient', () => ({
  requestJson: vi.fn(),
}))

import { requestJson } from './httpClient'
import {
  attachAgentSkill,
  createAgent,
  createAgentPriority,
  deleteAgent,
  deleteAgentPriority,
  detachAgentSkill,
  getAgent,
  getAgentMeta,
  getAgents,
  getBackendHealth,
  getChatActivity,
  getChatThread,
  getNodeStatus,
  getRun,
  moveAgentPriority,
  moveAgentSkill,
  startAgent,
  stopAgent,
  updateAgent,
  updateAgentPriority,
} from './studioApi'

describe('studioApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('health and chat activity endpoints map to expected api paths', () => {
    getBackendHealth()
    getChatActivity()
    getChatActivity({ limit: 12.7 })

    expect(requestJson).toHaveBeenNthCalledWith(1, '/health')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/chat/activity?limit=10')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/chat/activity?limit=12')
  })

  test('run and node reads validate ids and call expected endpoints', () => {
    getRun('7')
    getNodeStatus(11)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/runs/7')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/nodes/11/status')
  })

  test('chat thread read validates ids and preserves critical failure messaging', () => {
    expect(() => getChatThread('')).toThrow('threadId must be a positive integer.')
    expect(() => getRun(0)).toThrow('runId must be a positive integer.')
    expect(() => getNodeStatus('bad')).toThrow('nodeId must be a positive integer.')
  })

  test('agent endpoints map to expected api paths', () => {
    getAgents()
    getAgentMeta()
    getAgent(4)
    createAgent({ name: 'A', description: 'D', roleId: 2 })
    updateAgent(4, { name: 'B', description: 'E', roleId: null })
    deleteAgent(4)
    startAgent(4)
    stopAgent(4)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/agents')
    expect(requestJson).toHaveBeenNthCalledWith(2, '/agents/new')
    expect(requestJson).toHaveBeenNthCalledWith(3, '/agents/4')
    expect(requestJson).toHaveBeenNthCalledWith(4, '/agents', {
      method: 'POST',
      body: { name: 'A', description: 'D', role_id: 2 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/agents/4', {
      method: 'POST',
      body: { name: 'B', description: 'E', role_id: null },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/agents/4/delete', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/agents/4/start', { method: 'POST' })
    expect(requestJson).toHaveBeenNthCalledWith(8, '/agents/4/stop', { method: 'POST' })
  })

  test('agent priority and skill mutation endpoints map to expected api paths', () => {
    createAgentPriority(3, 'Do high-value work first')
    updateAgentPriority(3, 7, 'Updated')
    moveAgentPriority(3, 7, 'up')
    deleteAgentPriority(3, 7)
    attachAgentSkill(3, 9)
    moveAgentSkill(3, 9, 'down')
    detachAgentSkill(3, 9)

    expect(requestJson).toHaveBeenNthCalledWith(1, '/agents/3/priorities', {
      method: 'POST',
      body: { content: 'Do high-value work first' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(2, '/agents/3/priorities/7', {
      method: 'POST',
      body: { content: 'Updated' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(3, '/agents/3/priorities/7/move', {
      method: 'POST',
      body: { direction: 'up' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(4, '/agents/3/priorities/7/delete', {
      method: 'POST',
    })
    expect(requestJson).toHaveBeenNthCalledWith(5, '/agents/3/skills', {
      method: 'POST',
      body: { skill_id: 9 },
    })
    expect(requestJson).toHaveBeenNthCalledWith(6, '/agents/3/skills/9/move', {
      method: 'POST',
      body: { direction: 'down' },
    })
    expect(requestJson).toHaveBeenNthCalledWith(7, '/agents/3/skills/9/delete', {
      method: 'POST',
    })
  })

  test('agent endpoint id validation errors are explicit', () => {
    expect(() => getAgent('bad')).toThrow('agentId must be a positive integer.')
    expect(() => deleteAgent(0)).toThrow('agentId must be a positive integer.')
    expect(() => attachAgentSkill(2, 'x')).toThrow('skillId must be a positive integer.')
    expect(() => updateAgentPriority(2, 'bad', 'x')).toThrow('priorityId must be a positive integer.')
  })
})
